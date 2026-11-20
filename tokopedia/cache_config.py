"""Cache TTL per /tokopedia/* surface (cache.py, keyed on the validated
params). Tokopedia reprices through the day (flash sales, campaign
prices), so nothing that carries a price is kept for long.
"""
from datetime import timedelta

# products/search, categories/products: prices and campaign labels change
# through the day; the order of a list far less
LISTING_CACHE = timedelta(minutes=30)
# products/details: price, stock and the shipping estimate move, the
# description and the specifications do not
PRODUCT_CACHE = timedelta(hours=1)
# products/bulk: the price-watch call, asked again and again for the same ids
BULK_CACHE = timedelta(minutes=15)
# the id behind a product link: it never changes
PRODUCT_ID_CACHE = timedelta(days=7)
# products/reviews, shops/reviews: a busy product gains a few reviews a day
REVIEWS_CACHE = timedelta(hours=6)
# shops/details, shops/bulk: followers and sold counts creep, the rest is static
SHOP_CACHE = timedelta(hours=6)
# the shop record behind every `shop` param (its id, name and link)
SHOP_CORE_CACHE = timedelta(hours=24)
# shops/products: prices again
SHOP_PRODUCTS_CACHE = timedelta(minutes=30)
# shops/search: shops open and close slowly
SHOP_SEARCH_CACHE = timedelta(hours=6)
# categories/list: the tree moves with the site's merchandising
CATEGORIES_CACHE = timedelta(hours=24)
# how long a process keeps its own lookup table of the category tree (seconds)
CATEGORY_INDEX_SECONDS = 3600
