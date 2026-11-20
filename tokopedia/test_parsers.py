"""Offline tests for tokopedia/parsers.py against the raw captures in
fixtures/ (taken 2026-11-20), plus the transport's reading of the site's
error answers.

    python -m pytest tokopedia/test_parsers.py -q
"""
import gzip
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tokopedia import fetch, parsers, refs  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
DAVEED, USED, SPARSE = "100773001007", "1822628908", "104467229787"


def answers(name):
    """The list of answers one POST returned."""
    path = os.path.join(FIXTURES, name)
    if not os.path.exists(path):
        path += ".gz"
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def data(name, field, index=0):
    return answers(name)[index]["data"][field]


def product(name, second=None):
    info = data(name, "pdpMainInfo")
    return parsers.parse_product(info, data(second, "pdpMainInfo")["data"] if second else None)


def keys_are_snake_case(value, path=""):
    if isinstance(value, dict):
        for key, item in value.items():
            assert key == key.lower() and " " not in key and "-" not in key, f"{path}.{key}"
            assert key != "url", f"{path}.{key}"
            keys_are_snake_case(item, f"{path}.{key}")
    elif isinstance(value, list):
        for item in value:
            keys_are_snake_case(item, path + "[]")


def no_empty_text(value, path=""):
    if isinstance(value, dict):
        for key, item in value.items():
            no_empty_text(item, f"{path}.{key}")
    elif isinstance(value, list):
        for item in value:
            no_empty_text(item, path + "[]")
    else:
        assert value != "" and value != "N/A", path


def well_formed(value):
    keys_are_snake_case(value)
    no_empty_text(value)


# ---- values ----------------------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("Rp459.000", 459000), ("Rp 114.880", 114880), ("Rp1.899.000", 1899000), (309000, 309000), ("Rp0", 0),
    ("", None), (None, None), ("Rp10.000 - Rp20.000", 10000), (True, None),
])
def test_rupiah(raw, expected):
    assert parsers.rupiah(raw) == expected


@pytest.mark.parametrize("raw, expected", [
    ("50+ terjual", 50), ("1rb+ terjual", 1000), ("10rb+ terjual", 10000), ("1 terjual", 1), ("2,4jt+", 2400000),
    ("2.4jt+", 2400000), ("71,5 rb", 71500), ("1.141", 1141), ("0", 0), ("", None), (None, None), ("terjual", None),
])
def test_short_count(raw, expected):
    assert parsers.short_count(raw) == expected


@pytest.mark.parametrize("raw, expected", [
    ("33%", 33), (">43%", 43), (33, 33), (0, None), ("", None), (None, None), ("98% pembeli merasa puas", 98),
])
def test_percent(raw, expected):
    assert parsers.percent(raw) == expected


def test_jakarta_time_is_given_in_utc():
    assert parsers.jakarta_time("2026-08-01 00:00:00") == "2026-07-31T17:00:00Z"
    assert parsers.jakarta_time("") is None and parsers.jakarta_time("soon") is None


def test_ids_and_tiers():
    assert parsers.id_or_none("0") is None and parsers.id_or_none(0) is None and parsers.id_or_none("") is None
    assert parsers.id_or_none(7494273546126722546) == "7494273546126722546"
    assert [parsers.shop_tier(t) for t in (1, 2, 3, 9, None)] == ["regular", "mall", "power_shop", None, None]


# ---- product lists ---------------------------------------------------------------------

def test_search_page():
    parsed = parsers.parse_search(data("search_sepatu.json", "searchProductV5"))
    assert parsed["total_count"] == 2418263 and len(parsed["products"]) == 60
    assert parsed["redirect_link"] is None and parsed["suggested_query"] is None
    row = next(r for r in parsed["products"] if r["id"] == DAVEED)
    assert row["name"] == "TOMKINS Daveed - Hijau Hitam Sepatu Casual Anak Remaja"
    assert row["link"] == ("https://www.tokopedia.com/tomkinsofficial/tomkins-daveed-hijau-hitam-sepatu-casual-anak-"
                           "remaja-1731945700296001445")           # the tracking query is gone
    assert row["parent_id"] == "100773001006"
    assert row["price"] == {"amount": 309000, "currency": "IDR", "original_amount": 459000, "discount_percent": 33,
                            "net_amount": None}
    assert row["rating"] == 5.0 and row["sold_count"] == 50 and row["sold_label"] == "50+ terjual"
    assert row["labels"] == ["Beli Lokal", "Hemat s.d 8% Pakai Bonus", "Bisa COD"] and row["is_cod"] is True
    assert row["shop"] == {"id": "6638357", "name": "TOMKINS", "domain": "tomkinsofficial",
                           "link": "https://www.tokopedia.com/tomkinsofficial", "city": "Bandung", "tier": "mall"}
    assert row["category"] == {"id": "1759", "name": "Fashion Pria", "link": "https://www.tokopedia.com/p/fashion-pria",
                               "leaf_path": "fashion-pria/sepatu-pria/sneakers-pria",
                               "leaf_link": "https://www.tokopedia.com/p/fashion-pria/sepatu-pria/sneakers-pria"}
    assert row["tiktok_shop"] == {"product_id": "1731945672868923301", "sku_id": "1731945700296001445",
                                  "seller_id": "7494872585819229093"}
    assert row["image"].startswith("https://")
    well_formed(parsed)


