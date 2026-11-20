"""Reference resolvers, link builders and the choice tables for /tokopedia/*.

ONE param per input: `product` accepts a product id OR a tokopedia.com
product link; `shop` a shop domain, a shop id OR a shop link; `category` a
category id OR a category link. Resolvers raise ValueError with a
user-facing message (RefField turns it into a 400).

Identifier shapes (www.tokopedia.com, 2026-11-20):
  * product   id   100773001007           digits; ONE variant (a size, a
                                          colour). Every call takes it.
              link /<shop domain>/<product key>   the product page; the key
                                          is the product's own slug
                                          (tomkins-daveed-...-1731945700296001445).
                                          /review after it is its review page.
              The product call takes either form; the review calls take the
              id alone (the id behind a link is one small lookup).
  * shop      domain  tomkinsofficial     the first path part of every shop
                                          and product link
              id      6638357             digits (newer shops: 19 digits)
              The shop record is asked by either; products and reviews of a
              shop by the id alone.
  * category  id      1800                digits; what the lists filter by
              link    /p/fashion-pria/sepatu-pria   one to three slugs
              The category tree (categories/list) names every id with its
              link, so one becomes the other without a call of its own.
"""
import re
from urllib.parse import quote, urlparse

from tokopedia.locations import LOCATIONS

SITE = "https://www.tokopedia.com"
HOSTS = ("tokopedia.com",)
SHORT_LINK_HOSTS = ("tk.tokopedia.com", "vt.tokopedia.com", "tokopedia.link")

CURRENCY = "IDR"                 # every price on the site is in whole rupiah

# ---- limits, each measured on 2026-11-20 -----------------------------------------------

SEARCH_PER_PAGE = 60             # the search page's own size (the call takes up to 200)
SEARCH_DEPTH = 6000              # a list serves its first 6,000 products: start=5940 answers, start=6000 is empty
MAX_SEARCH_PAGE = SEARCH_DEPTH // SEARCH_PER_PAGE          # 100
SHOP_PRODUCTS_PER_PAGE = 80      # the shop page's own size and the cap: 81 answers an empty list
MAX_SHOP_PRODUCTS_PAGE = 100
REVIEWS_PER_PAGE = 50            # the product review call refuses 51 ("Invalid Argument")
MAX_PRODUCT_REVIEWS_PAGE = 199   # page 200 of 50 answers the search engine's error; 199 passes
MAX_SHOP_REVIEWS_PAGE = 200      # 10,000 reviews: page 200 of 50 answers with has-next false
REVIEWS_DEPTH = 10000            # the review total reads 10,000 for any larger number
SHOP_SEARCH_PER_PAGE = 60        # the cap: rows=100 answers 60 (the page itself asks for 30)
MAX_SHOP_SEARCH_PAGE = 100
OPERATIONS_PER_POST = 6          # 7 operations in one POST answer HTTP 406 "Request not allowed"
MAX_BULK_PRODUCTS = 30           # our own cap: five POSTs of six
MAX_BULK_SHOPS = 100             # 100 ids answered in 2.7 s; 200 ran into the site's deadline

# The address a visitor without one gets (Jakarta Pusat), as every page sends it.
DEFAULT_CITY_ID = "176"
DEFAULT_DISTRICT_ID = "2274"

# ---- choice tables: public value -> the token the site's own links send ----------------

# product search and category lists (ob=)
SORTS = {"relevance": "23", "reviews": "5", "newest": "9", "price_high": "4", "price_low": "3"}
# a shop's product list (sort=): `default` is what the shop page sends when no order is picked
SHOP_SORTS = {"default": 1, "relevance": 23, "newest": 2, "price_high": 10, "price_low": 9,
              "most_reviewed": 11, "best_selling": 8, "most_viewed": 5, "recently_updated": 3}
# reviews (sortBy=)
REVIEW_SORTS = {"helpful": "informative_score desc", "newest": "create_time desc",
                "rating_high": "rating desc", "rating_low": "rating asc"}
CONDITIONS = {"new": "1", "used": "2"}                        # condition=
SHOP_TYPES = {"mall": "2", "power_shop": "3"}                 # shop_tier=
SHOP_TIERS = {1: "regular", 2: "mall", 3: "power_shop"}       # a row's shop tier, as the same filter names it
STOCK = {"preorder": "true", "ready": "false"}                # preorder=
LISTED_WITHIN_DAYS = (7, 14, 30, 90)                          # latest_product=
DELIVERY = {"instant": "nearby,7408193449930786576",          # shipping_child=
            "same_day": "nearby,7408193863459800833,7408194434065663761"}
RATING_4_UP = "4,5"                                           # rt=: the one rating filter the site has
REVIEW_STARS = ("1", "2", "3", "4", "5")
REVIEW_MEDIA = "image,video"

# ---- shapes ----------------------------------------------------------------------------

_ID_RE = re.compile(r"^[0-9]{1,20}$")
_DOMAIN_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,99}$")
_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._~%-]{0,299}$")
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,99}$")
TOPIC_RE = re.compile(r"^[a-z0-9_]+( [a-z0-9_]+){0,5}$")    # kualitas, "sesuai deskripsi"

