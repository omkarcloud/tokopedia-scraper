"""Raw answers of gql.tokopedia.com -> clean dicts for every /tokopedia/*
endpoint. Pure functions: no network, no cache.

Fixtures (tokopedia/fixtures/, captured 2026-11-20, each the `[answer]`
list one POST returned; the two product files of id 1822628908 and of id
104467229787 went through a JSON re-dump on the way, nothing else did):
search_*.json, category_*.json (the product lists), product_*.json and
products_six.json (the product page's two calls), reviews_*.json and
review_summary_*.json, shop_*.json and shops_twenty.json, categories.json.

What the site's values look like:
  * prices are whole rupiah, as numbers (309000) or as text ("Rp309.000",
    "Rp 114.880": a dot groups thousands). The product call names the
    currency "UNKNOWN"; every price here is IDR.
  * a list row's discount is in a ribbon label ("33%", ">43%"), its sold
    count in a label too ("50+ terjual", "1rb+ terjual": rb = thousand,
    jt = million), and the row's own discountPercentage is 0.
  * dates: createdAt is ISO with +07:00; review times are epoch seconds
    (product reviews) or only "8 bulan lalu" (shop reviews, replies);
    campaign dates are Jakarta clock text ("2026-08-01 00:00:00").
  * picture links are signed and expire within hours; the product call
    also names the parts of one that does not (refs.stable_image).
  * text carries HTML entities (review bodies, stock notes) and, in a
    shop's SEO text, tags.
  * some fields the site's own texts ask for come back empty for every
    visitor without a login and are left out: a list row's price range,
    free-shipping badge and ad marks (0 of 2,440 rows), a shop's courier
    list (0 of 100 shops), view and transaction counts (always 0).
"""
import re
from datetime import datetime, timedelta, timezone

from scraper_utils.dates import epoch_utc, iso_utc
from scraper_utils.text import clean, html_to_text, multiline
from scraper_utils.values import as_dict, as_list, g, number, rating as stars, to_int
from tokopedia import refs

_JAKARTA = timezone(timedelta(hours=7))
_NUMBER_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(rb|jt)?", re.I)
_UNITS = {"rb": 1000, "jt": 1000000}
# label positions of a list row that restate a field of their own
_PRICE_LABELS = ("final_price", "nett_price")
_SOLD_LABEL = "ri_product_credibility"
_DISCOUNT_LABEL = "ri_ribbon"
_COD_LABEL = "bisa cod"


# ---- values ----------------------------------------------------------------------------

def text_or_none(value):
    """A one-line text, entities unescaped; None for '' and for the site's
    placeholders of nothing ('0' is kept: it is a value)."""
    return clean(value) if isinstance(value, (str, int, float)) and not isinstance(value, bool) else None


def id_or_none(value):
    """An id as text; None for nothing and for the site's '0' / 0."""
    text = text_or_none(value)
    return None if text in (None, "0", "-1") else text


def count(value):
    """A count the site sends as a number or as digits in text ('24',
    '41930'); None for nothing and for junk."""
    out = to_int(value)
    return out if out is not None and out >= 0 else None


def rupiah(value):
    """'Rp459.000' / 'Rp 114.880' / 309000 -> the amount in whole rupiah;
    None for nothing. A dot groups thousands."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    digits = re.sub(r"[^0-9]", "", str(value).split("-")[0])
    return int(digits) if digits else None


def percent(value):
    """'33%' / '>43%' / 33 -> 33; None for nothing and for 0."""
    if isinstance(value, bool) or value is None:
        return None
    match = re.search(r"\d+(?:[.,]\d+)?", str(value))
    if not match:
        return None
    out = number(match.group(0).replace(",", "."))
    return out or None


def short_count(value):
    """The number inside a rounded count: '50+ terjual' -> 50, '1rb+' ->
    1000, '2,4jt+' -> 2400000, '71,5 rb' -> 71500; None for nothing."""
    if value is None:
        return None
    match = _NUMBER_RE.search(str(value))
    if not match:
        return None
    figure, unit = match.group(1), (match.group(2) or "").lower()
    if unit:
        return int(round(float(figure.replace(",", ".")) * _UNITS[unit]))
    return int(figure.replace(".", "").replace(",", ""))


def jakarta_time(value):
    """'2026-08-01 00:00:00' on Jakarta's clock -> '2026-07-31T17:00:00Z'; None for nothing."""
    if not value or not isinstance(value, str):
        return None
    try:
        local = datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=_JAKARTA)
    except ValueError:
        return None
    return local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def created_time(value):
    """'2025-07-15T12:18:40+07:00' -> '2025-07-15T05:18:40Z'; None for nothing
    and for the site's zero ('1970-01-01T07:00:00+07:00': no date on record)."""
    out = iso_utc(value)
    return None if out == "1970-01-01T00:00:00Z" else out


def link_or_none(value):
    return value if isinstance(value, str) and value.startswith("http") else None