def test_search_rows_without_a_rating_or_a_discount():
    rows = parsers.parse_search(data("search_sepatu.json", "searchProductV5"))["products"]
    unrated = [r for r in rows if r["rating"] is None]
    assert len(unrated) == 3 and all(r["id"] for r in rows)
    plain = rows[0]                              # no ribbon label, no crossed-out price
    assert plain["price"]["discount_percent"] is None and plain["price"]["original_amount"] is None
    assert plain["sold_count"] is None and plain["sold_label"] is None
    assert {r["shop"]["tier"] for r in rows} == {"regular", "mall", "power_shop"}
    assert any(r["price"]["net_amount"] for r in rows) and any(r["video"] for r in rows)


def test_search_with_no_result_and_past_the_end_read_alike():
    for name in ("search_no_result.json", "search_past_end.json"):
        parsed = parsers.parse_search(data(name, "searchProductV5"))
        assert parsed["products"] == [] and parsed["total_count"] == 0


def test_search_the_site_redirects():
    parsed = parsers.parse_search(data("search_redirect_pulsa.json", "searchProductV5"))
    assert parsed["products"] == [] and parsed["redirect_link"] == "https://tokopedia.com/pulsa?dg_value=1"


def test_category_list_through_the_search_call():
    parsed = parsers.parse_search(data("category_sepatu_pria.json", "searchProductV5"))
    assert parsed["total_count"] == 1428178 and len(parsed["products"]) == 60
    assert {r["category"]["leaf_path"].split("/")[1] for r in parsed["products"]} == {"sepatu-pria"}
    well_formed(parsed)


def test_category_list_through_the_category_pages_own_call():
    parsed = parsers.parse_legacy_category(data("category_sepatu_pria_legacy.json", "CategoryProducts"))
    assert parsed["total_count"] == 1428202 and len(parsed["products"]) == 60
    row = parsed["products"][0]
    assert row["id"] == "100196376917" and row["price"]["amount"] == 950000 and row["price"]["currency"] == "IDR"
    assert row["shop"] == {"id": "11560671", "name": "adidas Indonesia", "domain": "adidasindonesiaofficial",
                           "link": "https://www.tokopedia.com/adidasindonesiaofficial", "city": "Bekasi", "tier": "mall"}
    assert row["category"]["leaf_path"] == "fashion-pria/sepatu-pria/sneakers-pria"
    assert row["sold_count"] == 18 and row["rating"] is None
    assert set(row) == set(parsers.parse_search(data("search_sepatu.json", "searchProductV5"))["products"][0])
    well_formed(parsed)
    empty = parsers.parse_legacy_category(data("category_legacy_empty.json", "CategoryProducts"))
    assert empty["products"] == [] and empty["total_count"] == 0


# ---- the category tree -----------------------------------------------------------------

def test_category_tree():
    tree = parsers.parse_categories(data("categories.json", "CategoryAllList")["categories"])
    assert len(tree) == 29 and all(node["id"] and node["level"] == 1 for node in tree)      # the id-0 shelf is left out
    flat = parsers.flatten_categories(tree)
    assert len(flat) == 3312 and len({node["id"] for node in flat}) == 3312
    by_id = {node["id"]: node for node in flat}
    assert by_id["1759"] == {"id": "1759", "name": "Fashion Pria", "link": "https://www.tokopedia.com/p/fashion-pria",
                             "path": "fashion-pria", "level": 1, "parents": []}
    shoes = by_id["1845"]
    assert shoes["path"] == "fashion-pria/sepatu-pria/sneakers-pria" and shoes["level"] == 3
    assert [parent["id"] for parent in shoes["parents"]] == ["1759", "1800"]
    well_formed(tree)


