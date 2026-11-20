# 🚀 Tokopedia Scraper

Tokopedia Scraper is a **free and open-source** scraper that gets you **unlimited** detailed Tokopedia data for free.

## ✨ What Can I Get?

- 🛒 **Full details on 160M+ products** — price & discount, stock, every variant, specs, images, rating, sold count, shop & shipping
- ⭐ **Up to 10,000 reviews per product or shop** — rating, text, variant bought, photos & videos, likes, seller replies, star breakdown & review topics
- 🏪 **Profiles of 14M+ sellers** — rating with star breakdown, followers, products sold, transactions, location & every product they sell
- 🗂️ **All 3,312 categories, searchable with 12 filters** — the full category tree, keyword search, price, rating, condition, official-store, location & delivery filters

## 🛒 Example: A Full Tokopedia Product

```json
{
  "id": "100000615294",
  "name": "Tymbi&Co - Thin Bubble Necklace | Kalung Huruf Anti Karat | Kalung Inisial Huruf | Letter Necklace (BELI 3 GRATIS 1) (BELI 3 GRATIS 1 GIFT) - A, GOLD",
  "link": "https://www.tokopedia.com/tymbico/tymbi-co-thin-bubble-necklace-kalung-huruf-anti-karat-kalung-inisial-huruf-letter-necklace-1730420702723278474",
  "description": "Material : Titanium steel (Anti Karat)\n\nSize : 1mm, 45cm…",
  "condition": "new",
  "category": { "id": "1925", "name": "Kalung Wanita", "link": "https://www.tokopedia.com/p/fashion-wanita/perhiasan-wanita/kalung-wanita" },
  "images_count": 29,
  "price": { "amount": 85000, "currency": "IDR", "original_amount": 89000, "discount_percent": 4 },
  "campaign": { "name": "Kejar Diskon", "discount_percent": 4, "sold_percent": 99, "ends_at": "2026-12-31T16:59:59Z" },
  "stock": 451,
  "weight": { "value": 0.005, "unit": "kilogram", "grams": 5 },
  "variants": {
    "total_stock": 2928,
    "options": [{ "name": "huruf", "values": [{ "value": "A", "stock": 612 }, { "value": "B", "stock": 32 }] }]
  },
  "rating": 4.9,
  "reviews_count": 13264,
  "sold_count": 80596,
  "wishlist_count": 42,
  "is_official_store": true,
  "shop": { "id": "7494083687829767818", "name": "Tymbi&Co", "domain": "tymbico", "location": "Kota Administrasi Jakarta Barat", "tier": "mall", "rating": 4.9 },
  "shipping": { "title": "Ongkir Rp7.500", "cheapest_amount": 7500, "has_free_shipping": true, "is_cod": true }
}
```

*Trimmed for readability.*

## 🚀 Unlimited Free Tokopedia Data — Get It in 60 Seconds

1️⃣ Clone and install:
```bash
git clone https://github.com/omkarcloud/tokopedia-scraper
cd tokopedia-scraper
python -m pip install -r requirements.txt
```

2️⃣ Start the API:
```bash
python run.py
```

Your own connection is all Tokopedia needs: no browser, no proxy. Every call is plain HTTP to the same data calls tokopedia.com's own pages make.

3️⃣ Get your first data:
```bash
curl "http://localhost:8000/products/details?product=100000615294"
```

```json
{
  "id": "100000615294",
  "parent_id": "100000615293",
  "name": "Tymbi&Co - Thin Bubble Necklace | Kalung Huruf Anti Karat | Kalung Inisial Huruf | Letter Necklace (BELI 3 GRATIS 1) (BELI 3 GRATIS 1 GIFT) - A, GOLD",
  "link": "https://www.tokopedia.com/tymbico/tymbi-co-thin-bubble-necklace-kalung-huruf-anti-karat-kalung-inisial-huruf-letter-necklace-1730420702723278474",
  "condition": "new",
  "status": "active",
  "category": { "id": "1925", "name": "Kalung Wanita" },
  "images_count": 29,
  "price": { "amount": 85000, "currency": "IDR", "original_amount": 89000, "discount_percent": 4 },
  "stock": 451,
  "min_order": 1,
  "max_order": 451,
  "rating": 4.9,
  "reviews_count": 13264,
  "sold_count": 80596,
  "sold_label": "50 rb+",
  "is_official_store": true,
  "shop": { "id": "7494083687829767818", "name": "Tymbi&Co", "domain": "tymbico", "tier": "mall" },
  "shipping": { "title": "Ongkir Rp7.500", "cheapest_amount": 7500, "has_free_shipping": true }
}
```

