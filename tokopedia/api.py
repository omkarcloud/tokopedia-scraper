"""The /tokopedia/* endpoint functions (route_glue's route_table calls them
with the schema's loaded kwargs).

Caching (cache.cached_call) sits here, on the upstream pieces as well as
on the answers, so endpoints that read the same thing pay one fetch:

  tokopedia.categories   the parsed category tree: categories/list answers
                         it, and every `category` param is resolved in it
                         (an id to its name and link, a link to its id)
  tokopedia.shop_core    one shop record: every `shop` param is resolved
                         through it (the id the product and review lists
                         need, the 404 of an unknown shop), and shops/details
                         of a domain starts from it
  tokopedia.product_id   the id behind a product link, for the review call

products/details is two upstream calls on one session: the product page's
first call, then its second with the payload the first returned. A second
call that fails costs the caller only the fields it holds (the shop block,
the wishlist count, the shipping estimate).
"""
import math
import threading

from cache import cached_call
from scraper_utils import fanout, memo
from tokopedia import cache_config as ttl
from tokopedia import parsers
from tokopedia import refs
from tokopedia.fetch import (TokopediaBadRequest, TokopediaNotFound, TokopediaUpstreamError, category_params,
                             fetch_categories, fetch_category_legacy, fetch_product, fetch_product_id,
                             fetch_product_reviews, fetch_product_second, fetch_products, fetch_search,
                             fetch_shop_core, fetch_shop_extras, fetch_shop_full, fetch_shop_products,
                             fetch_shop_reviews, fetch_shop_search, fetch_shops, legacy_category_params,
                             search_params, shop_search_params)

_SORT_NAMES = {token: name for name, token in refs.SORTS.items()}
_SHOP_SORT_NAMES = {token: name for name, token in refs.SHOP_SORTS.items()}
_REVIEW_SORT_NAMES = {token: name for name, token in refs.REVIEW_SORTS.items()}
_CONDITION_NAMES = {token: name for name, token in refs.CONDITIONS.items()}
_SHOP_TYPE_NAMES = {token: name for name, token in refs.SHOP_TYPES.items()}
_STOCK_NAMES = {token: name for name, token in refs.STOCK.items()}
_DELIVERY_NAMES = {token: name for name, token in refs.DELIVERY.items()}


# ---- categories ------------------------------------------------------------------------

def _fetch_category_tree():
    return parsers.parse_categories(fetch_categories())


def _category_tree():
    return cached_call("tokopedia.categories", {}, _fetch_category_tree, ttl.CATEGORIES_CACHE)


_index_store, _index_lock = {}, threading.Lock()


def _build_category_index():
    flat = parsers.flatten_categories(_category_tree())
    return {"by_id": {node["id"]: node for node in flat}, "by_path": {node["path"]: node for node in flat if node["path"]}}


def _category_index():
    """{by_id, by_path} over the tree, kept in this process for an hour."""
    return memo.expiring(_index_store, _index_lock, "index", ttl.CATEGORY_INDEX_SECONDS, _build_category_index)


def _find_category(ref):
    """The tree's entry for a resolved category ref (an id or a slug path); None when it has none."""
    index = _category_index()
    return index["by_id"].get(ref) if refs.is_category_id(ref) else index["by_path"].get(ref)


def categories_list():
    """The whole category tree."""
    tree = _category_tree()
    return {"categories_count": len(parsers.flatten_categories(tree)), "categories": tree}


# ---- product lists (shared) ------------------------------------------------------------

def _whole(amount):
    return int(round(amount))


def _filter_params(min_price, max_price, rating_4_up, condition, shop_type, location, cod, discounted, stock,
                   listed_within_days, delivery):
    """The keys the site's own filter links add to a list's `params`."""
    params = {}
    if min_price is not None:
        params["pmin"] = _whole(min_price)
    if max_price is not None:
        params["pmax"] = _whole(max_price)
    if rating_4_up:
        params["rt"] = refs.RATING_4_UP
    if condition:
        params["condition"] = condition
    if shop_type:
        params["shop_tier"] = shop_type
    if location:
        params["fcity"] = location
    if cod:
        params["cod"] = "true"
    if discounted:
        params["is_discount"] = "true"
    if stock:
        params["preorder"] = stock
    if listed_within_days:
        params["latest_product"] = listed_within_days
    if delivery:
        params["shipping_child"] = delivery
    return params