# ---- one product -----------------------------------------------------------------------

def test_product_with_both_calls():
    record = product("product_100773001007.json", "product_100773001007_second.json")
    assert record["id"] == DAVEED and record["parent_id"] == "100773001006"
    assert record["name"] == "TOMKINS Daveed - Hijau Hitam Sepatu Casual Anak Remaja - Ukuran 33"
    assert record["link"].endswith("/tomkinsofficial/tomkins-daveed-hijau-hitam-sepatu-casual-anak-remaja-1731945700296001445")
    assert record["condition"] == "new" and record["status"] == "active"
    assert record["created_at"] == "2025-07-15T05:18:40Z"                 # 12:18:40 +07:00
    assert record["price"] == {"amount": 309000, "currency": "IDR", "original_amount": 459000, "discount_percent": 33}
    campaign = record["campaign"]
    assert campaign["name"] == "Diskon Terbatas" and campaign["is_active"] and campaign["discount_percent"] == 33
    assert campaign["starts_at"] == "2026-07-31T17:00:00Z" and campaign["ends_at"] == "2026-12-31T16:59:00Z"
    assert record["stock"] == 141 and record["min_order"] == 1 and record["max_order"] == 141
    assert record["weight"] == {"value": 1, "unit": "kilogram", "grams": 1000}
    assert record["rating"] == 5.0 and record["reviews_count"] == 24 and record["sold_count"] == 54
    assert record["wishlist_count"] == 5 and record["brand"] == "Tomkins"
    assert record["category"]["id"] == "1845" and [n["id"] for n in record["category"]["path"]] == ["1759", "1800", "1845"]
    assert record["description"].startswith("TOMKINS Daveed\nsepatu casual") and "\xa0" not in record["description"]
    assert {"name": "Merek", "value": "Tomkins", "link": None} in record["specifications"]
    assert record["is_official_store"] is True and record["is_preorder"] is False
    shop = record["shop"]
    assert (shop["id"], shop["domain"], shop["location"], shop["tier"]) == ("6638357", "tomkinsofficial", "Kota Bandung", "mall")
    assert shop["link"] == "https://www.tokopedia.com/tomkinsofficial" and shop["rating"] == 4.9
    assert shop["active_products_count"] == 219 and shop["opened_at"] == "2022-12-22T07:03:32Z"
    shipping = record["shipping"]
    assert shipping["cheapest_amount"] == 10000 and shipping["title"] == "Ongkir Rp10.000"
    assert shipping["notes"] and shipping["ships_from"]["postal_code"] == "40295"
    assert record["tiktok_shop"]["product_id"] == "1731945672868923301"
    assert [n["id"] for n in record["tiktok_shop"]["category_path"]][0] == "601352"
    well_formed(record)


def test_product_pictures_have_a_link_that_does_not_expire():
    record = product("product_100773001007.json")
    assert record["images_count"] == 13 == len(record["images"])
    first = record["images"][0]
    assert first["link"] == ("https://images.tokopedia.net/img/cache/700/o3syd0/1997/1/1/"
                             "7a3d47dc511e4c939181a30b49521663~.jpeg.webp")
    assert "x-expires=" in first["signed_link"] and "x-expires=" in first["thumbnail"]
    assert refs.stable_image("", "/a.jpeg") is None and refs.stable_image("https://h/", None) is None


def test_product_variants():
    variants = product("product_100773001007.json")["variants"]
    assert variants["parent_id"] == "100773001006" and variants["default_id"] == DAVEED
    assert variants["total_stock"] == 1141 and variants["size_chart"].startswith("https://")
    assert [option["name"] for option in variants["options"]] == ["ukuran"]
    assert len(variants["options"][0]["values"]) == 6 == len(variants["items"])
    item = variants["items"][0]
    assert item["id"] == DAVEED and item["options"] == ["Ukuran 33"] and item["stock"] == 141 and item["is_buyable"]
    assert item["price"]["amount"] == 309000 and item["price"]["original_amount"] == 459000
    assert item["campaign"]["ends_at"] == "2026-12-31T16:59:00Z"
    two = product("product_1822628908_used.json")["variants"]
    assert [option["kind"] for option in two["options"]] == ["colour", "size"]
    assert two["items"][0]["options"] == ["Tan", "37"] and two["items"][0]["campaign"] is None


