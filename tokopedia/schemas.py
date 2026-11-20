"""Marshmallow request schemas for every /tokopedia/* route.

ONE param per input (never a sibling `url` / `id` pair):

    product    a product id (100773001007) OR a tokopedia.com product link
    products   several of those, comma-separated
    shop       a shop domain (tomkinsofficial), a shop id OR a shop link
    shops      several shop ids, comma-separated
    category   a category id (1800) OR a tokopedia.com category link

The two product lists (products/search, categories/products) share `sort`
and the filters of the site's own filter panel. A list serves its first
6,000 products, 60 a page, so `page` stops at 100. Reviews come 50 a page
and stop near 10,000.
"""
from marshmallow import ValidationError, fields, pre_load, validate, validates_schema

from schema_fields import (BaseSchema, ChoiceField, CommaListField, Flag, PageField, Price, QueryField, RefField,
                           StrippedString)
from scraper_utils.schema import max_length as _max_length
from tokopedia import refs

MAX_SHOP_QUERY = 100
MAX_LOCATION_TEXT = 4000         # room for every city id of the filter


class ProductRefField(RefField):
    resolver = staticmethod(refs.resolve_product)


class BulkProductsField(RefField):
    """'100773001007, <link>, ...' -> the refs joined by commas, in order,
    repeats dropped (up to 30)."""
    resolver = staticmethod(refs.resolve_bulk_products)


class ShopRefField(RefField):
    resolver = staticmethod(refs.resolve_shop)


class BulkShopsField(RefField):
    """'6638357, 1318431' -> the ids joined by commas, repeats dropped (up to 100)."""
    resolver = staticmethod(refs.resolve_bulk_shops)


class CategoryRefField(RefField):
    resolver = staticmethod(refs.resolve_category)