All 11 endpoints are now live at `http://localhost:8000`.

## 📚 Endpoints

11 endpoints cover everything you need.

| Endpoint | Path | Returns |
|---|---|---|
| Product Details | `/products/details` | Everything on a product page in a single call |
| Search Products | `/products/search` | 60 products per page with 5 sort orders and 12 filters |
| Product Reviews | `/products/reviews` | 50 reviews per page with photos, variants and seller replies |
| Bulk Products | `/products/bulk` | Up to 30 full products in one call |
| Categories | `/categories/list` | The full category tree with every id and link |
| Category Products | `/categories/products` | Any category's products with 5 sort orders and 11 filters |
| Search Shops | `/shops/search` | Shops for any brand or keyword, with badges and top products |
| Shop Details | `/shops/details` | A shop's rating, followers, sales, transactions and location |
| Shop Products / Reviews | `/shops/products`, `/shops/reviews` | Everything a shop sells, and what its buyers say |
| Bulk Shops | `/shops/bulk` | Up to 100 shops in one call |

## 🔍 Exploring Parameters

The same API is published on RapidAPI, and its playground is the easiest place to try parameters and see raw responses. Once a request looks right, run it locally for **unlimited free** data.

1. [Subscribe to the free plan](https://rapidapi.com/OmkarCloud/api/best-tokopedia-scraper-free-1000-calls/pricing) — 1,000 calls/month, no credit card.
2. [Try the endpoints in the playground](https://rapidapi.com/OmkarCloud/api/best-tokopedia-scraper-free-1000-calls/playground) — every param is pre-filled, so you see real data in one click.
3. Copy the generated code and replace `https://best-tokopedia-scraper-free-1000-calls.p.rapidapi.com` with `http://localhost:8000`. It will now run against your local API.

```python
import requests

# generated by the playground, host swapped for the local API
response = requests.get(
    "http://localhost:8000/products/details",
    params={"product": "100000615294"},
)
print(response.json())
```

## 💬 Have Questions? We Have Answers.

You're a developer — we know how hard completing a project can be. So we offer full support: just message us and we'll reply ✅ with a solution within 1 working day.

[![Message Us on WhatsApp about Tokopedia Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/whatsapp-us.png)](https://www.omkar.cloud/l/tokopedia-scraper-github-whatsapp)

[![Ask Us by Email about Tokopedia Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/ask-on-email.png)](mailto:happy.to.help@omkar.cloud?subject=Help%20with%20Tokopedia%20Scraper%20API&body=I%20need%20help%20using%20the%20Tokopedia%20Scraper%20API.)

## ⚡ Popular Scrapers by Omkar Cloud

- [**Google Maps Scraper (3,100+ GitHub Stars)**](https://github.com/omkarcloud/google-maps-scraper) — type "dentists in New York", get every business as a ready-to-call lead list: phones, emails, websites & reviews. Up to 100K free leads/month.
- [**G2 Scraper**](https://www.omkar.cloud/tools/g2-scraper) — G2 product details, ratings & AI-found contacts
- [**Website Email Contact Scraper**](https://www.omkar.cloud/tools/website-email-contact-scraper) — emails, phones & socials from any website
- [**AliExpress Scraper**](https://www.omkar.cloud/tools/aliexpress-scraper-api) — live product details, SKU variants, stock & shipping
- [**Booking Scraper**](https://www.omkar.cloud/tools/booking-scraper) — Booking.com hotels: prices, ratings, rooms & amenities
- [**Etsy Scraper**](https://www.omkar.cloud/tools/etsy-scraper) — Etsy products: prices, discounts, shops & variations

## ⭐ Love It? [Star It ⭐!](https://github.com/omkarcloud/tokopedia-scraper)

Star the repo ⭐ and become my star hero!

It's just 1 click, but it means the world to me.

[![Star us on GitHub](https://raw.githubusercontent.com/omkarcloud/google-maps-scraper/master/screenshots/star-us.png)](https://github.com/omkarcloud/tokopedia-scraper)
