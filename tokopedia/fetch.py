"""Tokopedia transport: plain curl_cffi with chrome TLS on the GraphQL host
the site's own pages call (gql.tokopedia.com). No browser, no login, no
cookie, no token: every call goes out as a brand-new visitor. Egress: one
session per thread on the exit config.TOKOPEDIA_EXIT names — the pod's own
IP, which answered every call here (pod probes 2026-11-20, tables in
notes/config/tokopedia.md). A retryable failure drops the session, so the
retry rides a fresh connection.

Every call is a POST to /graphql/<operation name> whose body is a LIST of
operations, [{operationName, variables, query}], and whose answer is the
list of their answers in the same order. One POST carries at most six
operations (seven answer HTTP 406 "Request not allowed"; so do aliases
inside one operation). The texts are in tokopedia/queries.py.

The calls (2026-11-20):

  SEARCH    SearchProductV5Query {params}: the search page's product list.
            `params` is a query text of its own (q, page, rows, start, ob =
            the order, and one key per filter). 60 products a page (the call
            takes up to 200), the first 6,000 of a list, a total in the
            header; past the end the list is empty and the total reads 0.
            With sc=<category id>, an empty q and source=directory it is a
            category's list (60 a page there: 100 answers nothing).
  CATEGORY  SearchProductQuery {params}: the category page's own, older
            list call. Fewer fields per product; the fallback of the above.
  PRODUCT   PDPMainInfo {productID | shopDomain + productKey, userLocation,
            source: "P1"}: the product page's first call. It answers
            "header not valid" without x-tkpd-akamai: pdpMainInfo.
  SECOND    PDPSecondaryInfo {productID, extraPayload, source: "P2"}: the
            page's second call (shop, wishlist count, shipping estimate). It
            answers "pdp: error unmarshal" without the extraPayload the
            first call returned. One from a browser passed 25 minutes later
            from another client, so it is tied to neither.
  PRODUCT ID  getMiniProductInfo {productURL}: the id behind a product link.
  REVIEWS   productReviewList {productID, page, limit, sortBy, filterBy} and
            productRatingAndTopics {productID}, in one POST. 50 a page at
            most (51: "Invalid Argument"); page x limit stops short of
            10,000 (the search engine's error after). A sort the site does
            not know is silently read as newest, so only known ones are sent.
  SHOP      ShopInfoCore {id, domain}; ShopStatisticQuery {shopID,
            shopIDStr}; GetShopDescription {input{shopIDsString}}. Asked by
            id, the three go in one POST; asked by domain, the first names
            the id the other two need.
  SHOPS     ShopInfoCore with a list of ids: 100 answered in 2.7 s, 200 ran
            into the site's deadline ("context deadline exceeded").
  SHOP PRODUCTS  ShopProducts {sid, page, perPage, sort, keyword}: 80 a page
            at most (81 answers an empty list), a next flag and no total.
  SHOP REVIEWS   ReviewList {shopID, page, limit, sortBy, filterBy}.
  SHOP SEARCH    AceSearchShopQuery {params}: 60 shops a page at most.
  CATEGORIES     categoryAllList {}: the whole tree (about 450 KB).

Errors arrive as HTTP 200 with an `errors` list next to a null `data`:
"product: not found", "Shop Not Found", "Category Not Found" (codes 5,
404, 2001) -> not found; "Invalid Argument" (code 3) -> bad request.

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  TokopediaUpstreamError  transport failure / 5xx / an error answer — retryable
  TokopediaBlocked        401 / 403 / 429 / a page instead of JSON  — retryable
  TokopediaBadRequest     the site's "Invalid Argument"             — never retried
  TokopediaNotFound       unknown product, shop or category         — never retried
"""
import json
import os
import sys
import threading
import uuid
from datetime import datetime, timezone

# Allow direct execution (python tokopedia/fetch.py): flat imports resolve
# like under the server. Idempotent when imported normally.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import egress
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError
from scraper_utils import retry, sessions
from tokopedia import queries, refs

IMPERSONATE = "chrome"
TIMEOUT = 30             # a search page is about 270 KB, the category tree 450 KB; both answer within 1.5 s

GRAPHQL = "https://gql.tokopedia.com/graphql/"

_NOT_FOUND_CODES = (5, 404, 2001)
_BAD_REQUEST_CODES = (3,)
_NOT_FOUND_TEXT = "not found"


