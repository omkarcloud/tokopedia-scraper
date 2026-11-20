"""Offline tests for the transport (tokopedia/fetch.py: what one POST
carries, how an answer is read) and the endpoint logic (tokopedia/api.py),
with the network and the cache replaced by fakes whose answers are the
fixtures.

    python -m pytest tokopedia/test_api.py -q
"""
import gzip
import json
import os
import sys
from urllib.parse import parse_qs

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError  # noqa: E402
from tokopedia import api, fetch, queries, refs, schemas  # noqa: E402
from schema_fields import load_query  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
DAVEED = "100773001007"
KEY = "tomkins-daveed-hijau-hitam-sepatu-casual-anak-remaja-1731945700296001445"


def answers(name):
    path = os.path.join(FIXTURES, name)
    if not os.path.exists(path):
        path += ".gz"
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as f:
        return json.load(f)


class Answer:
    def __init__(self, body, status=200):
        self.status_code = status
        self.text = body if isinstance(body, str) else json.dumps(body)

    def json(self):
        return json.loads(self.text)


class Cookies:
    def clear(self):
        pass


class Wire:
    """A session whose answers are queued; it records what was sent."""

    def __init__(self, monkeypatch, *queued):
        self.queued = [item if isinstance(item, (Answer, Exception)) else Answer(item) for item in queued]
        self.sent = []
        self.dropped = 0
        self.cookies = Cookies()
        monkeypatch.setattr(fetch, "_session", lambda: self)
        monkeypatch.setattr(fetch, "_drop_session", self._drop)
        monkeypatch.setattr(fetch.retry.time, "sleep", lambda seconds: None)

    def _drop(self):
        self.dropped += 1

    def post(self, url, data=None, headers=None, timeout=None):
        self.sent.append({"url": url, "operations": json.loads(data), "headers": headers})
        answer = self.queued.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def operation(self, index=0, position=0):
        return self.sent[index]["operations"][position]

    def params(self, index=0):
        """The `params` text of a list call, as {key: value}."""
        text = self.operation(index)["variables"]["params"]
        return {key: values[0] for key, values in parse_qs(text.lstrip("&"), keep_blank_values=True).items()}


@pytest.fixture
def memory_cache(monkeypatch):
    """cache.cached_call's contract in memory: keyed on (namespace, params)."""
    rows = {}

    def cached_call(namespace, data, fn, ttl, cache=True, refresh=False):
        key = (namespace, json.dumps(data, sort_keys=True))
        if key not in rows:
            rows[key] = fn(**data)
        return rows[key]
    monkeypatch.setattr(api, "cached_call", cached_call)
    monkeypatch.setattr(api, "_index_store", {})
    return rows


def call(schema, impl, query):
    data, error = load_query(schema, query)
    assert error is None, error
    return impl(**data)


# ---- the transport ---------------------------------------------------------------------

def test_error_classes_follow_the_shared_taxonomy():
    assert issubclass(fetch.TokopediaBlocked, Blocked) and issubclass(fetch.TokopediaBlocked, UpstreamError)
    assert issubclass(fetch.TokopediaUpstreamError, UpstreamError)
    assert issubclass(fetch.TokopediaBadRequest, BadRequest) and issubclass(fetch.TokopediaNotFound, NotFound)
    assert not issubclass(fetch.TokopediaNotFound, UpstreamError)


def test_a_call_is_one_post_of_a_list_to_the_operations_link(monkeypatch):
    wire = Wire(monkeypatch, answers("search_no_result.json"))
    fetch.fetch_search("q=x")
    sent = wire.sent[0]
    assert sent["url"] == "https://gql.tokopedia.com/graphql/SearchProductV5Query"
    assert sent["operations"] == [{"operationName": "SearchProductV5Query", "variables": {"params": "q=x"},
                                   "query": queries.SEARCH_PRODUCTS[1]}]
    headers = sent["headers"]
    assert headers["x-source"] == "tokopedia-lite" and headers["x-tkpd-lite-service"] == "zeus"
    assert headers["origin"] == "https://www.tokopedia.com" and headers["x-device"] == "desktop-0.0"
    for left_to_the_session in ("user-agent", "accept-language", "accept-encoding", "cookie"):
        assert left_to_the_session not in headers