def _filters_asked(min_price, max_price, rating_4_up, condition, shop_type, location, cod, discounted, stock,
                   listed_within_days, delivery):
    """The filters of a list's answer, in the caller's own words."""
    return {
        "min_price": _whole(min_price) if min_price is not None else None,
        "max_price": _whole(max_price) if max_price is not None else None,
        "rating_4_up": bool(rating_4_up),
        "condition": _CONDITION_NAMES.get(condition),
        "shop_type": _SHOP_TYPE_NAMES.get(shop_type),
        "location_city_ids": location.split(",") if location else None,
        "cod": bool(cod),
        "discounted": bool(discounted),
        "stock": _STOCK_NAMES.get(stock),
        "listed_within_days": listed_within_days,
        "delivery": _DELIVERY_NAMES.get(delivery),
    }


def _list_pagination(parsed, page):
    """The pagination block of a product list. Past the end of a list the
    site says nothing about it (no products, a total of 0)."""
    total = parsed["total_count"]
    if parsed["products"] and total:
        pages = min(math.ceil(total / refs.SEARCH_PER_PAGE), refs.MAX_SEARCH_PAGE)
        return {"page": page, "items_per_page": refs.SEARCH_PER_PAGE, "total_pages": pages, "total_count": total}
    if page == 1:
        return {"page": page, "items_per_page": refs.SEARCH_PER_PAGE, "total_pages": 0, "total_count": 0}
    return {"page": page, "items_per_page": refs.SEARCH_PER_PAGE, "has_next": False, "total_pages": None,
            "total_count": None}


def _category_summary(node):
    return {"id": node["id"], "name": node["name"], "link": node["link"], "path": node["path"], "level": node["level"],
            "parents": node["parents"]}


# ---- products/search -------------------------------------------------------------------

def _products_search(query, category, page, sort, **filters):
    asked = _filters_asked(**filters)
    params = _filter_params(**filters)
    node = None
    if category:
        node = _find_category(category)
        if node is None:
            raise TokopediaBadRequest(f"Tokopedia has no category {category}; /tokopedia/categories/list has them all.")
        params["sc"] = node["id"]
    parsed = parsers.parse_search(fetch_search(search_params(query, page, sort, params)))
    return {
        "query": query,
        "sort": _SORT_NAMES.get(sort, sort),
        "category": _category_summary(node) if node else None,
        "filters": asked,
        "redirect_link": parsed["redirect_link"],
        "suggested_query": parsed["suggested_query"],
        "related_query": parsed["related_query"],
        "products": parsed["products"],
        "pagination": _list_pagination(parsed, page),
    }


def products_search(**data):
    """A keyword search, optionally inside one category."""
    return cached_call("tokopedia.search", data, _products_search, ttl.LISTING_CACHE)


# ---- categories/products ---------------------------------------------------------------

def _category_page(node, page, sort, params):
    """One page of a category: through the search call, and through the
    category page's own older call when that one fails."""
    try:
        return parsers.parse_search(fetch_search(category_params(node["id"], page, sort, params)))
    except TokopediaUpstreamError:
        legacy = legacy_category_params(node["id"], node["path"], page, sort, params)
        return parsers.parse_legacy_category(fetch_category_legacy(legacy))


def _categories_products(category, page, sort, **filters):
    node = _find_category(category)
    if node is None:
        raise TokopediaNotFound(f"category {category} not found")
    parsed = _category_page(node, page, sort, _filter_params(**filters))
    return {
        "category": _category_summary(node),
        "sort": _SORT_NAMES.get(sort, sort),
        "filters": _filters_asked(**filters),
        "products": parsed["products"],
        "pagination": _list_pagination(parsed, page),
    }


def categories_products(**data):
    """The products of one category."""
    return cached_call("tokopedia.category_products", data, _categories_products, ttl.LISTING_CACHE)


# ---- products/details ------------------------------------------------------------------

def _products_details(product):
    info = fetch_product(product)
    record = parsers.parse_product(info)
    if record is None:
        raise TokopediaNotFound(f"product {product} not found")
    payload = parsers.extra_payload(info)
    if payload:
        second = fanout.soft(lambda: fetch_product_second(record["id"], payload), None,
                             (TokopediaUpstreamError, TokopediaNotFound, TokopediaBadRequest))()
        if second:
            record = parsers.parse_product(info, second)
    return record


def products_details(product):
    """One product in full: everything its page shows."""
    return cached_call("tokopedia.product", {"product": product}, _products_details, ttl.PRODUCT_CACHE)


# ---- products/bulk ---------------------------------------------------------------------