class TokopediaUpstreamError(UpstreamError):
    """Transport failure, 5xx, or an error answer of the site — retryable."""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class TokopediaBlocked(TokopediaUpstreamError, Blocked):
    """401 / 403 / 429, or a page where JSON was due — retryable."""


class TokopediaBadRequest(BadRequest):
    """The site rejected the arguments — never retried."""


class TokopediaNotFound(NotFound):
    """No such product, shop or category — never retried."""


# ---- the headers, as the site's own pages send them ----------------------------------------
# From the captured calls (2026-11-20): every header with its value. Left to
# the session: user-agent, the sec-ch-ua client hints, accept-language (it
# follows the exit) and accept-encoding. x-version is the site's build of
# that day; the calls answered alike with it, with another value and
# without it. x-date is the page's clock at the time of the call.

_COMMON = {
    "accept": "*/*",
    "bd-device-id": "",
    "content-type": "application/json",
    "origin": refs.SITE,
    "priority": "u=1, i",
    "referer": refs.SITE + "/",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-site",
    "x-price-center": "false",
    "x-source": "tokopedia-lite",
    "x-tkpd-lite-service": "zeus",
    "x-version": "3ea8f2e",
}
# the search page's product list (SearchProductV5Query)
SEARCH_HEADERS = {**_COMMON, "bd-web-id": "", "iris_session_id": "", "tkpd-userid": "", "x-dark-mode": "false",
                  "x-device": "desktop-0.0"}
# the product page's two calls (PDPSecondaryInfo as captured; PDPMainInfo is sent the same way by the page's server)
PRODUCT_HEADERS = {**_COMMON, "x-device": "desktop", "x-tkpd-akamai": "pdpMainInfo", "x-tkpd-pdpb": "0"}
# the product page's review calls (productReviewList)
REVIEW_HEADERS = {**_COMMON, "x-device": "desktop", "x-tkpd-pdpb": "0"}
# the shop page's calls (ShopProducts)
SHOP_HEADERS = {**_COMMON, "x-device": "default_v3"}
# the shop search page's list (AceSearchShopQuery): the common set alone
SHOP_SEARCH_HEADERS = dict(_COMMON)


def _x_date():
    """The x-date of a product call: the clock, written the way the page writes it."""
    return datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")


def _product_headers():
    return {**PRODUCT_HEADERS, "x-date": _x_date()}


# ---- sessions --------------------------------------------------------------------------

# One curl session per request thread (a curl handle must not be shared
# across threads). The calls are stateless: nothing is carried between them.
_local = threading.local()


def _session():
    return sessions.thread_session(
        _local, lambda: egress.exit_session(config.TOKOPEDIA_EXIT, impersonate=IMPERSONATE))


def _drop_session():
    """Close the thread's session so the retry rides a fresh connection / exit."""
    sessions.drop(_local)


def _retrying(fn):
    """fn() under the shared retry policy: only TokopediaUpstreamError
    (Blocked included) is retried; NotFound and BadRequest surface at once."""
    return retry.run(fn, config, TokopediaUpstreamError, lambda e: _drop_session())


# ---- one POST --------------------------------------------------------------------------

def _operation(named, variables):
    name, text = named
    return {"operationName": name, "variables": variables, "query": text}


def _send(operations, headers, label):
    """POST a list of operations -> the list of their answers."""
    if len(operations) > refs.OPERATIONS_PER_POST:
        raise ValueError(f"{len(operations)} operations in one POST; the site takes {refs.OPERATIONS_PER_POST}")
    sess = _session()
    sess.cookies.clear()        # a brand-new visitor every time: nothing here needs a cookie
    url = GRAPHQL + operations[0]["operationName"]
    try:
        resp = sess.post(url, data=json.dumps(operations, separators=(",", ":")), headers=headers, timeout=TIMEOUT)
    except Exception as e:
        raise TokopediaUpstreamError(f"request failed for {label}: {type(e).__name__}: {e}")
    status = resp.status_code
    if status in (401, 403, 429):
        raise TokopediaBlocked(f"HTTP {status} for {label}", status)
    if status >= 500:
        raise TokopediaUpstreamError(f"HTTP {status} for {label}", status)
    try:
        answers = resp.json()
    except Exception:
        raise TokopediaBlocked(f"non-JSON answer for {label} (HTTP {status}): {resp.text[:120]!r}", status)
    if isinstance(answers, dict):
        answers = [answers]
    if status != 200 or not isinstance(answers, list) or len(answers) != len(operations):
        raise TokopediaUpstreamError(f"HTTP {status} for {label}: {error_text(answers)[:200]}", status)
    return answers