def test_product_without_the_second_call():
    record = product("product_100773001007.json")
    assert record["wishlist_count"] is None and record["shipping"] is None
    assert record["shop"]["id"] == "6638357" and record["shop"]["name"] == "TOMKINS"
    assert record["shop"]["domain"] == "tomkinsofficial" and record["shop"]["location"] is None
    assert [spec["name"] for spec in record["specifications"]][:2] == ["Kondisi", "Pemesanan Minimum"]
    well_formed(record)


def test_used_product():
    record = product("product_1822628908_used.json", "product_1822628908_used_second.json")
    assert record["id"] == USED and record["condition"] == "used" and record["campaign"] is None
    assert record["price"] == {"amount": 89900, "currency": "IDR", "original_amount": None, "discount_percent": None}
    assert record["stock"] == 15 and record["stock_note"] == "Stok tinggal <20, beli segera!"      # &lt; in the raw text
    assert record["weight"]["grams"] == 300 and record["brand"] is None
    assert record["shipping"]["has_free_shipping"] is True and record["shipping"]["ships_from"]["city"] == "Kab. Bogor"
    well_formed(record)


def test_sparse_product_of_a_new_seller():
    record = product("product_104467229787_sparse.json", "product_104467229787_sparse_second.json")
    assert record["id"] == SPARSE and record["rating"] is None and record["reviews_count"] == 0
    assert record["sold_count"] == 0 and record["sold_label"] is None and record["campaign"] is None
    assert record["shop"]["tier"] == "regular" and record["shop"]["rating"] == 2.5
    assert record["shop"]["last_active_at"] is None and record["wishlist_count"] == 0
    well_formed(record)


def test_six_products_from_one_post():
    records = [parsers.parse_product(answer["data"]["pdpMainInfo"]) for answer in answers("products_six.json")]
    assert len(records) == 6 and len({record["id"] for record in records}) == 6
    assert all(record["name"] and record["price"]["amount"] for record in records)


def test_a_product_without_a_creation_date_on_record():
    info = answers("products_six.json")[5]["data"]["pdpMainInfo"]
    assert info["data"]["basicInfo"]["createdAt"] == "1970-01-01T07:00:00+07:00"       # the site's zero
    assert parsers.parse_product(info)["created_at"] is None
    assert parsers.created_time("2025-07-15T12:18:40+07:00") == "2025-07-15T05:18:40Z"
    assert parsers.created_time("") is None and parsers.created_time(None) is None


def test_an_answer_that_names_no_product():
    assert parsers.parse_product(None) is None and parsers.parse_product({"data": {"basicInfo": {}}}) is None
    assert parsers.extra_payload(data("product_100773001007.json", "pdpMainInfo")).startswith("3gAy")
    assert parsers.extra_payload({}) is None


# ---- reviews ---------------------------------------------------------------------------

def test_product_reviews():
    parsed = parsers.parse_product_reviews(data("reviews_100070724287.json", "productrevGetProductReviewList"))
    assert parsed["product_id"] == "100070724279"            # the parent product the reviews belong to
    assert parsed["total_count"] == 10000 and parsed["has_next"] is True and len(parsed["reviews"]) == 10
    assert parsed["shop"]["domain"] == "pavillionshoes"
    review = parsed["reviews"][0]
    assert review["id"] == "1458697193" and review["rating"] == 5 and review["created_at"] == "2025-05-14T18:56:07Z"
    assert review["text"] and review["reviewer"]["name"] and isinstance(review["likes_count"], int)
    assert all(r["images"] for r in parsed["reviews"]) and any(r["videos"] for r in parsed["reviews"])
    assert all(r["is_anonymous"] and r["reviewer"]["id"] is None for r in parsed["reviews"])      # the site masks them
    assert review["reviewer"]["name"] == "F***j" and review["variant"] == "Blue - 39(4)"
    well_formed(parsed)


def test_last_page_of_reviews_and_the_reply():
    parsed = parsers.parse_product_reviews(data("reviews_100773001007_last_page.json", "productrevGetProductReviewList"))
    assert len(parsed["reviews"]) == 7 == parsed["total_count"] and parsed["has_next"] is False
    assert all(r["seller_reply"]["text"] and r["seller_reply"]["created_ago"] for r in parsed["reviews"])
    named, masked = parsed["reviews"][0], parsed["reviews"][3]
    assert named["reviewer"] == {"id": "32204658", "name": "muhamad", "avatar": named["reviewer"]["avatar"],
                                 "link": "https://www.tokopedia.com/people/32204658"} and not named["is_anonymous"]
    assert masked["reviewer"]["id"] is None and masked["reviewer"]["name"] == "b***a" and masked["is_anonymous"]
    assert masked["reviewer"]["link"] is None and masked["seller_reply"]["text"].startswith("Terima kasih")