# First path parts that are pages of the site, not shops (seen in its pages and scripts).
_SITE_PAGES = {"p", "search", "discovery", "catalog", "help", "terms", "privacy", "mobile-apps", "pulsa"}
# Second path parts that are a shop's own tabs, not products.
_SHOP_TABS = {"product", "review", "etalase", "sold", "info", "feed", "catalog"}
MAX_CATEGORY_DEPTH = 3

_PRODUCT_HELP = ("Must be a Tokopedia product id (100773001007) or a tokopedia.com product link "
                 "(https://www.tokopedia.com/tomkinsofficial/tomkins-daveed-hijau-hitam-sepatu-casual-anak-remaja-"
                 "1731945700296001445).")
_SHOP_HELP = ("Must be a Tokopedia shop domain (tomkinsofficial), a shop id (6638357) or a tokopedia.com shop link "
              "(https://www.tokopedia.com/tomkinsofficial).")
_CATEGORY_HELP = ("Must be a Tokopedia category id (1800) or a tokopedia.com category link "
                  "(https://www.tokopedia.com/p/fashion-pria/sepatu-pria); /tokopedia/categories/list has both.")
_LOCATION_HELP = ("Use the names of Tokopedia's own location filter (Bandung, DKI Jakarta, Jawa Barat, Kab. Bogor), "
                  "comma-separated, or its city ids (165).")


# ---- links -----------------------------------------------------------------------------

def _path_parts(value):
    """The path parts of a tokopedia.com link or of a bare site path; None
    when the value is neither. Another site's link, and a short link (it
    names nothing by itself), raise ValueError."""
    text = value.strip()
    if re.match(r"^([a-z0-9-]+\.)*tokopedia\.(com|link)/", text, re.I):
        text = "https://" + text
    if text.lower().startswith(("http://", "https://", "//")):
        parsed = urlparse(text if not text.startswith("//") else "https:" + text)
        host = (parsed.hostname or "").lower()
        if host in SHORT_LINK_HOSTS:
            raise ValueError("A short link names no product by itself: open it and pass the link it leads to.")
        if not any(host == h or host.endswith("." + h) for h in HOSTS):
            raise ValueError(f"Not a tokopedia.com link: {value[:80]}")
        path = parsed.path
    elif "/" in text:
        path = text.split("?", 1)[0].split("#", 1)[0]
    else:
        return None
    return [part for part in path.split("/") if part]


def product_link(domain, key):
    return f"{SITE}/{domain}/{key}"


def shop_link(domain):
    return f"{SITE}/{domain}" if domain else None


def category_link(path):
    return f"{SITE}/p/{path}" if path else None


def without_query(link):
    """A site link without its tracking query (?extParam=...); None for none."""
    if not link or not isinstance(link, str):
        return None
    return link.split("?", 1)[0].split("#", 1)[0] or None


def shop_domain_of(link):
    """The shop domain inside a shop or product link; None when it has none."""
    try:
        parts = _path_parts(link or "")
    except ValueError:
        return None
    if not parts or parts[0].lower() in _SITE_PAGES:
        return None
    return parts[0].lower()


def stable_image(prefix, suffix, size=700):
    """The picture link that does not expire. The site's own picture links
    are signed and run out within hours; its product data also names the two
    parts of an unsigned one, which the picture host serves as WebP
    (.../img/cache/700/<path>.jpeg.webp answered 200, the same path without
    .webp 404; 2026-11-20). None when a part is missing."""
    if not prefix or not suffix or not str(prefix).startswith("http"):
        return None
    return f"{prefix}{size}{suffix}.webp"


# ---- product ---------------------------------------------------------------------------

def is_product_id(ref):
    return bool(_ID_RE.match(ref or ""))


def resolve_product(value):
    """A product id -> the id; a product link -> '<shop domain>/<product key>'."""
    text = (value or "").strip()
    if _ID_RE.match(text):
        if len(text) < 4:
            raise ValueError(_PRODUCT_HELP)
        return text
    parts = _path_parts(text)
    if not parts:
        raise ValueError(_PRODUCT_HELP)
    if len(parts) >= 3 and parts[2].lower() == "review":
        parts = parts[:2]
    if len(parts) != 2 or parts[0].lower() in _SITE_PAGES or parts[1].lower() in _SHOP_TABS:
        raise ValueError(_PRODUCT_HELP)
    domain, key = parts[0].lower(), parts[1]
    if not _DOMAIN_RE.match(domain) or not _KEY_RE.match(key):
        raise ValueError(_PRODUCT_HELP)
    return f"{domain}/{key}"


def split_product(ref):
    """A resolved product link ref -> (shop domain, product key)."""
    domain, _, key = ref.partition("/")
    return domain, key


def product_ref_link(ref):
    """The product page of a resolved link ref."""
    return product_link(*split_product(ref))