def error_of(answer):
    """(code, message) of an answer's first error; (None, '') when it has none."""
    errors = answer.get("errors") if isinstance(answer, dict) else None
    if not isinstance(errors, list) or not errors or not isinstance(errors[0], dict):
        return None, ""
    first = errors[0]
    extensions = first.get("extensions") if isinstance(first.get("extensions"), dict) else {}
    code = extensions.get("code", extensions.get("Code"))
    message = " / ".join(str(part) for part in (first.get("message"), extensions.get("moreInfo")) if part)
    return code, message


def error_text(answers):
    for answer in answers if isinstance(answers, list) else [answers]:
        _, message = error_of(answer)
        if message:
            return message
    return ""


def data_of(answer, label):
    """The `data` of one answer; its error raised as ours: not found ->
    TokopediaNotFound, "Invalid Argument" -> TokopediaBadRequest, anything
    else -> TokopediaUpstreamError (retryable)."""
    code, message = error_of(answer)
    if message or code is not None:
        if code in _NOT_FOUND_CODES or _NOT_FOUND_TEXT in message.lower():
            raise TokopediaNotFound(f"{label} not found")
        if code in _BAD_REQUEST_CODES:
            raise TokopediaBadRequest(f"Tokopedia rejected {label}: {message}")
        raise TokopediaUpstreamError(f"the site answered an error for {label}: {message[:200]}")
    data = answer.get("data") if isinstance(answer, dict) else None
    if not isinstance(data, dict):
        raise TokopediaUpstreamError(f"unexpected answer for {label}: {str(answer)[:120]!r}")
    return data


def _one(named, variables, headers, label):
    """One operation -> its `data`."""
    def once():
        return data_of(_send([_operation(named, variables)], headers, label)[0], label)
    return _retrying(once)


def _field(data, name, label):
    value = data.get(name)
    if value is None:
        raise TokopediaUpstreamError(f"no {name} in the answer for {label}")
    return value


# ---- lists -----------------------------------------------------------------------------

def _location_params():
    return {"user_addressId": "", "user_cityId": refs.DEFAULT_CITY_ID, "user_districtId": refs.DEFAULT_DISTRICT_ID,
            "user_lat": "", "user_long": "", "user_postCode": "", "user_warehouseId": "", "warehouses": ""}


def search_params(query, page, sort, filters=None):
    """The `params` of a keyword search, key for key what the search page sends."""
    params = {
        "device": "desktop", "enter_method": "normal_search", "l_name": "sre", "ob": sort, "page": page, "q": query,
        "related": "true", "rows": refs.SEARCH_PER_PAGE, "safe_search": "false", "sc": "", "scheme": "https",
        "shipping": "", "show_adult": "false", "source": "search", "st": "product",
        "start": (page - 1) * refs.SEARCH_PER_PAGE, "topads_bucket": "true", "unique_id": uuid.uuid4().hex,
        "user_id": "", "variants": "", **_location_params(),
    }
    params.update(filters or {})
    return refs.encode_params(params)


def category_params(category_id, page, sort, filters=None):
    """The `params` of a category's list through the search call."""
    params = {"device": "desktop", "ob": sort, "page": page, "q": "", "rows": refs.SEARCH_PER_PAGE,
              "source": "directory", "st": "product", "start": (page - 1) * refs.SEARCH_PER_PAGE}
    params.update(filters or {})
    params["sc"] = category_id
    return refs.encode_params(params)


def legacy_category_params(category_id, path, page, sort, filters=None):
    """The `params` of the category page's own list call (it counts from 1)."""
    params = {"ob": sort, "identifier": (path or "").replace("/", "_"), "sc": category_id, "user_id": "0",
              "rows": refs.SEARCH_PER_PAGE, "start": (page - 1) * refs.SEARCH_PER_PAGE + 1, "source": "directory",
              "device": "desktop", "page": page, "related": "true", "st": "product", "safe_search": "false"}
    params.update(filters or {})
    params["sc"] = category_id
    return "&" + "&".join(f"{key}={value}" for key, value in params.items())


def fetch_search(params):
    """One page of the product list for a `params` text -> searchProductV5."""
    label = "product list"
    return _field(_one(queries.SEARCH_PRODUCTS, {"params": params}, SEARCH_HEADERS, label), "searchProductV5", label)


def fetch_category_legacy(params):
    """One page of a category through the category page's own call -> CategoryProducts."""
    label = "category list"
    data = _one(queries.CATEGORY_PRODUCTS_LEGACY, {"params": params}, SEARCH_HEADERS, label)
    return _field(data, "CategoryProducts", label)