@pytest.mark.parametrize("name", ["reviews_none.json", "reviews_past_end.json"])
def test_no_reviews(name):
    parsed = parsers.parse_product_reviews(data(name, "productrevGetProductReviewList"))
    assert parsed == {"product_id": None, "shop": None, "reviews": [], "has_next": False, "total_count": 0}


def test_rating_summary():
    summary = parsers.parse_rating_summary(data("review_summary_100070724287.json", "productrevGetProductRatingAndTopics"))
    rating = summary["rating"]
    assert rating["score"] == 4.9 and rating["ratings_count"] > 40000 and rating["satisfied_percent"] == 98
    assert [row["stars"] for row in rating["breakdown"]] == [5, 4, 3, 2, 1]
    assert sum(row["count"] for row in rating["breakdown"]) == rating["ratings_count"]
    assert "sesuai deskripsi" in [topic["key"] for topic in summary["topics"]]
    assert all(refs.TOPIC_RE.match(topic["key"]) for topic in summary["topics"])
    well_formed(summary)


def test_rating_summary_of_a_product_without_reviews():
    summary = parsers.parse_rating_summary(data("review_summary_none.json", "productrevGetProductRatingAndTopics"))
    assert summary["rating"]["score"] is None and summary["rating"]["ratings_count"] == 0
    assert summary["rating"]["satisfied_percent"] is None
    assert parsers.parse_rating_summary(None) is None


def test_shop_reviews():
    parsed = parsers.parse_shop_reviews(data("shop_reviews_6638357.json", "productrevGetShopReviewReadingList"))
    assert parsed["shop_name"] == "TOMKINS" and parsed["total_count"] == 10000 and len(parsed["reviews"]) == 10
    review = parsed["reviews"][0]
    assert review["id"] == "2415045121" and review["rating"] == 5 and review["created_ago"] == "Hari ini"
    assert "&amp;" not in review["text"] and "aman & gak" in review["text"]
    assert review["product"]["id"] == "100000336445" and review["product"]["variant"] == "Ukuran 40"
    assert review["product"]["link"].startswith("https://www.tokopedia.com/tomkinsofficial/")
    assert len(review["images"]) == 1 and review["seller_reply"] is None
    well_formed(parsed)
    empty = parsers.parse_shop_reviews(data("shop_reviews_none.json", "productrevGetShopReviewReadingList"))
    assert empty == {"shop_name": "Kurir sepatu", "reviews": [], "has_next": False, "total_count": 0}


# ---- shops -----------------------------------------------------------------------------

def test_shop_record():
    shop = parsers.parse_shop(data("shop_tomkinsofficial.json", "shopInfoByID")["result"][0])
    assert (shop["id"], shop["domain"], shop["name"]) == ("6638357", "tomkinsofficial", "TOMKINS")
    assert shop["link"] == "https://www.tokopedia.com/tomkinsofficial"
    assert shop["city"] == "Kota Bandung" and shop["district"] == "Gedebage" and shop["opened_month"] == "2022-12"
    assert shop["tier"] == "mall" and shop["is_official"] and shop["is_power_merchant"] and shop["is_open"]
    assert shop["followers_count"] == 27749 and shop["active_products_count"] == 219
    assert shop["products_sold_count"] == 41930 and shop["transactions_count"] == 38236 and shop["showcases_count"] == 11
    assert "<" not in shop["seo"]["text"] and shop["seo"]["text"].startswith("Beraktivitas Semakin Nyaman")
    assert shop["rating"] is None and shop["description"] is None      # other operations hold them
    well_formed(shop)


def test_shop_from_three_operations_in_one_post():
    core, statistic, description = answers("shop_6638357_three_operations.json")
    shop = parsers.parse_shop(core["data"]["shopInfoByID"]["result"][0])
    blocks = parsers.parse_shop_statistic(statistic["data"])
    assert blocks["rating"]["score"] == 4.9 and blocks["rating"]["ratings_count"] == 76579
    assert [row["stars"] for row in blocks["rating"]["breakdown"]] == [5, 4, 3, 2, 1]
    assert blocks["rating"]["breakdown"][0] == {"stars": 5, "count": 71594, "percent": 93.49}
    assert blocks["satisfaction"] == {"good": 0, "neutral": 0, "bad": 0} and blocks["reputation"] is None
    text = parsers.parse_shop_description(description["data"], shop["id"])
    assert text.startswith("Tomkins Official Shop") and "\n" in text
    assert parsers.parse_shop_description(description["data"], "1") is None
    assert parsers.parse_shop_description({}, shop["id"]) is None