def test_the_product_calls_carry_the_header_the_site_requires(monkeypatch):
    wire = Wire(monkeypatch, answers("product_100773001007.json"), answers("product_100773001007_second.json"))
    info = fetch.fetch_product(DAVEED)
    fetch.fetch_product_second(DAVEED, info["extraPayload"])
    for sent in wire.sent:
        assert sent["headers"]["x-tkpd-akamai"] == "pdpMainInfo" and sent["headers"]["x-date"].endswith("+0000")
    assert "x-tkpd-akamai" not in fetch.SEARCH_HEADERS and "x-tkpd-akamai" not in fetch.SHOP_HEADERS


def test_a_product_is_asked_by_id_or_by_shop_domain_and_key(monkeypatch):
    wire = Wire(monkeypatch, answers("product_100773001007.json"), answers("product_100773001007.json"))
    fetch.fetch_product(DAVEED)
    fetch.fetch_product(f"tomkinsofficial/{KEY}")
    by_id, by_key = wire.operation(0)["variables"], wire.operation(1)["variables"]
    assert (by_id["productID"], by_id["shopDomain"], by_id["productKey"]) == (DAVEED, "", "")
    assert (by_key["productID"], by_key["shopDomain"], by_key["productKey"]) == ("", "tomkinsofficial", KEY)
    assert by_id["source"] == "P1" and by_id["userLocation"]["cityID"] == "176" and by_id["userLocation"]["districtID"] == "2274"
    assert "$productID:String" in wire.operation(0)["query"]


def test_the_second_product_call_sends_back_the_payload_of_the_first(monkeypatch):
    wire = Wire(monkeypatch, answers("product_100773001007_second.json"))
    second = fetch.fetch_product_second(DAVEED, "PAYLOAD")
    assert second["wishlistCount"] == "5"
    variables = wire.operation()["variables"]
    assert variables["extraPayload"] == "PAYLOAD" and variables["source"] == "P2" and variables["productID"] == DAVEED


def test_not_found_is_final(monkeypatch):
    wire = Wire(monkeypatch, answers("product_not_found.json"))
    with pytest.raises(fetch.TokopediaNotFound, match="product 1 not found"):
        fetch.fetch_product("1")
    assert len(wire.sent) == 1 and wire.dropped == 0


def test_a_bad_argument_is_final(monkeypatch):
    wire = Wire(monkeypatch, [answers("error_reviews_invalid_argument.json")[0], answers("review_summary_none.json")[0]])
    with pytest.raises(fetch.TokopediaBadRequest):
        fetch.fetch_product_reviews(DAVEED, 1, "create_time desc", "")
    assert len(wire.sent) == 1


@pytest.mark.parametrize("status, kind", [(403, fetch.TokopediaBlocked), (429, fetch.TokopediaBlocked),
                                          (502, fetch.TokopediaUpstreamError)])
def test_a_refusal_is_retried_on_a_fresh_session(monkeypatch, status, kind):
    wire = Wire(monkeypatch, Answer("no", status), Answer("no", status), answers("search_no_result.json"))
    assert fetch.fetch_search("q=x")["header"]["totalData"] == 0
    assert len(wire.sent) == 3 and wire.dropped == 2
    wire = Wire(monkeypatch, *[Answer("no", status)] * config.MAX_RETRIES)
    with pytest.raises(kind):
        fetch.fetch_search("q=x")
    assert len(wire.sent) == config.MAX_RETRIES


def test_a_page_where_json_was_due_is_a_block(monkeypatch):
    Wire(monkeypatch, *[Answer("<html>Access Denied</html>")] * config.MAX_RETRIES)
    with pytest.raises(fetch.TokopediaBlocked):
        fetch.fetch_search("q=x")


def test_a_failed_request_and_the_sites_own_error_are_retried(monkeypatch):
    wire = Wire(monkeypatch, ConnectionError("reset"), answers("error_reviews_too_deep.json"),
                answers("search_no_result.json"))
    assert fetch.fetch_search("q=x")["data"]["products"] == []
    assert len(wire.sent) == 3 and wire.dropped == 2


def test_seven_operations_never_leave(monkeypatch):
    wire = Wire(monkeypatch)
    with pytest.raises(ValueError):
        fetch.fetch_products([str(n) for n in range(1000, 1007)])
    assert wire.sent == []
    refused = Wire(monkeypatch, *[Answer(answers("error_seven_operations.json"), 406)] * config.MAX_RETRIES)
    with pytest.raises(fetch.TokopediaUpstreamError, match="Request not allowed"):
        fetch.fetch_search("q=x")
    assert len(refused.sent) == config.MAX_RETRIES