def shop_tier(value):
    """1 / 2 / 3 -> regular / mall / power_shop, as the site's shop filter names them."""
    tier = to_int(value)
    return refs.SHOP_TIERS.get(tier) if tier is not None else None


def _labels(groups, title_key="title"):
    """(labels, sold label, discount percent, net amount, is COD) of a list row's label groups."""
    labels, sold, discount, net = [], None, None, None
    for group in as_list(groups):
        position, title = g(group, "position"), clean(g(group, title_key))
        if not title:
            continue
        if position == _SOLD_LABEL:
            sold = title
        elif position == _DISCOUNT_LABEL:
            discount = percent(title)
        elif position == "nett_price":
            net = rupiah(title)
        elif position not in _PRICE_LABELS and title not in labels:
            labels.append(title)
    return labels, sold, discount, net, any(label.lower() == _COD_LABEL for label in labels)


def _row_category(category_id, name, breadcrumb):
    """A list row's category: the id and name are its TOP category, the
    breadcrumb runs down to the category the product is filed in."""
    path = (text_or_none(breadcrumb) or "").strip("/").lower() or None
    return {
        "id": id_or_none(category_id),
        "name": text_or_none(name),
        "link": refs.category_link(path.split("/")[0]) if path else None,
        "leaf_path": path,
        "leaf_link": refs.category_link(path),
    }


# ---- product lists ---------------------------------------------------------------------

def _search_row(row):
    labels, sold, discount, net, is_cod = _labels(row.get("labelGroups"))
    price, shop, category, meta = (as_dict(row.get(key)) for key in ("price", "shop", "category", "meta"))
    shop_link = refs.without_query(shop.get("url"))
    amount = rupiah(price.get("number"))
    original = rupiah(price.get("original"))
    return {
        "id": id_or_none(row.get("id")),
        "parent_id": id_or_none(meta.get("parentID")),
        "name": text_or_none(row.get("name")),
        "link": refs.without_query(row.get("url")),
        "image": link_or_none(g(row, "mediaURL", "image300")) or link_or_none(g(row, "mediaURL", "image")),
        "video": link_or_none(g(row, "mediaURL", "videoCustom")),
        "price": {
            "amount": amount,
            "currency": refs.CURRENCY,
            "original_amount": original if original and original != amount else None,
            "discount_percent": discount or percent(price.get("discountPercentage")),
            "net_amount": net,
        },
        "rating": stars(row.get("rating")),
        "sold_count": short_count(sold),
        "sold_label": sold,
        "labels": labels,
        "is_cod": is_cod,
        "shop": {
            "id": id_or_none(shop.get("id")),
            "name": text_or_none(shop.get("name")),
            "domain": refs.shop_domain_of(shop_link),
            "link": shop_link,
            "city": text_or_none(shop.get("city")),
            "tier": shop_tier(shop.get("tier")),
        },
        "category": _row_category(category.get("id"), category.get("name"), category.get("breadcrumb")),
        "tiktok_shop": {
            "product_id": id_or_none(row.get("ttsProductID")),
            "sku_id": id_or_none(g(row, "stock", "ttsSKUID")),
            "seller_id": id_or_none(shop.get("ttsSellerID")),
        },
        "warehouse_id": id_or_none(meta.get("warehouseID")),
    }


def parse_search(raw):
    """searchProductV5 -> {total_count, products, redirect_link,
    suggested_query, related_query}. Past the end of a list, and for a
    search with no result, the products are [] and the total is 0."""
    header, data = as_dict(g(raw, "header")), as_dict(g(raw, "data"))
    return {
        "total_count": count(header.get("totalData")) or 0,
        "products": [_search_row(row) for row in as_list(data.get("products")) if isinstance(row, dict)],
        "redirect_link": link_or_none(g(data, "redirection", "url")),
        "suggested_query": text_or_none(g(data, "suggestion", "query")) or text_or_none(g(data, "suggestion", "suggestion")),
        "related_query": text_or_none(g(data, "related", "relatedKeyword")),
    }


def _legacy_row(row):
    labels, sold, discount, net, is_cod = _labels(row.get("labelGroups"))
    shop = as_dict(row.get("shop"))
    shop_link = refs.without_query(shop.get("url"))
    amount = rupiah(row.get("priceInt")) or rupiah(row.get("price"))
    original = rupiah(row.get("original_price"))
    path = row.get("gaKey")
    tier = "mall" if shop.get("official") else "power_shop" if shop.get("goldmerchant") else "regular"
    return {
        "id": id_or_none(row.get("id")),
        "parent_id": None,
        "name": text_or_none(row.get("name")),
        "link": refs.without_query(row.get("url")),
        "image": link_or_none(row.get("imageUrl")),
        "video": None,
        "price": {"amount": amount, "currency": refs.CURRENCY,
                  "original_amount": original if original and original != amount else None,
                  "discount_percent": discount or percent(row.get("discountPercentage")), "net_amount": net},
        "rating": stars(row.get("rating")),
        "sold_count": short_count(sold),
        "sold_label": sold,
        "labels": labels,
        "is_cod": is_cod,
        "shop": {"id": id_or_none(shop.get("id")), "name": text_or_none(shop.get("name")),
                 "domain": refs.shop_domain_of(shop_link), "link": shop_link, "city": text_or_none(shop.get("location")),
                 "tier": tier},
        "category": _row_category(row.get("catId"), None, path),
        "tiktok_shop": {"product_id": None, "sku_id": None, "seller_id": None},
        "warehouse_id": None,
    }