def resolve_bulk_products(value):
    """'100773001007, <link>, ...' -> the refs joined by commas, in order,
    repeats dropped (1 to MAX_BULK_PRODUCTS)."""
    refs = []
    for part in (value or "").split(","):
        if not part.strip():
            continue
        ref = resolve_product(part)
        if ref not in refs:
            refs.append(ref)
    if not refs:
        raise ValueError(_PRODUCT_HELP)
    if len(refs) > MAX_BULK_PRODUCTS:
        raise ValueError(f"At most {MAX_BULK_PRODUCTS} products in one call.")
    return ",".join(refs)


def split_refs(joined):
    return [part for part in (joined or "").split(",") if part]


# ---- shop ------------------------------------------------------------------------------

def is_shop_id(ref):
    return bool(_ID_RE.match(ref or ""))


def resolve_shop(value):
    """A shop id -> the id; a shop domain or any link under it -> the domain."""
    text = (value or "").strip()
    if _ID_RE.match(text):
        return text
    parts = _path_parts(text)
    if parts is None:
        domain = text.lower()
    elif parts and parts[0].lower() not in _SITE_PAGES:
        domain = parts[0].lower()
    else:
        raise ValueError(_SHOP_HELP)
    if not _DOMAIN_RE.match(domain) or domain in _SITE_PAGES:
        raise ValueError(_SHOP_HELP)
    return domain


def resolve_bulk_shops(value):
    """'6638357, 1318431' -> the ids joined by commas, repeats dropped (1 to
    MAX_BULK_SHOPS). Ids only: the site's many-shops call takes nothing else."""
    ids = []
    for part in (value or "").split(","):
        part = part.strip()
        if not part:
            continue
        if not _ID_RE.match(part):
            raise ValueError(f"'{part[:40]}' is not a shop id. This endpoint takes shop ids (6638357); "
                             "/tokopedia/shops/details reads a shop by its domain or link and returns the id.")
        if part not in ids:
            ids.append(part)
    if not ids:
        raise ValueError("Give at least one shop id (6638357).")
    if len(ids) > MAX_BULK_SHOPS:
        raise ValueError(f"At most {MAX_BULK_SHOPS} shops in one call.")
    return ",".join(ids)


# ---- category --------------------------------------------------------------------------

def is_category_id(ref):
    return bool(_ID_RE.match(ref or ""))


def resolve_category(value):
    """A category id -> the id; a category link or slug path -> its path
    ('fashion-pria/sepatu-pria')."""
    text = (value or "").strip()
    if _ID_RE.match(text):
        return text
    parts = _path_parts(text)
    if parts is None:
        parts = [text]
    if parts and parts[0].lower() == "p":
        parts = parts[1:]
    parts = [part.lower() for part in parts]
    if not parts or len(parts) > MAX_CATEGORY_DEPTH or not all(_SLUG_RE.match(part) for part in parts):
        raise ValueError(_CATEGORY_HELP)
    return "/".join(parts)


def category_path_of(link):
    """'https://www.tokopedia.com/p/fashion-pria/sepatu-pria' -> 'fashion-pria/sepatu-pria'; None for none."""
    if not link or not isinstance(link, str):
        return None
    path = urlparse(link).path if "://" in link else link
    parts = [part for part in path.split("/") if part]
    if parts and parts[0] == "p":
        parts = parts[1:]
    return "/".join(parts).lower() or None


# ---- location --------------------------------------------------------------------------

def _location_key(name):
    return " ".join(name.lower().replace(".", " ").split())


_LOCATION_IDS = {_location_key(name): ids for name, ids in LOCATIONS.items()}
MAX_LOCATION_IDS = 534          # every city id of the filter in one search answered (2026-11-20)


def resolve_location(value):
    """'Bandung, Jawa Tengah' or '165,252' -> the city ids, comma-joined."""
    ids = []
    for part in (value or "").split(","):
        part = part.strip()
        if not part:
            continue
        if _ID_RE.match(part):
            found = [part]
        else:
            listed = _LOCATION_IDS.get(_location_key(part))
            if listed is None:
                raise ValueError(f"Unknown location '{part[:40]}'. {_LOCATION_HELP}")
            found = listed.split(",")
        for city in found:
            if city not in ids:
                ids.append(city)
    if not ids:
        raise ValueError(_LOCATION_HELP)
    if len(ids) > MAX_LOCATION_IDS:
        raise ValueError(f"At most {MAX_LOCATION_IDS} city ids in one search.")
    return ",".join(ids)


# ---- review filters --------------------------------------------------------------------

def review_filter(stars=None, with_media=None, topic=None):
    """The filterBy value of the review calls, built as the review page
    builds it: 'media=image,video;rating=5,4;topic=kualitas'."""
    parts = []
    if with_media:
        parts.append(f"media={REVIEW_MEDIA}")
    if stars:
        parts.append("rating=" + ",".join(stars))
    if topic:
        parts.append(f"topic={topic}")
    return ";".join(parts)


def encode_params(params):
    """{key: value} -> the query text the site's own pages put in `params`:
    keys in alphabetical order, a comma left as it is."""
    return "&".join(f"{key}={quote(str(value), safe=',')}" for key, value in sorted(params.items()))