def test_search_params_are_the_search_pages_own(monkeypatch):
    wire = Wire(monkeypatch, answers("search_no_result.json"))
    fetch.fetch_search(fetch.search_params("sepatu lari", 3, "9", {"fcity": "165,252", "pmin": 100000}))
    params = wire.params()
    assert params["q"] == "sepatu lari" and params["page"] == "3" and params["start"] == "120" and params["rows"] == "60"
    assert params["ob"] == "9" and params["fcity"] == "165,252" and params["pmin"] == "100000"
    assert params["source"] == "search" and params["st"] == "product" and params["device"] == "desktop"
    assert params["user_cityId"] == "176" and params["user_districtId"] == "2274" and len(params["unique_id"]) == 32
    captured = ("device enter_method l_name ob page q related rows safe_search sc scheme shipping show_adult source st "
                "start topads_bucket unique_id user_addressId user_cityId user_districtId user_id user_lat user_long "
                "user_postCode user_warehouseId variants warehouses").split()
    assert sorted(set(params) - {"fcity", "pmin"}) == sorted(captured)


def test_category_params(monkeypatch):
    assert fetch.category_params("1800", 2, "3", {"shop_tier": "2"}) == \
        "device=desktop&ob=3&page=2&q=&rows=60&sc=1800&shop_tier=2&source=directory&st=product&start=60"
    legacy = fetch.legacy_category_params("1800", "fashion-pria/sepatu-pria", 2, "23")
    assert legacy == ("&ob=23&identifier=fashion-pria_sepatu-pria&sc=1800&user_id=0&rows=60&start=61&source=directory"
                      "&device=desktop&page=2&related=true&st=product&safe_search=false")


# ---- products/search -------------------------------------------------------------------

def test_products_search(monkeypatch, memory_cache):
    wire = Wire(monkeypatch, answers("search_sepatu.json"))
    out = call(schemas.ProductsSearchSchema, api.products_search, {"query": "sepatu"})
    assert list(out) == ["query", "sort", "category", "filters", "redirect_link", "suggested_query", "related_query",
                         "products", "pagination"]
    assert out["query"] == "sepatu" and out["sort"] == "relevance" and out["category"] is None
    assert len(out["products"]) == 60
    assert out["pagination"] == {"page": 1, "items_per_page": 60, "total_pages": 100, "total_count": 2418263}
    assert out["filters"]["min_price"] is None and out["filters"]["cod"] is False
    assert "sc" in wire.params() and wire.params()["sc"] == ""


def test_products_search_sends_every_filter_as_the_sites_token(monkeypatch, memory_cache):
    wire = Wire(monkeypatch, answers("search_no_result.json"))
    out = call(schemas.ProductsSearchSchema, api.products_search, {
        "query": "sepatu", "sort": "price_low", "min_price": "100000", "max_price": "200000.4", "rating_4_up": "true",
        "condition": "used", "shop_type": "power_shop", "location": "Bandung", "cod": "true", "discounted": "true",
        "stock": "ready", "listed_within_days": "7", "delivery": "instant"})
    params = wire.params()
    assert {key: params[key] for key in ("ob", "pmin", "pmax", "rt", "condition", "shop_tier", "fcity", "cod",
                                         "is_discount", "preorder", "latest_product", "shipping_child")} == {
        "ob": "3", "pmin": "100000", "pmax": "200000", "rt": "4,5", "condition": "2", "shop_tier": "3", "fcity": "165",
        "cod": "true", "is_discount": "true", "preorder": "false", "latest_product": "7",
        "shipping_child": "nearby,7408193449930786576"}
    assert out["filters"] == {"min_price": 100000, "max_price": 200000, "rating_4_up": True, "condition": "used",
                              "shop_type": "power_shop", "location_city_ids": ["165"], "cod": True, "discounted": True,
                              "stock": "ready", "listed_within_days": 7, "delivery": "instant"}
    assert out["sort"] == "price_low"
    assert out["pagination"] == {"page": 1, "items_per_page": 60, "total_pages": 0, "total_count": 0}


def test_false_switches_send_nothing(monkeypatch, memory_cache):
    wire = Wire(monkeypatch, answers("search_no_result.json"))
    call(schemas.ProductsSearchSchema, api.products_search, {"query": "x", "cod": "false", "discounted": "0",
                                                           "rating_4_up": "no"})
    assert not {"cod", "is_discount", "rt"} & set(wire.params())