def parse_legacy_category(raw):
    """CategoryProducts (the category page's own list call) -> the same
    answer as parse_search, with the fields that call has."""
    return {
        "total_count": count(g(raw, "count")) or 0,
        "products": [_legacy_row(row) for row in as_list(g(raw, "data")) if isinstance(row, dict)],
        "redirect_link": None, "suggested_query": None, "related_query": None,
    }


# ---- the category tree -----------------------------------------------------------------

def _category_node(node, depth):
    link = link_or_none(node.get("url"))
    if not link and node.get("identifier"):
        link = refs.category_link(node["identifier"])
    children = [_category_node(child, depth + 1) for child in as_list(node.get("child")) if isinstance(child, dict)]
    return {
        "id": id_or_none(node.get("id")),
        "name": text_or_none(node.get("name")),
        "link": link,
        "path": refs.category_path_of(link),
        "level": depth,
        "icon": link_or_none(node.get("iconImageUrl")),
        "categories": children,
    }


def parse_categories(raw):
    """categoryAllList's categories -> the tree: top categories, each with
    the categories under it, three levels. The site's first entry, its
    "picked for you" shelf of categories that also stand in their own place
    (id 0), is left out."""
    nodes = [_category_node(node, 1) for node in as_list(raw) if isinstance(node, dict)]
    return [node for node in nodes if node["id"]]


def flatten_categories(tree, parents=()):
    """Every category of the tree with its parents: [{id, name, link, path, level, parents}]."""
    out = []
    for node in tree:
        own = {key: node[key] for key in ("id", "name", "link", "path", "level")}
        out.append({**own, "parents": list(parents)})
        out.extend(flatten_categories(node["categories"], parents + ({"id": own["id"], "name": own["name"],
                                                                      "link": own["link"]},)))
    return out


# ---- one product -----------------------------------------------------------------------

def _component(info, name):
    """The first data row of a named component of the product answer; {} when it has none."""
    for component in as_list(g(info, "components")):
        if g(component, "name") == name:
            data = as_list(component.get("data"))
            return data[0] if data and isinstance(data[0], dict) else {}
    return {}


def _images(media):
    out = []
    for item in as_list(g(media, "media")):
        if not isinstance(item, dict) or item.get("type") != "image":
            continue
        signed = link_or_none(item.get("urlMaxRes")) or link_or_none(item.get("urlOriginal"))
        stable = refs.stable_image(item.get("prefix"), item.get("suffix"))
        if not signed and not stable:
            continue
        out.append({
            "link": stable or signed,
            "signed_link": signed,
            "thumbnail": link_or_none(item.get("urlThumbnail")),
            "description": text_or_none(item.get("description")),
            "variant_option_id": id_or_none(item.get("variantOptionID")),
        })
    return out


def _videos(media):
    out = []
    for item in as_list(g(media, "media")):
        if isinstance(item, dict) and item.get("type") == "video" and link_or_none(item.get("videoUrl")):
            out.append({"link": item["videoUrl"], "source": None, "thumbnail": link_or_none(item.get("urlThumbnail"))})
    for item in as_list(g(media, "videos")):
        link = link_or_none(g(item, "url"))
        if link and all(video["link"] != link for video in out):
            out.append({"link": link, "source": text_or_none(g(item, "source")), "thumbnail": None})
    return out


def _campaign(raw, discount_key="percentageAmount", discounted_key="discountedPrice"):
    raw = as_dict(raw)
    if not raw.get("isActive") and not rupiah(raw.get("originalPrice")):
        return None
    return {
        "id": id_or_none(raw.get("campaignID")),
        "name": text_or_none(raw.get("campaignTypeName")),
        "is_active": bool(raw.get("isActive")),
        "discount_percent": percent(raw.get(discount_key)),
        "original_amount": rupiah(raw.get("originalPrice")) or None,
        "discounted_amount": rupiah(raw.get(discounted_key)) or None,
        "stock": count(raw.get("stock")),
        "original_stock": count(raw.get("originalStock")),
        "sold_percent": count(raw.get("stockSoldPercentage")),
        "starts_at": jakarta_time(raw.get("startDate")),
        "ends_at": epoch_utc(raw.get("endDateUnix")) or jakarta_time(raw.get("endDate")),
        "is_app_only": bool(raw.get("isAppsOnly")),
    }


def _pricing(amount, original_text, discount_text):
    amount, original = rupiah(amount), rupiah(original_text)
    return {
        "amount": amount,
        "currency": refs.CURRENCY,
        "original_amount": original if original and original != amount else None,
        "discount_percent": percent(discount_text),
    }