def fetch_categories():
    """The whole category tree -> its list of top categories."""
    label = "category tree"
    tree = _field(_one(queries.CATEGORIES, {}, SEARCH_HEADERS, label), "CategoryAllList", label)
    return tree.get("categories") or []


# ---- products --------------------------------------------------------------------------

def _user_location():
    return {"addressID": "", "cityID": refs.DEFAULT_CITY_ID, "districtID": refs.DEFAULT_DISTRICT_ID, "latlon": "",
            "postalCode": ""}


def _product_variables(ref):
    if refs.is_product_id(ref):
        product_id, domain, key = ref, "", ""
    else:
        product_id = ""
        domain, key = refs.split_product(ref)
    return {"productID": product_id, "productKey": key, "shopDomain": domain, "layoutID": "", "extraPayload": "",
            "queryParam": "", "source": "P1", "userLocation": _user_location()}


def fetch_product(ref):
    """The product page's first call for an id or a '<domain>/<key>' ref -> pdpMainInfo."""
    label = f"product {ref}"
    data = _one(queries.PRODUCT, _product_variables(ref), _product_headers(), label)
    info = data.get("pdpMainInfo")
    if not isinstance(info, dict):
        raise TokopediaNotFound(f"{label} not found")
    return info


def fetch_product_second(product_id, extra_payload):
    """The product page's second call -> its pdpMainInfo.data (shop, wishlist, shipping)."""
    label = f"shop block of product {product_id}"
    variables = {"productID": product_id, "layoutID": "", "extraPayload": extra_payload, "queryParam": "",
                 "source": "P2", "userLocation": _user_location()}
    info = _field(_one(queries.PRODUCT_SECOND, variables, _product_headers(), label), "pdpMainInfo", label)
    return info.get("data") or {}


def fetch_products(product_refs):
    """Up to six products in one POST -> [pdpMainInfo or None], aligned
    with the refs; None for a product the site does not know."""
    label = f"{len(product_refs)} products"
    operations = [_operation(queries.PRODUCT, _product_variables(ref)) for ref in product_refs]

    def once():
        out = []
        for ref, answer in zip(product_refs, _send(operations, _product_headers(), label)):
            try:
                out.append(data_of(answer, f"product {ref}").get("pdpMainInfo"))
            except TokopediaNotFound:
                out.append(None)
        return out
    return _retrying(once)


def fetch_product_id(ref):
    """The id of the product behind a '<domain>/<key>' ref."""
    label = f"product {ref}"
    variables = {"productURL": refs.product_ref_link(ref),
                 "userLocation": {"addressID": "", "districtID": refs.DEFAULT_DISTRICT_ID, "latlon": "",
                                  "postalCode": ""}}
    data = _one(queries.PRODUCT_ID, variables, REVIEW_HEADERS, label)
    product = (data.get("productrevGetMiniProductInfo") or {}).get("product") or {}
    if not product.get("id") or str(product["id"]) == "0":
        raise TokopediaNotFound(f"{label} not found")
    return str(product["id"])


def fetch_product_reviews(product_id, page, sort, filter_by):
    """One page of a product's reviews and its rating summary, in one
    POST -> (productrevGetProductReviewList, productrevGetProductRatingAndTopics).
    The summary is None when its own operation failed."""
    label = f"reviews of product {product_id}"
    operations = [
        _operation(queries.PRODUCT_REVIEWS, {"productID": product_id, "page": page, "limit": refs.REVIEWS_PER_PAGE,
                                             "sortBy": sort, "filterBy": filter_by}),
        _operation(queries.PRODUCT_RATING, {"productID": product_id}),
    ]

    def once():
        listed, rating = _send(operations, REVIEW_HEADERS, label)
        try:
            reviews = _field(data_of(listed, label), "productrevGetProductReviewList", label)
        except TokopediaNotFound:
            raise TokopediaNotFound(f"product {product_id} not found")
        try:
            summary = data_of(rating, label).get("productrevGetProductRatingAndTopics")
        except (TokopediaUpstreamError, TokopediaNotFound, TokopediaBadRequest):
            summary = None
        return reviews, summary
    return _retrying(once)


# ---- shops -----------------------------------------------------------------------------

def _shop_result(data, label):
    result = (data.get("shopInfoByID") or {}).get("result")
    if not isinstance(result, list) or not result or not isinstance(result[0], dict):
        raise TokopediaNotFound(f"{label} not found")
    return result