class LocationField(RefField):
    """'Bandung, Jawa Tengah' or city ids -> the city ids the site's location filter sends."""
    resolver = staticmethod(refs.resolve_location)

    def __init__(self, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("load_default", None)
        kwargs.setdefault("validate", _max_length(MAX_LOCATION_TEXT))
        super().__init__(**kwargs)


class OneOfInt(fields.Integer):
    """An optional whole number out of a fixed set."""

    def __init__(self, choices, **kwargs):
        kwargs.setdefault("load_default", None)
        kwargs.setdefault("validate", validate.OneOf(
            list(choices), error="Must be one of: " + ", ".join(str(c) for c in choices) + "."))
        super().__init__(strict=False, **kwargs)


class TopicField(StrippedString):
    """A review topic key (kualitas), as the review summary lists them."""

    def __init__(self, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("load_default", None)
        super().__init__(**kwargs)

    def _deserialize(self, value, attr, data, **kwargs):
        value = super()._deserialize(value, attr, data, **kwargs)
        if value is None:
            return None
        value = value.lower()
        if len(value) > 40 or not refs.TOPIC_RE.match(value):
            raise ValidationError("A topic is one of the keys in `topics` of this endpoint's answer (kualitas, pengiriman).")
        return value


def _stars_field():
    return CommaListField(allowed=refs.REVIEW_STARS, upper=False, max_items=5, metadata={
        "description": "only reviews with these star ratings, comma-separated: 1, 2, 3, 4, 5 (1,2 = the bad ones)"})


class _Schema(BaseSchema):
    """What every /tokopedia/* schema shares."""

    @pre_load
    def empty_is_absent(self, data, **kwargs):
        """An optional param sent empty (`page=`, `cod=`: a form that sends
        every field) is the absent param. Left in, `cod=` loaded as false
        and `page=` / `min_price=` were refused as "not a valid integer" /
        "number". A required param sent empty is still refused, and so is a
        param no schema knows."""
        optional = {field.data_key or name for name, field in self.fields.items() if not field.required}
        return {key: value for key, value in data.items()
                if not (key in optional and isinstance(value, str) and not value.strip())}


class _ListingSchema(_Schema):
    """What the two product lists share."""
    page = PageField(max_page=refs.MAX_SEARCH_PAGE, metadata={
        "description": "page of results, 1 to 100: Tokopedia serves the first 6,000 products of a list, 60 a page, "
                       "and an empty page after them"})
    sort = ChoiceField(refs.SORTS, load_default=refs.SORTS["relevance"], metadata={
        "description": "relevance (default), reviews (most reviewed), newest, price_high or price_low"})
    min_price = Price(metadata={"description": "lowest price, in rupiah (100000)"})
    max_price = Price(metadata={"description": "highest price, in rupiah (200000)"})
    rating_4_up = Flag(metadata={"description": "true = only products rated 4 stars and up"})
    condition = ChoiceField(refs.CONDITIONS, metadata={"description": "new or used"})
    shop_type = ChoiceField(refs.SHOP_TYPES, metadata={
        "description": "mall (Tokopedia's official stores) or power_shop"})
    location = LocationField(metadata={
        "description": "where the seller is: the names of Tokopedia's own location filter (Bandung, DKI Jakarta, "
                       "Jawa Barat, Kab. Bogor), comma-separated, or its city ids (165)"})
    cod = Flag(metadata={"description": "true = only products that can be paid on delivery"})
    discounted = Flag(metadata={"description": "true = only discounted products"})
    stock = ChoiceField(refs.STOCK, metadata={"description": "ready (in stock now) or preorder"})
    listed_within_days = OneOfInt(refs.LISTED_WITHIN_DAYS, metadata={
        "description": "only products added in the last 7, 14, 30 or 90 days"})
    delivery = ChoiceField(refs.DELIVERY, metadata={"description": "instant or same_day delivery"})

    @validates_schema
    def _price_range(self, data, **kwargs):
        low, high = data.get("min_price"), data.get("max_price")
        if low is not None and high is not None and low > high:
            raise ValidationError("min_price is above max_price.", "min_price")


class ProductsSearchSchema(_ListingSchema):
    query = QueryField(metadata={"description": "what to search for (sepatu, iphone 15, rak buku)"})
    category = CategoryRefField(required=False, load_default=None, metadata={
        "description": "search inside one category: a category id (1759) or a tokopedia.com category link"})


class CategoriesProductsSchema(_ListingSchema):
    category = CategoryRefField(metadata={
        "description": "a category id (1800) or a tokopedia.com category link "
                       "(https://www.tokopedia.com/p/fashion-pria/sepatu-pria); /tokopedia/categories/list has both"})


class CategoriesListSchema(_Schema):
    """No params: the whole tree comes in one answer."""


class ProductSchema(_Schema):
    product = ProductRefField(metadata={
        "description": "a Tokopedia product id (100773001007) or a tokopedia.com product link"})


class ProductsReviewsSchema(ProductSchema):
    page = PageField(max_page=refs.MAX_PRODUCT_REVIEWS_PAGE, metadata={
        "description": "page of reviews, 1 to 199: 50 a page; Tokopedia serves about the first 10,000 of a product"})
    sort = ChoiceField(refs.REVIEW_SORTS, load_default=refs.REVIEW_SORTS["helpful"], metadata={
        "description": "helpful (default), newest, rating_high or rating_low"})
    stars = _stars_field()
    with_media = Flag(metadata={"description": "true = only reviews with a photo or a video"})
    topic = TopicField(metadata={
        "description": "only reviews about one topic: a key from `topics` in this endpoint's answer (kualitas, pengiriman)"})


class ProductsBulkSchema(_Schema):
    products = BulkProductsField(metadata={
        "description": "up to 30 product ids or tokopedia.com product links, comma-separated"})


class ShopSchema(_Schema):
    shop = ShopRefField(metadata={
        "description": "a Tokopedia shop domain (tomkinsofficial), a shop id (6638357) or a tokopedia.com shop link"})


class ShopsProductsSchema(ShopSchema):
    page = PageField(max_page=refs.MAX_SHOP_PRODUCTS_PAGE, metadata={
        "description": "page of products, 80 a page; the answer says whether a next page exists"})
    sort = ChoiceField(refs.SHOP_SORTS, load_default=refs.SHOP_SORTS["default"], metadata={
        "description": "default (the shop page's own order), relevance, newest, price_high, price_low, most_reviewed, "
                       "best_selling, most_viewed or recently_updated"})
    query = StrippedString(required=False, load_default=None, validate=_max_length(MAX_SHOP_QUERY), metadata={
        "description": "search inside the shop (rak, sandal)"})


class ShopsReviewsSchema(ShopSchema):
    page = PageField(max_page=refs.MAX_SHOP_REVIEWS_PAGE, metadata={
        "description": "page of reviews, 1 to 200: 50 a page; Tokopedia serves the first 10,000 of a shop"})
    sort = ChoiceField(refs.REVIEW_SORTS, load_default=refs.REVIEW_SORTS["newest"], metadata={
        "description": "newest (default), helpful, rating_high or rating_low"})
    stars = _stars_field()
    with_media = Flag(metadata={"description": "true = only reviews with a photo or a video"})


class ShopsSearchSchema(_Schema):
    query = QueryField(metadata={"description": "what to search shops for (sepatu, elektronik)"})
    page = PageField(max_page=refs.MAX_SHOP_SEARCH_PAGE, metadata={"description": "page of shops, 60 a page"})
    shop_type = ChoiceField(refs.SHOP_TYPES, metadata={
        "description": "mall (Tokopedia's official stores) or power_shop"})
    location = LocationField(metadata={
        "description": "where the shop is: the names of Tokopedia's own location filter (Bandung, DKI Jakarta, "
                       "Jawa Barat), comma-separated, or its city ids (165)"})


class ShopsBulkSchema(_Schema):
    shops = BulkShopsField(metadata={
        "description": "up to 100 shop ids, comma-separated (6638357,1318431); /tokopedia/shops/details reads a "
                       "shop by its domain or link and returns the id"})