def _products_bulk(products):
    product_refs = refs.split_refs(products)
    rows, missing = [], []
    for start in range(0, len(product_refs), refs.OPERATIONS_PER_POST):
        chunk = product_refs[start:start + refs.OPERATIONS_PER_POST]
        for ref, info in zip(chunk, fetch_products(chunk)):
            record = parsers.parse_product(info) if info else None
            if record is None:
                missing.append(ref if refs.is_product_id(ref) else refs.product_ref_link(ref))
            else:
                rows.append(record)
    if not rows:
        raise TokopediaNotFound("none of these products was found: " + ", ".join(missing[:5])
                                + (" ..." if len(missing) > 5 else ""))
    return {"products_count": len(rows), "products": rows, "not_found": missing}


def products_bulk(products):
    """Up to 30 products in one call: each one's main record, without the
    shop block, wishlist count and shipping estimate of products/details."""
    return cached_call("tokopedia.bulk", {"products": products}, _products_bulk, ttl.BULK_CACHE)


# ---- products/reviews ------------------------------------------------------------------

def _fetch_product_id(product):
    return fetch_product_id(product)


def _product_id(product):
    """The product id of a resolved product ref: itself, or the one behind a link."""
    if refs.is_product_id(product):
        return product
    return cached_call("tokopedia.product_id", {"product": product}, _fetch_product_id, ttl.PRODUCT_ID_CACHE)


def _reviews_pagination(parsed, page, max_page):
    total = parsed["total_count"]
    if parsed["reviews"] and total:
        pages = min(math.ceil(total / refs.REVIEWS_PER_PAGE), max_page)
        return {"page": page, "items_per_page": refs.REVIEWS_PER_PAGE, "total_pages": pages, "total_count": total}
    if page == 1:
        return {"page": page, "items_per_page": refs.REVIEWS_PER_PAGE, "total_pages": 0, "total_count": 0}
    return {"page": page, "items_per_page": refs.REVIEWS_PER_PAGE, "has_next": False, "total_pages": None,
            "total_count": None}


def _products_reviews(product, page, sort, stars, with_media, topic):
    raw, raw_summary = fetch_product_reviews(product, page, sort, refs.review_filter(stars, with_media, topic))
    parsed = parsers.parse_product_reviews(raw)
    summary = parsers.parse_rating_summary(raw_summary) or {"rating": None, "topics": []}
    if topic and summary["topics"] and topic not in [item["key"] for item in summary["topics"]]:
        known = ", ".join(item["key"] for item in summary["topics"])
        raise TokopediaBadRequest(f"This product's reviews have no topic '{topic}'. Its topics: {known}.")
    return {
        "product_id": product,
        "reviewed_product_id": parsed["product_id"],
        "sort": _REVIEW_SORT_NAMES.get(sort, sort),
        "stars": [int(star) for star in stars] if stars else None,
        "with_media": bool(with_media),
        "topic": topic,
        "rating": summary["rating"],
        "topics": summary["topics"],
        "shop": parsed["shop"],
        "reviews": parsed["reviews"],
        "pagination": _reviews_pagination(parsed, page, refs.MAX_PRODUCT_REVIEWS_PAGE),
    }


def products_reviews(product, page=1, sort=None, stars=None, with_media=None, topic=None):
    """One page of a product's reviews, with its rating summary."""
    data = {"product": _product_id(product), "page": page, "sort": sort or refs.REVIEW_SORTS["helpful"],
            "stars": stars, "with_media": with_media, "topic": topic}
    return cached_call("tokopedia.reviews", data, _products_reviews, ttl.REVIEWS_CACHE)


# ---- shops -----------------------------------------------------------------------------

def _fetch_shop_core(shop):
    record = parsers.parse_shop(fetch_shop_core(shop))
    if record is None:
        raise TokopediaNotFound(f"shop {shop} not found")
    return record


def _shop_core(shop):
    """The shop record behind a resolved shop ref (a domain or an id)."""
    return cached_call("tokopedia.shop_core", {"shop": shop}, _fetch_shop_core, ttl.SHOP_CORE_CACHE)


def _shop_summary(record):
    return {"id": record["id"], "domain": record["domain"], "name": record["name"], "link": record["link"]}


def _with_extras(record, statistic, description):
    record = dict(record)
    record.update(parsers.parse_shop_statistic(statistic))
    record["description"] = parsers.parse_shop_description(description, record["id"])
    return record


def _shops_details(shop):
    if refs.is_shop_id(shop):
        row, statistic, description = fetch_shop_full(shop)
        record = parsers.parse_shop(row)
        if record is None:
            raise TokopediaNotFound(f"shop {shop} not found")
        return _with_extras(record, statistic, description)
    record = _shop_core(shop)
    statistic, description = fanout.soft(lambda: fetch_shop_extras(record["id"]), ({}, {}),
                                         (TokopediaUpstreamError,))()
    return _with_extras(record, statistic, description)