def test_a_page_past_the_end_is_an_empty_page(monkeypatch, memory_cache):
    Wire(monkeypatch, answers("search_past_end.json"))
    out = call(schemas.ProductsSearchSchema, api.products_search, {"query": "sepatu", "page": "100"})
    assert out["products"] == []
    assert out["pagination"] == {"page": 100, "items_per_page": 60, "has_next": False, "total_pages": None,
                                 "total_count": None}


def test_a_search_the_site_redirects_says_where(monkeypatch, memory_cache):
    Wire(monkeypatch, answers("search_redirect_pulsa.json"))
    out = call(schemas.ProductsSearchSchema, api.products_search, {"query": "pulsa"})
    assert out["products"] == [] and out["redirect_link"] == "https://tokopedia.com/pulsa?dg_value=1"


def test_search_inside_a_category(monkeypatch, memory_cache):
    wire = Wire(monkeypatch, answers("categories.json"), answers("search_no_result.json"))
    out = call(schemas.ProductsSearchSchema, api.products_search, {
        "query": "sepatu", "category": "https://www.tokopedia.com/p/fashion-pria/sepatu-pria"})
    assert wire.params(1)["sc"] == "1800" and wire.params(1)["q"] == "sepatu"
    assert out["category"]["id"] == "1800" and out["category"]["name"] == "Sepatu Pria"
    assert [parent["id"] for parent in out["category"]["parents"]] == ["1759"]


def test_search_inside_a_category_the_site_does_not_have(monkeypatch, memory_cache):
    wire = Wire(monkeypatch, answers("categories.json"))
    with pytest.raises(fetch.TokopediaBadRequest, match="no category 99999999"):
        call(schemas.ProductsSearchSchema, api.products_search, {"query": "sepatu", "category": "99999999"})
    assert len(wire.sent) == 1                    # the tree alone: no list was asked


def test_the_same_search_is_fetched_once(monkeypatch, memory_cache):
    wire = Wire(monkeypatch, answers("search_sepatu.json"))
    for _ in range(2):
        call(schemas.ProductsSearchSchema, api.products_search, {"query": "sepatu"})
    assert len(wire.sent) == 1


# ---- categories ------------------------------------------------------------------------

def test_categories_list(monkeypatch, memory_cache):
    wire = Wire(monkeypatch, answers("categories.json"))
    out = api.categories_list()
    assert out["categories_count"] == 3312 and len(out["categories"]) == 29
    assert wire.sent[0]["url"].endswith("/graphql/categoryAllList") and wire.operation()["variables"] == {}


@pytest.mark.parametrize("category", ["1800", "https://www.tokopedia.com/p/fashion-pria/sepatu-pria",
                                      "fashion-pria/sepatu-pria"])
def test_categories_products_by_id_or_link(monkeypatch, memory_cache, category):
    wire = Wire(monkeypatch, answers("categories.json"), answers("category_sepatu_pria.json"))
    out = call(schemas.CategoriesProductsSchema, api.categories_products, {"category": category, "sort": "newest"})
    assert list(out) == ["category", "sort", "filters", "products", "pagination"]
    assert out["category"] == {"id": "1800", "name": "Sepatu Pria", "link": "https://www.tokopedia.com/p/fashion-pria/sepatu-pria",
                               "path": "fashion-pria/sepatu-pria", "level": 2,
                               "parents": [{"id": "1759", "name": "Fashion Pria",
                                            "link": "https://www.tokopedia.com/p/fashion-pria"}]}
    params = wire.params(1)
    assert params["sc"] == "1800" and params["q"] == "" and params["source"] == "directory" and params["ob"] == "9"
    assert params["rows"] == "60" and params["start"] == "0"
    assert out["pagination"] == {"page": 1, "items_per_page": 60, "total_pages": 100, "total_count": 1428178}


def test_categories_products_of_an_unknown_category(monkeypatch, memory_cache):
    Wire(monkeypatch, answers("categories.json"))
    for category in ("99999999", "no-such/category"):
        with pytest.raises(fetch.TokopediaNotFound, match=f"category {category} not found"):
            call(schemas.CategoriesProductsSchema, api.categories_products, {"category": category})


def test_categories_products_falls_back_to_the_category_pages_own_call(monkeypatch, memory_cache):
    refused = [Answer("no", 502)] * config.MAX_RETRIES
    wire = Wire(monkeypatch, answers("categories.json"), *refused, answers("category_sepatu_pria_legacy.json"))
    out = call(schemas.CategoriesProductsSchema, api.categories_products, {"category": "1800", "page": "2"})
    last = wire.sent[-1]
    assert last["url"].endswith("/graphql/SearchProductQuery")
    assert wire.params(len(wire.sent) - 1)["start"] == "61" and wire.params(len(wire.sent) - 1)["identifier"] == "fashion-pria_sepatu-pria"
    assert len(out["products"]) == 60 and out["pagination"]["total_count"] == 1428202