def _variants(raw):
    """The variant block: the choices (a size, a colour) and one row per
    combination that can be bought. None for a product without variants."""
    raw = as_dict(raw)
    children = [child for child in as_list(raw.get("children")) if isinstance(child, dict)]
    if not children:
        return None
    options = []
    for variant in as_list(raw.get("variants")):
        if not isinstance(variant, dict):
            continue
        options.append({
            "name": text_or_none(variant.get("name")),
            "kind": text_or_none(variant.get("identifier")),
            "values": [{
                "id": id_or_none(option.get("productVariantOptionID")),
                "value": text_or_none(option.get("value")),
                "hex": text_or_none(option.get("hex")),
                "image": link_or_none(g(option, "picture", "urlOriginal")),
                "stock": count(option.get("stock")),
            } for option in as_list(variant.get("option")) if isinstance(option, dict)],
        })
    rows = []
    for child in children:
        stock = as_dict(child.get("stock"))
        rows.append({
            "id": id_or_none(child.get("productID")),
            "name": text_or_none(child.get("productName")),
            "link": refs.without_query(child.get("productURL")),
            "options": [clean(name) for name in as_list(child.get("optionName")) if clean(name)],
            "option_ids": [str(option) for option in as_list(child.get("optionID"))],
            "price": _pricing(child.get("price"), child.get("slashPriceFmt"), child.get("discPercentage")),
            "stock": count(stock.get("stock")),
            "is_buyable": bool(stock.get("isBuyable")),
            "min_order": count(stock.get("minimumOrder")),
            "max_order": count(stock.get("maximumOrder")),
            "stock_note": html_to_text(stock.get("stockWordingHTML")),
            "is_cod": bool(child.get("isCOD")),
            "image": link_or_none(g(child, "picture", "urlOriginal")),
            "campaign": _campaign(child.get("campaignInfo"), "discountPercentage", "discountPrice"),
            "tiktok_shop": {"product_id": id_or_none(child.get("ttsPID")), "sku_id": id_or_none(child.get("ttsSKUID"))},
        })
    return {
        "parent_id": id_or_none(raw.get("parentID")),
        "default_id": id_or_none(raw.get("defaultChild")),
        "total_stock": short_count(raw.get("totalStockFmt")),
        "size_chart": link_or_none(raw.get("sizeChart")),
        "options": options,
        "items": rows,
    }


def _specs(rows):
    out = []
    for row in as_list(rows):
        name, value = text_or_none(g(row, "title")), text_or_none(g(row, "subtitle"))
        if name and value:
            out.append({"name": name, "value": value, "link": link_or_none(g(row, "applink"))})
    return out


def _category_path(category):
    path = []
    for node in as_list(g(category, "detail")):
        if isinstance(node, dict) and id_or_none(node.get("id")):
            path.append({"id": id_or_none(node.get("id")), "name": text_or_none(node.get("name")),
                         "link": link_or_none(node.get("breadcrumbURL"))})
    return path


_WEIGHT_GRAMS = {"GRAM": 1, "KILOGRAM": 1000}
_BRAND_SPEC = "merek"            # the specification row that names the brand (in the second call's list)


def _weight(basic):
    value, unit = number(basic.get("weight")), text_or_none(basic.get("weightUnit"))
    grams = None
    if value is not None and unit and unit.upper() in _WEIGHT_GRAMS:
        grams = number(round(value * _WEIGHT_GRAMS[unit.upper()], 3))
    return {"value": value, "unit": unit.lower() if unit else None, "grams": grams}


def _shipping(second, product_id):
    """The shipping estimate of this product from the second call (the
    call lists one per group of variants)."""
    chosen = None
    for estimate in as_list(second.get("ratesEstimates")):
        if not isinstance(estimate, dict):
            continue
        if chosen is None or str(product_id) in [str(p) for p in as_list(estimate.get("products"))]:
            chosen = estimate
            if str(product_id) in [str(p) for p in as_list(estimate.get("products"))]:
                break
    data = as_dict(g(chosen, "data"))
    if not data:
        return None
    notes = [clean(g(line, "text")) for line in as_list(data.get("shipmentBody")) if clean(g(line, "text"))]
    group = next((row for row in as_list(g(second, "shipmentGrouping", "shipment", "detail", "shipmentv5", "data"))
                  if str(g(row, "productID")) == str(product_id)), None)
    warehouse = as_dict(g(group, "warehouse_info"))
    free = next((row for row in as_list(g(second, "bebasOngkir", "products"))
                 if str(g(row, "productID")) == str(product_id)), None)
    return {
        "title": text_or_none(data.get("title")),
        "cheapest_amount": rupiah(data.get("cheapestShippingPrice")),
        "currency": refs.CURRENCY,
        "original_amount": rupiah(data.get("originalShippingRate")) or None,
        "notes": notes,
        "courier": text_or_none(data.get("courierLabel")),
        "arrival": text_or_none(data.get("eTAText")),
        "destination": text_or_none(data.get("destination")),
        "has_free_shipping": bool(to_int(g(free, "boType"))) if free else None,
        "is_cod": bool(g(group, "isCOD")) if group else None,
        "ships_from": {
            "city": text_or_none(warehouse.get("city_name")),
            "postal_code": text_or_none(warehouse.get("postal_code")),
            "district_id": id_or_none(warehouse.get("district_id")),
            "warehouse_id": id_or_none(warehouse.get("warehouse_id")) or id_or_none(chosen.get("warehouseID")),
            "is_fulfilled_by_tokopedia": bool(warehouse.get("is_fulfillment")) if warehouse else None,
        },
    }


