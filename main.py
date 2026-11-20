"""Use the scraper straight from Python, no server needed.

    python main.py

Each call validates its params with the same schema the API uses (so the
defaults apply) and returns the same JSON the API does, except that a list
keeps its `pagination` block instead of next / previous links. The results
are written to output/*.json.
"""
import json
import os

from tokopedia import api, schemas
from schema_fields import load_query

os.makedirs("output", exist_ok=True)


def run(schema_cls, impl, **params):
    data, error = load_query(schema_cls, {k: str(v) for k, v in params.items()})
    if error:
        raise ValueError(error)
    return impl(**data)


def save(name, data):
    path = os.path.join("output", name)
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"saved {path}")


if __name__ == "__main__":
    # the full product (an id or any tokopedia.com product link): price and discount, stock,
    # variants, specs, images, rating, sold count, shop and shipping
    save("products_details.json", run(schemas.ProductSchema, api.products_details, product='100000615294'))

    # 60 products a page for a keyword, with sort and the filters of Tokopedia's own filter panel
    save("products_search.json", run(schemas.ProductsSearchSchema, api.products_search, query='necklace'))

    # 50 reviews a page: rating, text, variant, photos, likes and seller reply, plus the star
    # breakdown and the review topics
    save("products_reviews.json", run(schemas.ProductsReviewsSchema, api.products_reviews, product='100000615294'))