def _shop_variables(ref):
    if refs.is_shop_id(ref):
        return {"id": int(ref), "domain": ""}
    return {"id": 0, "domain": ref}


def _shop_extras(shop_id):
    return [_operation(queries.SHOP_STATISTIC, {"shopID": int(shop_id), "shopIDStr": str(shop_id)}),
            _operation(queries.SHOP_DESCRIPTION, {"input": {"shopIDsString": [str(shop_id)], "source": "shoppage"}})]


def _soft_data(answer, label):
    """The data of an optional operation; {} when it failed."""
    try:
        return data_of(answer, label)
    except (TokopediaUpstreamError, TokopediaNotFound, TokopediaBadRequest):
        return {}


def fetch_shop_core(ref):
    """The shop record of a domain or an id -> the shopInfoByID result row."""
    label = f"shop {ref}"
    return _shop_result(_one(queries.SHOP, _shop_variables(ref), SHOP_HEADERS, label), label)[0]


def fetch_shop_extras(shop_id):
    """A shop's rating block and description, in one POST -> (statistic data, description data)."""
    label = f"rating and description of shop {shop_id}"

    def once():
        statistic, description = _send(_shop_extras(shop_id), SHOP_HEADERS, label)
        return _soft_data(statistic, label), _soft_data(description, label)
    return _retrying(once)


def fetch_shop_full(shop_id):
    """Record, rating block and description of a shop id, in one POST ->
    (result row, statistic data, description data)."""
    label = f"shop {shop_id}"
    operations = [_operation(queries.SHOP, _shop_variables(str(shop_id)))] + _shop_extras(shop_id)

    def once():
        core, statistic, description = _send(operations, SHOP_HEADERS, label)
        row = _shop_result(data_of(core, label), label)[0]
        return row, _soft_data(statistic, label), _soft_data(description, label)
    return _retrying(once)


def fetch_shops(shop_ids):
    """The records of up to 100 shop ids -> the result rows the site knows."""
    label = f"{len(shop_ids)} shops"
    try:
        data = _one(queries.SHOPS_BY_ID, {"ids": [int(i) for i in shop_ids]}, SHOP_HEADERS, label)
    except TokopediaNotFound:
        return []
    result = (data.get("shopInfoByID") or {}).get("result")
    return [row for row in result if isinstance(row, dict)] if isinstance(result, list) else []


def fetch_shop_products(shop_id, page, sort, keyword=None):
    """One page of a shop's products -> GetShopProduct."""
    label = f"products of shop {shop_id}"
    variables = {"source": "shop", "sid": str(shop_id), "page": page, "perPage": refs.SHOP_PRODUCTS_PER_PAGE,
                 "etalaseId": "etalase", "sort": sort, "user_districtId": refs.DEFAULT_DISTRICT_ID,
                 "user_cityId": refs.DEFAULT_CITY_ID, "user_lat": "0", "user_long": "0",
                 "usecase": "ace_get_shop_product_v2"}
    if keyword:
        variables["keyword"] = keyword
    return _field(_one(queries.SHOP_PRODUCTS, variables, SHOP_HEADERS, label), "GetShopProduct", label)


def fetch_shop_reviews(shop_id, page, sort, filter_by):
    """One page of a shop's reviews -> productrevGetShopReviewReadingList."""
    label = f"reviews of shop {shop_id}"
    variables = {"shopID": str(shop_id), "limit": refs.REVIEWS_PER_PAGE, "page": page, "filterBy": filter_by,
                 "sortBy": sort}
    try:
        data = _one(queries.SHOP_REVIEWS, variables, REVIEW_HEADERS, label)
    except TokopediaNotFound:
        raise TokopediaNotFound(f"shop {shop_id} not found")
    return _field(data, "productrevGetShopReviewReadingList", label)


def shop_search_params(query, page, filters=None):
    """The `params` of a shop search, key for key what the shop search page sends."""
    params = {"q": query, "rows": refs.SHOP_SEARCH_PER_PAGE, "start": (page - 1) * refs.SHOP_SEARCH_PER_PAGE,
              "user_id": "0", **_location_params()}
    params.update(filters or {})
    return refs.encode_params(params)


def fetch_shop_search(params):
    """One page of the shop search -> aceSearchShop."""
    label = "shop search"
    return _field(_one(queries.SHOP_SEARCH, {"params": params}, SHOP_SEARCH_HEADERS, label), "aceSearchShop", label)
