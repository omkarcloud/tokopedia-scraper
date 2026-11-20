"""Offline tests for the /tokopedia/* request schemas and the reference
resolvers.

    python -m pytest tokopedia/test_schemas.py -q
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from schema_fields import load_query  # noqa: E402
from tokopedia import refs, schemas  # noqa: E402

DAVEED = "100773001007"
KEY = "tomkins-daveed-hijau-hitam-sepatu-casual-anak-remaja-1731945700296001445"
PRODUCT_LINK = f"https://www.tokopedia.com/tomkinsofficial/{KEY}"
PRODUCT_REF = f"tomkinsofficial/{KEY}"
SHOP_LINK = "https://www.tokopedia.com/tomkinsofficial"
CATEGORY_LINK = "https://www.tokopedia.com/p/fashion-pria/sepatu-pria"


def errors_of(schema, query):
    data, error = load_query(schema, query)
    assert data is None, f"expected a refusal, got {data}"
    return error["errors"]


def loaded(schema, query):
    data, error = load_query(schema, query)
    assert error is None, error
    return data


# ---- product -----------------------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    (DAVEED, DAVEED),
    (f" {DAVEED} ", DAVEED),
    (PRODUCT_LINK, PRODUCT_REF),
    (PRODUCT_LINK + "?extParam=ivf%3Dfalse%26src%3Dsearch", PRODUCT_REF),
    (PRODUCT_LINK + "/review", PRODUCT_REF),
    (f"www.tokopedia.com/tomkinsofficial/{KEY}", PRODUCT_REF),
    (f"tokopedia.com/TomkinsOfficial/{KEY}", PRODUCT_REF),
    (f"https://m.tokopedia.com/tomkinsofficial/{KEY}", PRODUCT_REF),
    (f"/tomkinsofficial/{KEY}", PRODUCT_REF),
])
def test_product_accepts_an_id_or_a_link(value, expected):
    assert loaded(schemas.ProductSchema, {"product": value}) == {"product": expected}
    assert refs.is_product_id(expected) == expected.isdigit()


@pytest.mark.parametrize("value", [
    "abc", "12", SHOP_LINK, SHOP_LINK + "/product", SHOP_LINK + "/review", SHOP_LINK + "/etalase/sandal", CATEGORY_LINK,
    "https://www.tokopedia.com/search?q=sepatu", "https://www.tokopedia.com/", "https://shopee.co.id/a/b",
    "https://www.tokopedia.com/a/b/c/d",
])
def test_product_refuses_what_is_no_product(value):
    message = errors_of(schemas.ProductSchema, {"product": value})["product"][0]
    assert "product" in message.lower() or "tokopedia.com link" in message


@pytest.mark.parametrize("value", ["https://tk.tokopedia.com/ZSabc/", "tk.tokopedia.com/ZSabc/",
                                   "vt.tokopedia.com/t/ZSabc/", "tokopedia.link/abc"])
def test_a_short_link_is_refused_with_what_to_do(value):
    message = errors_of(schemas.ProductSchema, {"product": value})["product"][0]
    assert message == "A short link names no product by itself: open it and pass the link it leads to."
    assert errors_of(schemas.ShopSchema, {"shop": value})["shop"][0] == message


def test_product_is_required_and_unknown_params_are_refused():
    assert "product" in errors_of(schemas.ProductSchema, {})
    assert "product" in errors_of(schemas.ProductSchema, {"product": ""})
    assert "url" in errors_of(schemas.ProductSchema, {"product": DAVEED, "url": PRODUCT_LINK})


def test_product_link_round_trip():
    assert refs.split_product(PRODUCT_REF) == ("tomkinsofficial", KEY)
    assert refs.product_ref_link(PRODUCT_REF) == PRODUCT_LINK


def test_bulk_products():
    data = loaded(schemas.ProductsBulkSchema, {"products": f"{DAVEED}, {PRODUCT_LINK},{DAVEED},, 1822628908"})
    assert data["products"] == f"{DAVEED},{PRODUCT_REF},1822628908"
    assert refs.split_refs(data["products"]) == [DAVEED, PRODUCT_REF, "1822628908"]
    thirty = ",".join(str(10000 + n) for n in range(30))
    assert len(refs.split_refs(loaded(schemas.ProductsBulkSchema, {"products": thirty})["products"])) == 30
    too_many = ",".join(str(10000 + n) for n in range(31))
    assert errors_of(schemas.ProductsBulkSchema, {"products": too_many})["products"] == ["At most 30 products in one call."]
    assert "products" in errors_of(schemas.ProductsBulkSchema, {"products": f"{DAVEED},nope"})
    assert "products" in errors_of(schemas.ProductsBulkSchema, {"products": " , "})


# ---- shop --------------------------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    ("tomkinsofficial", "tomkinsofficial"),
    ("TomkinsOfficial", "tomkinsofficial"),
    ("haze--honeymall", "haze--honeymall"),
    ("6638357", "6638357"),
    ("7496151511420275428", "7496151511420275428"),
    (SHOP_LINK, "tomkinsofficial"),
    (SHOP_LINK + "/product?sort=9", "tomkinsofficial"),
    (SHOP_LINK + "/review", "tomkinsofficial"),
    (PRODUCT_LINK, "tomkinsofficial"),
    ("tokopedia.com/osfrans", "osfrans"),
])
def test_shop_accepts_a_domain_an_id_or_a_link(value, expected):
    assert loaded(schemas.ShopSchema, {"shop": value}) == {"shop": expected}


@pytest.mark.parametrize("value", ["https://www.tokopedia.com/p/fashion-pria", "https://www.tokopedia.com/search?q=x",
                                   "https://www.tokopedia.com/", "a shop", "https://www.lazada.co.id/shop/x", "search"])
def test_shop_refuses_what_is_no_shop(value):
    assert "shop" in errors_of(schemas.ShopSchema, {"shop": value})


def test_bulk_shops_takes_ids_only():
    assert loaded(schemas.ShopsBulkSchema, {"shops": "6638357, 1318431,6638357"}) == {"shops": "6638357,1318431"}
    message = errors_of(schemas.ShopsBulkSchema, {"shops": "6638357,tomkinsofficial"})["shops"][0]
    assert message.startswith("'tomkinsofficial' is not a shop id") and "/tokopedia/shops/details" in message
    hundred_one = ",".join(str(1000 + n) for n in range(101))
    assert errors_of(schemas.ShopsBulkSchema, {"shops": hundred_one})["shops"] == ["At most 100 shops in one call."]


# ---- category ----------------------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    ("1800", "1800"),
    (CATEGORY_LINK, "fashion-pria/sepatu-pria"),
    (CATEGORY_LINK + "/sneakers-pria?ob=9", "fashion-pria/sepatu-pria/sneakers-pria"),
    ("/p/fashion-pria", "fashion-pria"),
    ("fashion-pria/sepatu-pria", "fashion-pria/sepatu-pria"),
    ("Fashion-Pria", "fashion-pria"),
])
def test_category_accepts_an_id_or_a_link(value, expected):
    assert loaded(schemas.CategoriesProductsSchema, {"category": value})["category"] == expected
    assert refs.is_category_id(expected) == expected.isdigit()


@pytest.mark.parametrize("value", ["https://www.tokopedia.com/p", "a/b/c/d", "sepatu pria", "https://example.com/p/x"])
def test_category_refuses_what_is_no_category(value):
    assert "category" in errors_of(schemas.CategoriesProductsSchema, {"category": value})


def test_category_path_of_a_link():
    assert refs.category_path_of(CATEGORY_LINK) == "fashion-pria/sepatu-pria"
    assert refs.category_path_of(None) is None and refs.category_path_of("") is None
    assert refs.category_link("fashion-pria") == "https://www.tokopedia.com/p/fashion-pria"


# ---- the product lists -------------------------------------------------------------------

def test_search_defaults():
    data = loaded(schemas.ProductsSearchSchema, {"query": " sepatu  lari "})
    assert data == {"query": "sepatu lari", "category": None, "page": 1, "sort": "23", "min_price": None,
                    "max_price": None, "rating_4_up": None, "condition": None, "shop_type": None, "location": None,
                    "cod": None, "discounted": None, "stock": None, "listed_within_days": None, "delivery": None}


def test_search_filters_become_the_sites_tokens():
    data = loaded(schemas.ProductsSearchSchema, {
        "query": "sepatu", "page": "3", "sort": "Price_Low", "min_price": "100000", "max_price": "200000",
        "rating_4_up": "true", "condition": "used", "shop_type": "mall", "location": "Bandung, jawa tengah",
        "cod": "1", "discounted": "yes", "stock": "preorder", "listed_within_days": "30", "delivery": "same_day",
        "category": CATEGORY_LINK})
    assert data["sort"] == "3" and data["page"] == 3 and data["min_price"] == 100000 and data["max_price"] == 200000
    assert data["condition"] == "2" and data["shop_type"] == "2" and data["stock"] == "true"
    assert data["listed_within_days"] == 30 and data["delivery"] == "nearby,7408193863459800833,7408194434065663761"
    assert data["rating_4_up"] is True and data["cod"] is True and data["discounted"] is True
    assert data["location"].split(",")[:2] == ["165", "180"] and data["category"] == "fashion-pria/sepatu-pria"


@pytest.mark.parametrize("param, value", [
    ("sort", "cheapest"), ("condition", "refurbished"), ("shop_type", "official"), ("stock", "sold_out"),
    ("listed_within_days", "10"), ("delivery", "drone"), ("page", "0"), ("page", "101"), ("page", "x"),
    ("min_price", "-1"), ("min_price", "cheap"), ("rating_4_up", "maybe"), ("location", "Atlantis"),
])
def test_a_wrong_value_is_refused_by_name(param, value):
    assert param in errors_of(schemas.ProductsSearchSchema, {"query": "sepatu", param: value})
    assert param in errors_of(schemas.CategoriesProductsSchema, {"category": "1800", param: value})


def test_price_range_must_be_in_order():
    errors = errors_of(schemas.ProductsSearchSchema, {"query": "x", "min_price": "200", "max_price": "100"})
    assert errors == {"min_price": ["min_price is above max_price."]}


def test_an_optional_param_sent_empty_is_absent():
    data = loaded(schemas.ProductsSearchSchema, {"query": "sepatu", "page": "", "cod": "", "min_price": " ", "sort": "",
                                                 "location": "", "category": ""})
    assert data["page"] == 1 and data["cod"] is None and data["min_price"] is None and data["sort"] == "23"
    assert data["location"] is None and data["category"] is None
    assert "query" in errors_of(schemas.ProductsSearchSchema, {"query": ""})


def test_query_and_category_are_required_where_they_name_the_list():
    assert "query" in errors_of(schemas.ProductsSearchSchema, {})
    assert "category" in errors_of(schemas.CategoriesProductsSchema, {})
    assert "query" in errors_of(schemas.CategoriesProductsSchema, {"category": "1800", "query": "sepatu"})


def test_categories_list_takes_no_params():
    assert loaded(schemas.CategoriesListSchema, {}) == {}
    assert "category" in errors_of(schemas.CategoriesListSchema, {"category": "1800"})


# ---- locations ---------------------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    ("Bandung", "165"),
    ("bandung", "165"),
    ("165", "165"),
    ("DKI Jakarta", "174,175,176,177,178,179"),
    ("kab bogor", refs.resolve_location("Kab. Bogor")),
    ("Bandung, Surabaya, 165", "165,252"),
    ("Bengkulu", "52,53,54,55,56,57,58,59,464,60"),          # the province and its capital share the name
])
def test_location_names_and_ids(value, expected):
    assert refs.resolve_location(value) == expected


def test_location_refusals():
    with pytest.raises(ValueError, match="Unknown location 'Atlantis'"):
        refs.resolve_location("Bandung, Atlantis")
    assert len(refs.resolve_location("Jawa Barat, Jawa Tengah, Jawa Timur").split(",")) == 100
    with pytest.raises(ValueError, match="At most 534 city ids"):
        refs.resolve_location(",".join(str(n) for n in range(1, 536)))
    with pytest.raises(ValueError):
        refs.resolve_location(" , ")


def test_every_listed_location_resolves():
    from tokopedia.locations import LOCATIONS
    assert len(LOCATIONS) == 551
    for name, ids in LOCATIONS.items():
        assert refs.resolve_location(name) == ids and all(part.isdigit() for part in ids.split(","))


# ---- reviews -----------------------------------------------------------------------------

def test_review_defaults_differ_per_list_as_the_site_does():
    product = loaded(schemas.ProductsReviewsSchema, {"product": DAVEED})
    assert product == {"product": DAVEED, "page": 1, "sort": "informative_score desc", "stars": None,
                       "with_media": None, "topic": None}
    shop = loaded(schemas.ShopsReviewsSchema, {"shop": "tomkinsofficial"})
    assert shop == {"shop": "tomkinsofficial", "page": 1, "sort": "create_time desc", "stars": None, "with_media": None}


def test_review_filters():
    data = loaded(schemas.ProductsReviewsSchema, {"product": DAVEED, "sort": "rating_low", "stars": "2, 1,2",
                                                  "with_media": "true", "topic": "Sesuai Deskripsi", "page": "199"})
    assert data["sort"] == "rating asc" and data["stars"] == ["2", "1"] and data["with_media"] is True
    assert data["topic"] == "sesuai deskripsi" and data["page"] == 199
    assert refs.review_filter(data["stars"], True, data["topic"]) == "media=image,video;rating=2,1;topic=sesuai deskripsi"
    assert refs.review_filter() == "" and refs.review_filter(["5"]) == "rating=5"


@pytest.mark.parametrize("schema, base, param, value", [
    (schemas.ProductsReviewsSchema, {"product": DAVEED}, "sort", "banana"),
    (schemas.ProductsReviewsSchema, {"product": DAVEED}, "stars", "6"),
    (schemas.ProductsReviewsSchema, {"product": DAVEED}, "stars", "five"),
    (schemas.ProductsReviewsSchema, {"product": DAVEED}, "page", "200"),
    (schemas.ProductsReviewsSchema, {"product": DAVEED}, "topic", "a;rating=1"),
    (schemas.ProductsReviewsSchema, {"product": DAVEED}, "with_media", "some"),
    (schemas.ShopsReviewsSchema, {"shop": "x1"}, "sort", "oldest"),
    (schemas.ShopsReviewsSchema, {"shop": "x1"}, "page", "201"),
    (schemas.ShopsReviewsSchema, {"shop": "x1"}, "topic", "kualitas"),
])
def test_review_refusals(schema, base, param, value):
    assert param in errors_of(schema, {**base, param: value})


# ---- shop lists --------------------------------------------------------------------------

def test_shop_products():
    data = loaded(schemas.ShopsProductsSchema, {"shop": SHOP_LINK})
    assert data == {"shop": "tomkinsofficial", "page": 1, "sort": 1, "query": None}
    data = loaded(schemas.ShopsProductsSchema, {"shop": "6638357", "sort": "best_selling", "query": " rak ", "page": "2"})
    assert data == {"shop": "6638357", "page": 2, "sort": 8, "query": "rak"}
    assert "sort" in errors_of(schemas.ShopsProductsSchema, {"shop": "x1", "sort": "cheapest"})
    assert "query" in errors_of(schemas.ShopsProductsSchema, {"shop": "x1", "query": "x" * 101})
    assert set(refs.SHOP_SORTS.values()) == {1, 23, 2, 10, 9, 11, 8, 5, 3}


def test_shop_search():
    data = loaded(schemas.ShopsSearchSchema, {"query": "sepatu"})
    assert data == {"query": "sepatu", "page": 1, "shop_type": None, "location": None}
    data = loaded(schemas.ShopsSearchSchema, {"query": "sepatu", "shop_type": "power_shop", "location": "Bandung"})
    assert data["shop_type"] == "3" and data["location"] == "165"
    assert "shop_type" in errors_of(schemas.ShopsSearchSchema, {"query": "x", "shop_type": "gold"})
    assert "sort" in errors_of(schemas.ShopsSearchSchema, {"query": "x", "sort": "newest"})


# ---- every field documents itself --------------------------------------------------------

def test_every_field_has_a_description():
    for name in dir(schemas):
        schema = getattr(schemas, name)
        if isinstance(schema, type) and issubclass(schema, schemas.BaseSchema) and name.endswith("Schema"):
            for field_name, field in schema().fields.items():
                assert field.metadata.get("description"), f"{name}.{field_name}"


def test_params_text_is_built_as_the_site_builds_it():
    assert refs.encode_params({"q": "sepatu lari", "ob": "23", "fcity": "165,252", "sc": ""}) == \
        "fcity=165,252&ob=23&q=sepatu%20lari&sc="