def test_sparse_shop():
    shop = parsers.parse_shop(data("shop_sparse.json", "shopInfoByID")["result"][0])
    assert shop["tier"] == "regular" and shop["is_official"] is False and shop["followers_count"] == 1
    blocks = parsers.parse_shop_statistic(answers("shop_statistic_sparse.json")[0]["data"])
    assert blocks["rating"]["score"] is None and blocks["rating"]["ratings_count"] == 0
    assert parsers.parse_shop({}) is None and parsers.parse_shop(None) is None


def test_many_shops():
    rows = data("shops_twenty.json", "shopInfoByID")["result"]
    shops = [parsers.parse_shop(row) for row in rows]
    assert len(shops) == 20 and all(shop["id"] and shop["link"] for shop in shops)
    well_formed(shops)


def test_shop_products():
    parsed = parsers.parse_shop_products(data("shop_products_tomkinsofficial.json", "GetShopProduct"))
    assert len(parsed["products"]) == 80 and parsed["has_next"] is True
    row = parsed["products"][0]
    assert row["id"] == "104420069894" and row["price"]["amount"] == 259000 and row["price"]["original_amount"] == 469000
    assert row["price"]["discount_percent"] and row["sold_count"] == 1 and row["sold_label"] == "1 terjual"
    assert row["link"].startswith("https://www.tokopedia.com/tomkinsofficial/") and row["is_sold_out"] is False
    assert any(r["rating"] == 4.9 for r in parsed["products"]) and any(r["rating"] is None for r in parsed["products"])
    well_formed(parsed)


def test_shop_products_last_page_and_empty_page():
    last = parsers.parse_shop_products(data("shop_products_keyword_last_page.json", "GetShopProduct"))
    assert len(last["products"]) == 54 and last["has_next"] is False
    assert last["products"][0]["price"]["original_amount"] is None and last["products"][0]["price"]["discount_percent"] is None
    empty = parsers.parse_shop_products(data("shop_products_empty.json", "GetShopProduct"))
    assert empty == {"products": [], "has_next": False}


def test_shop_search():
    parsed = parsers.parse_shop_search(data("shop_search_sepatu.json", "aceSearchShop"))
    assert parsed["total_count"] == 2639 and len(parsed["shops"]) == 30
    shop = parsed["shops"][0]
    assert (shop["id"], shop["domain"], shop["location"]) == ("18075569", "sepatu-inprot781", "Jakarta Timur")
    assert shop["link"] == "https://www.tokopedia.com/sepatu-inprot781" and shop["is_open"] is True
    assert len(shop["products"]) == 3 and shop["products"][0]["price"] == {"amount": 773800, "currency": "IDR"}
    well_formed(parsed)
    for name in ("shop_search_no_result.json", "shop_search_past_end.json"):
        assert parsers.parse_shop_search(data(name, "aceSearchShop"))["shops"] == []
    assert parsers.parse_shop_search(data("shop_search_past_end.json", "aceSearchShop"))["total_count"] == 2639


# ---- the site's error answers ----------------------------------------------------------

@pytest.mark.parametrize("name", [
    "product_not_found.json", "product_id_not_found.json", "product_id_lookup_not_found.json",
    "reviews_product_not_found.json", "shop_not_found.json", "shop_reviews_not_found.json",
])
def test_not_found_answers(name):
    with pytest.raises(fetch.TokopediaNotFound):
        fetch.data_of(answers(name)[0], "it")


def test_invalid_argument_is_a_bad_request():
    with pytest.raises(fetch.TokopediaBadRequest):
        fetch.data_of(answers("error_reviews_invalid_argument.json")[0], "reviews")


@pytest.mark.parametrize("name", ["error_reviews_too_deep.json", "product_second_without_payload.json",
                                  "error_seven_operations.json"])
def test_other_error_answers_are_retryable(name):
    with pytest.raises(fetch.TokopediaUpstreamError):
        fetch.data_of(answers(name)[0], "it")


def test_a_good_answer_passes():
    answer = answers("product_id_lookup.json")[0]
    assert fetch.data_of(answer, "it")["productrevGetMiniProductInfo"]["product"]["id"] == DAVEED
    assert fetch.error_of(answer) == (None, "")
    assert fetch.error_of(answers("shop_not_found.json")[0]) == (2001, "[1000410] Shop Not Found")