# ---- products/details ------------------------------------------------------------------

def test_products_details_makes_the_two_calls(monkeypatch, memory_cache):
    wire = Wire(monkeypatch, answers("product_100773001007.json"), answers("product_100773001007_second.json"))
    out = api.products_details(DAVEED)
    assert [sent["url"].rsplit("/", 1)[1] for sent in wire.sent] == ["PDPMainInfo", "PDPSecondaryInfo"]
    assert wire.operation(1)["variables"]["extraPayload"].startswith("3gAy")
    assert list(out)[:6] == ["id", "parent_id", "name", "link", "slug", "brand"]
    assert out["wishlist_count"] == 5 and out["shop"]["location"] == "Kota Bandung" and out["shipping"]["cheapest_amount"] == 10000


def test_products_details_survives_a_second_call_that_fails(monkeypatch, memory_cache):
    refused = [answers("product_second_without_payload.json")] * config.MAX_RETRIES
    Wire(monkeypatch, answers("product_100773001007.json"), *refused)
    out = api.products_details(DAVEED)
    assert out["id"] == DAVEED and out["price"]["amount"] == 309000
    assert out["wishlist_count"] is None and out["shipping"] is None and out["shop"]["name"] == "TOMKINS"


@pytest.mark.parametrize("fixture", ["product_not_found.json", "product_id_not_found.json"])
def test_products_details_of_an_unknown_product(monkeypatch, memory_cache, fixture):
    wire = Wire(monkeypatch, answers(fixture))
    with pytest.raises(fetch.TokopediaNotFound, match="not found"):
        api.products_details("999999999999999")
    assert len(wire.sent) == 1


# ---- products/bulk ---------------------------------------------------------------------

def test_products_bulk_sends_six_a_post(monkeypatch, memory_cache):
    six = answers("products_six.json")
    ids = [answer["data"]["pdpMainInfo"]["data"]["basicInfo"]["id"] for answer in six]
    wire = Wire(monkeypatch, six, six[:2])
    out = api.products_bulk(",".join(ids + ["1", "2"]))          # the fake answers ids[0:2] for the last two
    assert [len(sent["operations"]) for sent in wire.sent] == [6, 2]
    assert all(operation["operationName"] == "PDPMainInfo" for sent in wire.sent for operation in sent["operations"])
    assert out["products_count"] == 8 and out["not_found"] == []
    assert [row["id"] for row in out["products"]][:6] == ids


def test_products_bulk_names_what_was_not_found(monkeypatch, memory_cache):
    found, missing = answers("product_100773001007.json")[0], answers("product_id_not_found.json")[0]
    Wire(monkeypatch, [found, missing, missing])
    out = api.products_bulk(f"{DAVEED},999,shop/some-product")
    assert out["products_count"] == 1 and out["products"][0]["id"] == DAVEED
    assert out["not_found"] == ["999", "https://www.tokopedia.com/shop/some-product"]
    assert out["products"][0]["wishlist_count"] is None          # the bulk record is the first call alone


def test_products_bulk_of_nothing_known(monkeypatch, memory_cache):
    missing = answers("product_id_not_found.json")[0]
    Wire(monkeypatch, [missing, missing])
    with pytest.raises(fetch.TokopediaNotFound, match="none of these products was found: 998, 999"):
        api.products_bulk("998,999")


# ---- products/reviews ------------------------------------------------------------------

def _review_answers(reviews, summary):
    return [answers(reviews)[0], answers(summary)[0]]


def test_products_reviews(monkeypatch, memory_cache):
    wire = Wire(monkeypatch, _review_answers("reviews_100070724287.json", "review_summary_100070724287.json"))
    out = call(schemas.ProductsReviewsSchema, api.products_reviews, {"product": "100070724287"})
    assert [operation["operationName"] for operation in wire.sent[0]["operations"]] == ["productReviewList",
                                                                                       "productRatingAndTopics"]
    assert wire.operation()["variables"] == {"productID": "100070724287", "page": 1, "limit": 50,
                                              "sortBy": "informative_score desc", "filterBy": ""}
    assert list(out) == ["product_id", "reviewed_product_id", "sort", "stars", "with_media", "topic", "rating", "topics",
                         "shop", "reviews", "pagination"]
    assert out["product_id"] == "100070724287" and out["reviewed_product_id"] == "100070724279"
    assert out["sort"] == "helpful" and out["rating"]["score"] == 4.9 and len(out["topics"]) == 6
    assert out["pagination"] == {"page": 1, "items_per_page": 50, "total_pages": 199, "total_count": 10000}