def _product_shop(basic, second):
    """The shop of a product: its id and name from the first call, the
    rest from the second (None there when that call was not made)."""
    info = as_dict(g(second, "shopInfo"))
    core = as_dict(info.get("shopCore"))
    link = refs.without_query(core.get("url"))
    domain = text_or_none(core.get("domain")) or refs.shop_domain_of(basic.get("url"))
    return {
        "id": id_or_none(core.get("shopID")) or id_or_none(basic.get("shopID")),
        "name": text_or_none(core.get("name")) or text_or_none(basic.get("shopName")),
        "domain": domain,
        "link": link or refs.shop_link(domain),
        "location": text_or_none(info.get("location")),
        "tier": shop_tier(info.get("shopTier")),
        "avatar": link_or_none(g(info, "shopAssets", "avatar")),
        "badge": link_or_none(info.get("badgeURL")),
        "rating": stars(g(second, "shopRatingsQuery", "ratingScore")),
        "active_products_count": count(info.get("activeProduct")),
        "opened_at": epoch_utc(g(info, "createInfo", "epochShopCreated")),
        "last_active_at": epoch_utc(info.get("shopLastActive")),
        "is_cod": bool(info.get("isCOD")) if info else None,
        "status_message": text_or_none(g(info, "statusInfo", "statusMessage")),
        "closed_note": text_or_none(g(info, "closedInfo", "closedNote")),
        "reply_time": text_or_none(g(second, "shopTopChatSpeed", "messageResponseTime")),
        "packing_time": text_or_none(g(second, "shopPackSpeed", "speedFmt")),
        "finish_rate": text_or_none(g(second, "shopFinishRate", "finishRate")),
    }


def parse_product(info, second=None):
    """pdpMainInfo of the first product call (+ the data of the second) ->
    the product record. None when the answer names no product."""
    basic = as_dict(g(info, "data", "basicInfo"))
    product_id = id_or_none(basic.get("id")) or id_or_none(basic.get("productID"))
    if not product_id:
        return None
    second = as_dict(second)
    content = _component(info, "product_content")
    detail = _component(info, "product_detail")
    media = _component(info, "product_media")
    category = as_dict(basic.get("category"))
    stats, sold = as_dict(basic.get("stats")), as_dict(basic.get("txStats"))
    price, stock, preorder = (as_dict(content.get(key)) for key in ("price", "stock", "preorder"))
    variants = _variants(_component(info, "new_variant_options"))
    images = _images(media)
    specs = _specs(g(second, "productDetail", "content")) or _specs(detail.get("content"))
    wholesale = [{"min_quantity": count(g(tier, "minQty")), "amount": rupiah(g(tier, "price", "value")),
                  "currency": refs.CURRENCY}
                 for tier in as_list(content.get("wholesale")) if isinstance(tier, dict)]
    return {
        "id": product_id,
        "parent_id": id_or_none(g(content, "variant", "parentID")) or (variants or {}).get("parent_id"),
        "name": text_or_none(content.get("name")),
        "link": refs.without_query(basic.get("url")),
        "slug": text_or_none(basic.get("alias")),
        "brand": next((spec["value"] for spec in specs if spec["name"].lower() == _BRAND_SPEC), None),
        "description": multiline(g(detail, "productDetailDescription", "content")),
        "condition": (text_or_none(basic.get("condition")) or "").lower() or None,
        "status": (text_or_none(basic.get("status")) or "").lower() or None,
        "created_at": created_time(basic.get("createdAt")),
        "category": {
            "id": id_or_none(category.get("id")),
            "name": text_or_none(category.get("name")),
            "link": link_or_none(category.get("breadcrumbURL")),
            "path": _category_path(category),
        },
        "images": images,
        "images_count": len(images),
        "videos": _videos(media),
        "price": _pricing(price.get("value"), price.get("slashPriceFmt"), price.get("discPercentage")),
        "campaign": _campaign(content.get("campaign")),
        "wholesale": wholesale,
        "stock": count(stock.get("value")),
        "stock_note": text_or_none(stock.get("stockWording")),
        "min_order": count(basic.get("minOrder")),
        "max_order": count(basic.get("maxOrder")),
        "weight": _weight(basic),
        "specifications": specs,
        "variants": variants,
        "rating": stars(stats.get("rating")),
        "reviews_count": count(stats.get("countReview")),
        "discussions_count": count(stats.get("countTalk")),
        "sold_count": count(sold.get("countSold")),
        "sold_label": text_or_none(sold.get("itemSoldFmt")),
        "wishlist_count": count(second.get("wishlistCount")) if second else None,
        "is_official_store": bool(content.get("isOS")),
        "is_power_merchant": bool(content.get("isPowerMerchant")),
        "is_cod": bool(content.get("isCOD")),
        "is_trade_in": bool(content.get("isTradeIn")),
        "is_preorder": bool(preorder.get("isActive")),
        "preorder_days": count(preorder.get("preorderInDays")) or None,
        "cashback_percent": percent(g(content, "isCashback", "percentage")),
        "is_tokonow": bool(basic.get("isTokoNow")),
        "needs_prescription": bool(basic.get("needPrescription")),
        "is_blacklisted": bool(basic.get("isBlacklisted")),
        "shop": _product_shop(basic, second),
        "shipping": _shipping(second, product_id),
        "tiktok_shop": {
            "product_id": id_or_none(basic.get("ttsPID")),
            "sku_id": id_or_none(basic.get("ttsSKUID")),
            "shop_id": id_or_none(basic.get("ttsShopID")),
            "category_id": id_or_none(category.get("ttsID")),
            "category_path": [{"id": id_or_none(node.get("id")), "name": text_or_none(node.get("name"))}
                              for node in as_list(category.get("ttsDetail"))
                              if isinstance(node, dict) and id_or_none(node.get("id"))],
        },
        "catalog_id": id_or_none(basic.get("catalogID")),
    }