def shops_details(shop):
    """One shop: its record, its rating with the star breakdown and its description."""
    return cached_call("tokopedia.shop", {"shop": shop}, _shops_details, ttl.SHOP_CACHE)


def _shops_bulk(shops):
    ids = refs.split_refs(shops)
    records = [record for record in (parsers.parse_shop(row) for row in fetch_shops(ids)) if record]
    if not records:
        raise TokopediaNotFound("none of these shops was found: " + ", ".join(ids[:5]) + (" ..." if len(ids) > 5 else ""))
    found = {record["id"] for record in records}
    records.sort(key=lambda record: ids.index(record["id"]) if record["id"] in ids else len(ids))
    return {"shops_count": len(records), "shops": records, "not_found": [i for i in ids if i not in found]}


def shops_bulk(shops):
    """Up to 100 shops by id: each one's record, without the rating block
    and the description of shops/details."""
    return cached_call("tokopedia.shops_bulk", {"shops": shops}, _shops_bulk, ttl.SHOP_CACHE)


def _shops_products(shop_id, page, sort, query):
    parsed = parsers.parse_shop_products(fetch_shop_products(shop_id, page, sort, query))
    return {"products": parsed["products"], "has_next": parsed["has_next"]}


def shops_products(shop, page=1, sort=None, query=None):
    """One page of a shop's products."""
    record = _shop_core(shop)
    sort = sort or refs.SHOP_SORTS["default"]
    data = {"shop_id": record["id"], "page": page, "sort": sort, "query": query}
    listed = cached_call("tokopedia.shop_products", data, _shops_products, ttl.SHOP_PRODUCTS_CACHE)
    return {
        "shop": _shop_summary(record),
        "sort": _SHOP_SORT_NAMES.get(sort, sort),
        "query": query,
        "products": listed["products"],
        # The site says whether a next page exists, never how many products the list has.
        "pagination": {"page": page, "items_per_page": refs.SHOP_PRODUCTS_PER_PAGE,
                       "has_next": listed["has_next"] and page < refs.MAX_SHOP_PRODUCTS_PAGE,
                       "total_pages": None, "total_count": None},
    }


def _shops_reviews(shop_id, page, sort, stars, with_media):
    parsed = parsers.parse_shop_reviews(fetch_shop_reviews(shop_id, page, sort, refs.review_filter(stars, with_media)))
    return {"reviews": parsed["reviews"], "total_count": parsed["total_count"]}


def shops_reviews(shop, page=1, sort=None, stars=None, with_media=None):
    """One page of the reviews of a shop's products."""
    record = _shop_core(shop)
    sort = sort or refs.REVIEW_SORTS["newest"]
    data = {"shop_id": record["id"], "page": page, "sort": sort, "stars": stars, "with_media": with_media}
    listed = cached_call("tokopedia.shop_reviews", data, _shops_reviews, ttl.REVIEWS_CACHE)
    return {
        "shop": _shop_summary(record),
        "sort": _REVIEW_SORT_NAMES.get(sort, sort),
        "stars": [int(star) for star in stars] if stars else None,
        "with_media": bool(with_media),
        "reviews": listed["reviews"],
        "pagination": _reviews_pagination(listed, page, refs.MAX_SHOP_REVIEWS_PAGE),
    }


def _shops_search(query, page, shop_type, location):
    params = {}
    if shop_type:
        params["shop_tier"] = shop_type
    if location:
        params["fcity"] = location
    parsed = parsers.parse_shop_search(fetch_shop_search(shop_search_params(query, page, params)))
    total = parsed["total_count"]
    if total:
        pages = min(math.ceil(total / refs.SHOP_SEARCH_PER_PAGE), refs.MAX_SHOP_SEARCH_PAGE)
        pagination = {"page": page, "items_per_page": refs.SHOP_SEARCH_PER_PAGE, "total_pages": pages,
                      "total_count": total}
    else:
        pagination = {"page": page, "items_per_page": refs.SHOP_SEARCH_PER_PAGE, "total_pages": 0, "total_count": 0}
    return {
        "query": query,
        "shop_type": _SHOP_TYPE_NAMES.get(shop_type),
        "location_city_ids": location.split(",") if location else None,
        "suggested_query": parsed["suggested_query"],
        "shops": parsed["shops"],
        "pagination": pagination,
    }


def shops_search(**data):
    """A keyword search for shops."""
    return cached_call("tokopedia.shop_search", data, _shops_search, ttl.SHOP_SEARCH_CACHE)