def test_products_reviews_by_link_looks_the_id_up_once(monkeypatch, memory_cache):
    wire = Wire(monkeypatch, answers("product_id_lookup.json"),
                _review_answers("reviews_100773001007_last_page.json", "review_summary_none.json"),
                _review_answers("reviews_past_end.json", "review_summary_none.json"))
    link = f"https://www.tokopedia.com/tomkinsofficial/{KEY}"
    out = call(schemas.ProductsReviewsSchema, api.products_reviews, {"product": link, "stars": "5,4", "with_media": "true",
                                                                     "sort": "newest"})
    assert wire.sent[0]["url"].endswith("/graphql/getMiniProductInfo")
    assert wire.operation(0)["variables"]["productURL"] == link
    variables = wire.operation(1)["variables"]
    assert variables["productID"] == DAVEED and variables["filterBy"] == "media=image,video;rating=5,4"
    assert variables["sortBy"] == "create_time desc"
    assert out["stars"] == [5, 4] and out["with_media"] is True and out["sort"] == "newest"
    assert out["pagination"] == {"page": 1, "items_per_page": 50, "total_pages": 1, "total_count": 7}
    past = call(schemas.ProductsReviewsSchema, api.products_reviews, {"product": link, "page": "2"})
    assert len(wire.sent) == 3                       # the id was not looked up again
    assert past["reviews"] == [] and past["pagination"] == {"page": 2, "items_per_page": 50, "has_next": False,
                                                           "total_pages": None, "total_count": None}


def test_products_reviews_of_a_product_without_reviews(monkeypatch, memory_cache):
    Wire(monkeypatch, _review_answers("reviews_none.json", "review_summary_none.json"))
    out = call(schemas.ProductsReviewsSchema, api.products_reviews, {"product": "104467229787"})
    assert out["reviews"] == [] and out["rating"]["ratings_count"] == 0 and out["rating"]["score"] is None
    assert out["pagination"] == {"page": 1, "items_per_page": 50, "total_pages": 0, "total_count": 0}


def test_products_reviews_of_an_unknown_product(monkeypatch, memory_cache):
    Wire(monkeypatch, _review_answers("reviews_product_not_found.json", "review_summary_none.json"))
    with pytest.raises(fetch.TokopediaNotFound, match="product 999999999999999 not found"):
        call(schemas.ProductsReviewsSchema, api.products_reviews, {"product": "999999999999999"})


def test_products_reviews_refuses_a_topic_the_product_does_not_have(monkeypatch, memory_cache):
    Wire(monkeypatch, _review_answers("reviews_100070724287.json", "review_summary_100070724287.json"))
    with pytest.raises(fetch.TokopediaBadRequest, match="no topic 'banana'. Its topics: kualitas, pelayanan"):
        call(schemas.ProductsReviewsSchema, api.products_reviews, {"product": "100070724287", "topic": "banana"})


def test_products_reviews_without_the_summary(monkeypatch, memory_cache):
    Wire(monkeypatch, [answers("reviews_100070724287.json")[0], answers("error_reviews_too_deep.json")[0]])
    out = call(schemas.ProductsReviewsSchema, api.products_reviews, {"product": "100070724287", "topic": "kualitas"})
    assert out["rating"] is None and out["topics"] == [] and len(out["reviews"]) == 10


# ---- shops -----------------------------------------------------------------------------

def test_shops_details_by_id_is_one_post_of_three_operations(monkeypatch, memory_cache):
    wire = Wire(monkeypatch, answers("shop_6638357_three_operations.json"))
    out = api.shops_details("6638357")
    assert len(wire.sent) == 1
    assert [operation["operationName"] for operation in wire.sent[0]["operations"]] == [
        "ShopInfoCore", "ShopStatisticQuery", "GetShopDescription"]
    assert wire.operation(0, 0)["variables"] == {"id": 6638357, "domain": ""}
    assert wire.operation(0, 1)["variables"] == {"shopID": 6638357, "shopIDStr": "6638357"}
    assert wire.sent[0]["headers"]["x-device"] == "default_v3"
    assert list(out)[:5] == ["id", "domain", "name", "link", "description"]
    assert out["rating"]["score"] == 4.9 and out["description"].startswith("Tomkins Official Shop")
    assert out["followers_count"] == 27749