def extra_payload(info):
    """What the second product call must send back; None when the first gave none."""
    return text_or_none(g(info, "extraPayload"))


# ---- reviews ---------------------------------------------------------------------------

def _attachments(images, videos, thumbnail_key, full_key):
    pictures = [{"id": id_or_none(g(item, "attachmentID")), "link": link_or_none(g(item, full_key)),
                 "thumbnail": link_or_none(g(item, thumbnail_key))}
                for item in as_list(images) if link_or_none(g(item, full_key))]
    clips = [{"id": id_or_none(g(item, "attachmentID")), "link": link_or_none(g(item, "videoUrl"))}
             for item in as_list(videos) if link_or_none(g(item, "videoUrl"))]
    return pictures, clips


def _reply(text, when):
    text = multiline(text)
    return {"text": text, "created_ago": text_or_none(when)} if text else None


def _product_review(row):
    user, reply = as_dict(row.get("user")), as_dict(row.get("reviewResponse"))
    images, videos = _attachments(row.get("imageAttachments"), row.get("videoAttachments"), "imageThumbnailUrl", "imageUrl")
    return {
        "id": id_or_none(row.get("id")),
        "rating": count(row.get("productRating")),
        "text": multiline(row.get("message")),
        "variant": text_or_none(row.get("variantName")),
        "created_at": epoch_utc(row.get("reviewCreateTime")),
        "created_ago": text_or_none(row.get("reviewCreateTimestamp")),
        "likes_count": count(g(row, "likeDislike", "totalLike")) or 0,
        "is_anonymous": bool(row.get("isAnonymous")),
        "bad_rating_reason": text_or_none(row.get("badRatingReasonFmt")),
        "images": images,
        "videos": videos,
        "reviewer": {
            "id": id_or_none(user.get("userID")),
            "name": text_or_none(user.get("fullName")),
            "avatar": link_or_none(user.get("image")),
            "link": link_or_none(user.get("url")),
        },
        "seller_reply": _reply(reply.get("message"), reply.get("createTime")),
    }


def parse_product_reviews(raw):
    """productrevGetProductReviewList -> {product_id (the parent product
    the reviews belong to), shop, reviews, has_next, total_count}."""
    shop = as_dict(g(raw, "shop"))
    shop_link = refs.without_query(shop.get("url"))
    return {
        "product_id": id_or_none(g(raw, "productID")),
        "shop": {"id": id_or_none(shop.get("shopID")), "name": text_or_none(shop.get("name")),
                 "domain": refs.shop_domain_of(shop_link), "link": shop_link} if id_or_none(shop.get("shopID")) else None,
        "reviews": [_product_review(row) for row in as_list(g(raw, "list")) if isinstance(row, dict)],
        "has_next": bool(g(raw, "hasNext")),
        "total_count": count(g(raw, "totalReviews")) or 0,
    }


def _breakdown(rows, percent_key="percentageFloat"):
    return [{"stars": count(g(row, "rate")), "count": count(g(row, "totalReviews")) or 0,
             "percent": number(g(row, percent_key))}
            for row in as_list(rows) if isinstance(row, dict)]


def parse_rating_summary(raw):
    """productrevGetProductRatingAndTopics -> {rating, topics}; None for no answer."""
    rating = as_dict(g(raw, "rating"))
    if not raw or not rating:
        return None
    total = count(rating.get("totalRating")) or 0
    return {
        "rating": {
            "score": stars(rating.get("ratingScore")) if total else None,
            "ratings_count": total,
            "with_photo_count": count(rating.get("totalRatingWithImage")),
            "with_text_and_photo_count": count(rating.get("totalRatingTextAndImage")),
            "satisfied_percent": percent(rating.get("positivePercentageFmt")) if total else None,
            "breakdown": _breakdown(rating.get("detail")),
            "includes_tiktok_shop": bool(rating.get("isAggregatedWithTTS")),
        },
        "topics": [{"key": text_or_none(g(topic, "key")), "name": text_or_none(g(topic, "formatted")),
                    "rating": stars(g(topic, "rating")), "reviews_count": count(g(topic, "reviewCount")) or 0}
                   for topic in as_list(g(raw, "topics")) if text_or_none(g(topic, "key"))],
    }


def _shop_review(row):
    product, state = as_dict(row.get("product")), as_dict(row.get("state"))
    images, videos = _attachments(row.get("attachments"), row.get("videoAttachments"), "thumbnailURL", "fullsizeURL")
    return {
        "id": id_or_none(row.get("id")),
        "rating": count(row.get("rating")),
        "text": multiline(row.get("reviewText")),
        "created_ago": text_or_none(row.get("reviewTime")),
        "likes_count": count(g(row, "likeDislike", "totalLike")) or 0,
        "is_anonymous": bool(state.get("isAnonymous")),
        "bad_rating_reason": text_or_none(row.get("badRatingReasonFmt")),
        "images": images,
        "videos": videos,
        "product": {
            "id": id_or_none(product.get("productID")),
            "name": text_or_none(product.get("productName")),
            "link": refs.without_query(product.get("productPageURL")),
            "image": link_or_none(product.get("productImageURL")),
            "variant_id": id_or_none(g(product, "productVariant", "variantID")),
            "variant": text_or_none(g(product, "productVariant", "variantName")),
            "is_deleted": bool(product.get("isDeletedProduct")),
        },
        "reviewer": {
            "id": id_or_none(row.get("reviewerID")),
            "name": text_or_none(row.get("reviewerName")),
            "avatar": link_or_none(row.get("avatar")),
        },
        "seller_reply": _reply(row.get("replyText"), row.get("replyTime")),
    }


def parse_shop_reviews(raw):
    """productrevGetShopReviewReadingList -> {shop_name, reviews, has_next, total_count}."""
    return {
        "shop_name": text_or_none(g(raw, "shopName")),
        "reviews": [_shop_review(row) for row in as_list(g(raw, "list")) if isinstance(row, dict)],
        "has_next": bool(g(raw, "hasNext")),
        "total_count": count(g(raw, "totalReviews")) or 0,
    }


# ---- shops -----------------------------------------------------------------------------

def _month(value):
    """'December 2022' -> '2022-12'; None when it reads otherwise."""
    try:
        return datetime.strptime(str(value).strip(), "%B %Y").strftime("%Y-%m")
    except (ValueError, TypeError):
        return None


def parse_shop(row):
    """One shopInfoByID result row -> the shop record (without the rating
    block and the description, which other operations hold). None for a
    row that names no shop."""
    core = as_dict(g(row, "shopCore"))
    shop_id = id_or_none(core.get("shopID"))
    if not shop_id:
        return None
    gold, stats, status, closed = (as_dict(g(row, key)) for key in ("goldOS", "shopStats", "statusInfo", "closedInfo"))
    domain = text_or_none(core.get("domain"))
    return {
        "id": shop_id,
        "domain": domain,
        "name": text_or_none(core.get("name")),
        "link": refs.shop_link(domain),
        "description": None,
        "location": text_or_none(g(row, "location")),
        "city": text_or_none(g(row, "shippingLoc", "cityName")),
        "district": text_or_none(g(row, "shippingLoc", "districtName")),
        "opened_month": _month(g(row, "createInfo", "openSince")),
        "tier": shop_tier(gold.get("shopTier")),
        "is_official": bool(gold.get("isOfficial")),
        "is_power_merchant": bool(gold.get("isGold")),
        "is_open": bool(g(row, "isOpen")),
        "status_title": text_or_none(status.get("statusTitle")),
        "status_message": text_or_none(status.get("statusMessage")),
        "closed_note": text_or_none(closed.get("closedNote")),
        "closed_until": text_or_none(closed.get("until")),
        "followers_count": count(g(row, "favoriteData", "totalFavorite")),
        "active_products_count": count(g(row, "activeProduct")),
        "products_sold_count": count(stats.get("productSold")),
        "transactions_count": count(stats.get("totalTxSuccess")),
        "showcases_count": count(stats.get("totalShowcase")),
        "rating": None,
        "satisfaction": None,
        "reputation": None,
        "avatar": link_or_none(g(row, "shopAssets", "avatar")),
        "cover": link_or_none(g(row, "shopAssets", "cover")),
        "badge": link_or_none(gold.get("badge")),
        "share_image": link_or_none(g(row, "shopSnippetURL")),
        "seo": {
            "title": text_or_none(g(row, "customSEO", "title")),
            "description": text_or_none(g(row, "customSEO", "description")),
            "text": html_to_text(g(row, "customSEO", "bottomContent")),
        },
    }