def test_shops_details_by_domain_reads_the_id_first(monkeypatch, memory_cache):
    three = answers("shop_6638357_three_operations.json")
    wire = Wire(monkeypatch, answers("shop_tomkinsofficial.json"), three[1:])
    out = api.shops_details("tomkinsofficial")
    assert wire.operation(0)["variables"] == {"id": 0, "domain": "tomkinsofficial"}
    assert [operation["operationName"] for operation in wire.sent[1]["operations"]] == ["ShopStatisticQuery",
                                                                                       "GetShopDescription"]
    assert wire.operation(1, 1)["variables"] == {"input": {"shopIDsString": ["6638357"], "source": "shoppage"}}
    assert out["id"] == "6638357" and out["rating"]["ratings_count"] == 76579 and out["description"]


def test_shops_details_keeps_the_record_when_the_rating_call_fails(monkeypatch, memory_cache):
    Wire(monkeypatch, answers("shop_tomkinsofficial.json"), *[Answer("no", 502)] * config.MAX_RETRIES)
    out = api.shops_details("tomkinsofficial")
    assert out["name"] == "TOMKINS" and out["rating"] is None and out["description"] is None


@pytest.mark.parametrize("shop", ["zzzz-no-such-shop-zzzz", "999999999999"])
def test_an_unknown_shop_is_not_found_on_every_shop_endpoint(monkeypatch, memory_cache, shop):
    for impl in (api.shops_details, api.shops_products, api.shops_reviews):
        wire = Wire(monkeypatch, answers("shop_not_found.json"))
        if impl is api.shops_details and shop.isdigit():          # an id: the three operations in one POST
            wire = Wire(monkeypatch, answers("shop_id_not_found_three_operations.json"))
        with pytest.raises(fetch.TokopediaNotFound, match=f"shop {shop} not found"):
            impl(shop)
        assert len(wire.sent) == 1 and wire.dropped == 0


def test_shops_bulk(monkeypatch, memory_cache):
    wire = Wire(monkeypatch, answers("shops_twenty.json"))
    rows = answers("shops_twenty.json")[0]["data"]["shopInfoByID"]["result"]
    ids = [row["shopCore"]["shopID"] for row in rows]
    asked = list(reversed(ids)) + ["999999999999"]
    out = api.shops_bulk(",".join(asked))
    assert wire.operation()["variables"] == {"ids": [int(i) for i in asked]}
    assert "$ids:[Int!]!" in wire.operation()["query"]
    assert out["shops_count"] == 20 and out["not_found"] == ["999999999999"]
    assert [shop["id"] for shop in out["shops"]] == list(reversed(ids))          # in the order asked


def test_shops_bulk_of_nothing_known(monkeypatch, memory_cache):
    Wire(monkeypatch, answers("shop_not_found.json"))
    with pytest.raises(fetch.TokopediaNotFound, match="none of these shops was found: 998, 999"):
        api.shops_bulk("998,999")


def test_shops_products(monkeypatch, memory_cache):
    wire = Wire(monkeypatch, answers("shop_tomkinsofficial.json"), answers("shop_products_tomkinsofficial.json"),
                answers("shop_products_keyword_last_page.json"))
    out = call(schemas.ShopsProductsSchema, api.shops_products, {"shop": "tomkinsofficial"})
    assert wire.operation(1)["variables"] == {
        "source": "shop", "sid": "6638357", "page": 1, "perPage": 80, "etalaseId": "etalase", "sort": 1,
        "user_districtId": "2274", "user_cityId": "176", "user_lat": "0", "user_long": "0",
        "usecase": "ace_get_shop_product_v2"}
    assert list(out) == ["shop", "sort", "query", "products", "pagination"]
    assert out["shop"] == {"id": "6638357", "domain": "tomkinsofficial", "name": "TOMKINS",
                           "link": "https://www.tokopedia.com/tomkinsofficial"}
    assert out["sort"] == "default" and len(out["products"]) == 80
    assert out["pagination"] == {"page": 1, "items_per_page": 80, "has_next": True, "total_pages": None,
                                 "total_count": None}
    last = call(schemas.ShopsProductsSchema, api.shops_products, {"shop": "tomkinsofficial", "query": "rak",
                                                                  "sort": "price_low", "page": "2"})
    variables = wire.operation(2)["variables"]
    assert variables["keyword"] == "rak" and variables["sort"] == 9 and variables["page"] == 2
    assert len(wire.sent) == 3                       # the shop record was read once
    assert last["sort"] == "price_low" and last["query"] == "rak" and last["pagination"]["has_next"] is False


def test_shops_products_past_the_end(monkeypatch, memory_cache):
    Wire(monkeypatch, answers("shop_tomkinsofficial.json"), answers("shop_products_empty.json"))
    out = call(schemas.ShopsProductsSchema, api.shops_products, {"shop": "tomkinsofficial", "page": "50"})
    assert out["products"] == [] and out["pagination"]["has_next"] is False


def test_shops_products_last_page_the_endpoint_takes_has_no_next(monkeypatch, memory_cache):
    Wire(monkeypatch, answers("shop_tomkinsofficial.json"), answers("shop_products_tomkinsofficial.json"))
    out = call(schemas.ShopsProductsSchema, api.shops_products, {"shop": "tomkinsofficial",
                                                                 "page": str(refs.MAX_SHOP_PRODUCTS_PAGE)})
    assert len(out["products"]) == 80                # the site still says a next page exists
    assert out["pagination"]["has_next"] is False    # page 101 is refused, so no link to it


def test_shops_reviews(monkeypatch, memory_cache):
    wire = Wire(monkeypatch, answers("shop_tomkinsofficial.json"), answers("shop_reviews_6638357.json"))
    out = call(schemas.ShopsReviewsSchema, api.shops_reviews, {"shop": "tomkinsofficial", "stars": "1"})
    assert wire.operation(1)["variables"] == {"shopID": "6638357", "limit": 50, "page": 1, "filterBy": "rating=1",
                                              "sortBy": "create_time desc"}
    assert list(out) == ["shop", "sort", "stars", "with_media", "reviews", "pagination"]
    assert out["sort"] == "newest" and out["stars"] == [1] and len(out["reviews"]) == 10
    assert out["pagination"] == {"page": 1, "items_per_page": 50, "total_pages": 200, "total_count": 10000}


def test_shops_reviews_of_a_shop_without_reviews(monkeypatch, memory_cache):
    Wire(monkeypatch, answers("shop_sparse.json"), answers("shop_reviews_none.json"))
    out = call(schemas.ShopsReviewsSchema, api.shops_reviews, {"shop": "sepatu-inprot781"})
    assert out["reviews"] == [] and out["pagination"]["total_count"] == 0 and out["pagination"]["total_pages"] == 0


def test_shops_search(monkeypatch, memory_cache):
    wire = Wire(monkeypatch, answers("shop_search_sepatu.json"), answers("shop_search_past_end.json"),
                answers("shop_search_no_result.json"))
    out = call(schemas.ShopsSearchSchema, api.shops_search, {"query": "sepatu", "shop_type": "mall", "location": "Bandung"})
    params = wire.params()
    assert params["q"] == "sepatu" and params["rows"] == "60" and params["start"] == "0" and params["user_id"] == "0"
    assert params["shop_tier"] == "2" and params["fcity"] == "165"
    assert "x-device" not in wire.sent[0]["headers"]                 # the shop search page sends none
    assert list(out) == ["query", "shop_type", "location_city_ids", "suggested_query", "shops", "pagination"]
    assert out["shop_type"] == "mall" and len(out["shops"]) == 30
    assert out["pagination"] == {"page": 1, "items_per_page": 60, "total_pages": 44, "total_count": 2639}
    past = call(schemas.ShopsSearchSchema, api.shops_search, {"query": "sepatu", "page": "51"})
    assert wire.params(1)["start"] == "3000" and past["shops"] == [] and past["pagination"]["total_count"] == 2639
    none = call(schemas.ShopsSearchSchema, api.shops_search, {"query": "zzqqxxkkvv"})
    assert none["shops"] == [] and none["pagination"] == {"page": 1, "items_per_page": 60, "total_pages": 0,
                                                          "total_count": 0}


def test_limits_are_the_measured_ones():
    assert (refs.SEARCH_PER_PAGE, refs.MAX_SEARCH_PAGE, refs.SHOP_PRODUCTS_PER_PAGE) == (60, 100, 80)
    assert (refs.REVIEWS_PER_PAGE, refs.MAX_PRODUCT_REVIEWS_PAGE, refs.MAX_SHOP_REVIEWS_PAGE) == (50, 199, 200)
    assert (refs.OPERATIONS_PER_POST, refs.MAX_BULK_PRODUCTS, refs.MAX_BULK_SHOPS) == (6, 30, 100)