def parse_shop_statistic(data):
    """The data of ShopStatisticQuery -> {rating, satisfaction, reputation}."""
    rating = as_dict(g(data, "shopRating"))
    total = count(rating.get("totalRating")) or 0
    month = as_dict(g(data, "shopSatisfaction", "recentOneMonth"))
    reputation = next((item for item in as_list(g(data, "shopReputation")) if isinstance(item, dict)), None)
    return {
        "rating": {
            "score": stars(rating.get("ratingScore")) if total else None,
            "ratings_count": total,
            "breakdown": _breakdown(rating.get("detail")),
        } if rating else None,
        "satisfaction": {"good": count(month.get("good")) or 0, "neutral": count(month.get("neutral")) or 0,
                         "bad": count(month.get("bad")) or 0} if month else None,
        "reputation": {"score": text_or_none(reputation.get("score")), "badge": link_or_none(reputation.get("badge"))}
        if reputation else None,
    }


def parse_shop_description(data, shop_id):
    """The data of GetShopDescription -> the description of this shop; None for none."""
    for row in as_list(g(data, "getShopDescription", "result")):
        if isinstance(row, dict) and str(row.get("shopID")) == str(shop_id):
            return multiline(row.get("description"))
    return None


def _shop_product(row):
    labels, sold, discount, net, is_cod = _labels(row.get("label_groups"))
    flags, campaign = as_dict(row.get("flags")), as_dict(row.get("campaign"))
    amount = rupiah(g(row, "price", "text_idr"))
    original = rupiah(campaign.get("original_price_fmt"))
    image = as_dict(row.get("primary_image"))
    return {
        "id": id_or_none(row.get("product_id")),
        "name": text_or_none(row.get("name")),
        "link": refs.without_query(row.get("product_url")),
        "image": link_or_none(image.get("resize300")) or link_or_none(image.get("original")),
        "price": {
            "amount": amount,
            "currency": refs.CURRENCY,
            "original_amount": original if original and original != amount else None,
            "discount_percent": discount or percent(campaign.get("discounted_percentage")),
            "net_amount": net,
        },
        "rating": stars(g(row, "stats", "averageRating")),
        "sold_count": short_count(sold),
        "sold_label": sold,
        "labels": labels,
        "is_cod": is_cod,
        "is_sold_out": bool(flags.get("isSold")),
        "is_preorder": bool(flags.get("isPreorder")),
        "is_wholesale": bool(flags.get("isWholesale")),
    }


def parse_shop_products(raw):
    """GetShopProduct -> {products, has_next}."""
    return {
        "products": [_shop_product(row) for row in as_list(g(raw, "data")) if isinstance(row, dict)],
        "has_next": bool(g(raw, "links", "next")),
    }


def _found_shop(row):
    domain = text_or_none(row.get("shop_domain"))
    return {
        "id": id_or_none(row.get("shop_id")),
        "domain": domain,
        "name": text_or_none(row.get("shop_name")),
        "link": refs.without_query(row.get("shop_url")) or refs.shop_link(domain),
        "location": text_or_none(row.get("shop_location")),
        "tag_line": text_or_none(row.get("shop_tag_line")),
        "description": multiline(row.get("shop_description")),
        "image": link_or_none(row.get("shop_image")),
        "is_official": bool(row.get("is_official")),
        "is_power_merchant": bool(row.get("shop_gold_shop")),
        "is_power_merchant_pro": bool(row.get("is_pm_pro")),
        "is_open": row.get("shop_status") == 1,
        "followers_count": short_count(row.get("shop_total_favorite")),
        "reputation_score": count(row.get("reputation_score")) or None,
        "has_free_shipping_voucher": bool(g(row, "voucher", "free_shipping")),
        "cashback": number(g(row, "voucher", "cashback", "cashback_value")) or None,
        "is_cashback_percent": bool(g(row, "voucher", "cashback", "is_percentage")),
        "products": [{
            "id": id_or_none(g(product, "id")),
            "name": text_or_none(g(product, "name")),
            "link": refs.without_query(g(product, "url")),
            "image": link_or_none(g(product, "image_url")),
            "price": {"amount": rupiah(g(product, "price")), "currency": refs.CURRENCY},
        } for product in as_list(row.get("products")) if isinstance(product, dict)],
    }


def parse_shop_search(raw):
    """aceSearchShop -> {total_count, shops, suggested_query}."""
    return {
        "total_count": count(g(raw, "header", "total_data")) or 0,
        "shops": [_found_shop(row) for row in as_list(g(raw, "shops")) if isinstance(row, dict)],
        "suggested_query": text_or_none(g(raw, "suggestion", "query")),
    }
