import json
from decimal import Decimal, InvalidOperation
from html import unescape

from django.conf import settings
from django.utils.html import strip_tags
from django.utils.text import Truncator


def clean_text(value, limit=None):
    text = strip_tags(str(value or ""))
    text = unescape(text)
    text = " ".join(text.split())
    if limit:
        text = Truncator(text).chars(limit, truncate="...")
    return text


def get_site_url(request=None):
    if request:
        scheme = "https" if request.is_secure() else request.scheme
        return f"{scheme}://{request.get_host()}".rstrip("/")
    return getattr(settings, "SITE_URL", "https://arolana.com").rstrip("/")


def absolute_url(value, request=None):
    if not value:
        return ""

    value = str(value).strip()

    if value.startswith(("http://", "https://")):
        return value

    site_url = get_site_url(request)

    if not value.startswith("/"):
        value = "/" + value

    return f"{site_url}{value}"


def get_product_url(product, request=None):
    try:
        return absolute_url(product.get_absolute_url(), request)
    except Exception:
        return ""


def get_image_url(image_field, request=None):
    if not image_field:
        return ""
    try:
        return absolute_url(image_field.url, request)
    except Exception:
        return ""


def product_image_alt(product, image=None):
    brand = getattr(getattr(product, "brand", None), "name", "") or ""
    category = getattr(getattr(product, "category", None), "name", "") or ""
    sku = getattr(product, "sku", "") or ""
    parts = [brand, getattr(product, "name", ""), category]
    alt = " ".join(clean_text(p) for p in parts if p)
    if sku:
        alt = f"{alt} SKU {sku}"
    return clean_text(alt, 160) or "Arolana product image"


def seo_title_for_product(product):
    if getattr(product, "meta_title", ""):
        return clean_text(product.meta_title, 65)

    brand = getattr(getattr(product, "brand", None), "name", "") or ""
    category = getattr(getattr(product, "category", None), "name", "") or ""
    bits = [getattr(product, "name", "Product")]

    if brand:
        bits.append(brand)
    elif category:
        bits.append(category)

    bits.append("Arolana")
    return clean_text(" | ".join(bits), 70)


def seo_description_for_product(product):
    if getattr(product, "meta_description", ""):
        return clean_text(product.meta_description, 160)

    name = clean_text(getattr(product, "name", "this product"))
    brand = getattr(getattr(product, "brand", None), "name", "") or ""
    category = getattr(getattr(product, "category", None), "name", "") or ""

    description = (
        f"Buy {name}"
        f"{' by ' + brand if brand else ''}"
        f"{' in ' + category if category else ''} on Arolana. "
        "View specifications, availability, warranty, shipping information, and order securely from verified vendors."
    )
    return clean_text(description, 160)


def canonical_url_for_product(product, request=None):
    canonical = getattr(product, "canonical_url", "") or ""
    if canonical:
        return absolute_url(canonical, request)
    return get_product_url(product, request)


def product_images(product, request=None):
    images = []

    main_image = get_image_url(getattr(product, "main_image", None), request)
    if main_image:
        images.append(main_image)

    try:
        for img in product.images.filter(is_active=True).order_by("-is_main", "order", "id")[:10]:
            url = get_image_url(getattr(img, "image", None), request)
            if url and url not in images:
                images.append(url)
    except Exception:
        pass

    try:
        for variant in product.variants.filter(is_active=True)[:10]:
            url = get_image_url(getattr(variant, "image", None), request)
            if url and url not in images:
                images.append(url)
    except Exception:
        pass

    return images


def price_decimal(value):
    try:
        amount = Decimal(str(value or "0").replace(",", "")).quantize(Decimal("0.01"))
        return amount
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0.00")


def product_availability_url(product):
    stock = int(getattr(product, "stock_quantity", 0) or 0)
    is_in_stock = bool(getattr(product, "is_in_stock", False)) or stock > 0
    return "https://schema.org/InStock" if is_in_stock else "https://schema.org/OutOfStock"


def product_condition_url(product):
    condition = clean_text(getattr(product, "condition", "")).lower()
    if "used" in condition:
        return "https://schema.org/UsedCondition"
    if "refurb" in condition:
        return "https://schema.org/RefurbishedCondition"
    if "damaged" in condition:
        return "https://schema.org/DamagedCondition"
    return "https://schema.org/NewCondition"


def product_reviews_schema(product, limit=5):
    reviews = []

    try:
        qs = (
            product.reviews
            .filter(is_active=True)
            .select_related("user")
            .order_by("-created_at")[:limit]
        )

        for review in qs:
            rating = getattr(review, "rating", None)
            if not rating:
                continue

            user = getattr(review, "user", None)
            author_name = clean_text(
                getattr(user, "get_full_name", lambda: "")()
                or getattr(user, "username", "")
                or "Arolana customer"
            )

            reviews.append({
                "@type": "Review",
                "author": {
                    "@type": "Person",
                    "name": author_name,
                },
                "datePublished": getattr(review, "created_at", None).date().isoformat()
                if getattr(review, "created_at", None) else "",
                "reviewBody": clean_text(getattr(review, "review", "") or getattr(review, "comment", ""), 500),
                "name": clean_text(getattr(review, "title", "") or "Customer review", 120),
                "reviewRating": {
                    "@type": "Rating",
                    "ratingValue": str(rating),
                    "bestRating": "5",
                    "worstRating": "1",
                },
            })
    except Exception:
        pass

    return reviews


def product_schema(product, request=None, currency_code="NGN"):
    images = product_images(product, request)
    brand = getattr(getattr(product, "brand", None), "name", "") or "Arolana"
    category = getattr(getattr(product, "category", None), "name", "") or ""
    url = canonical_url_for_product(product, request)

    sku = clean_text(getattr(product, "sku", ""))
    manufacturer_sku = clean_text(getattr(product, "manufacturer_sku", ""))

    schema = {
        "@context": "https://schema.org/",
        "@type": "Product",
        "name": clean_text(getattr(product, "name", "")),
        "description": seo_description_for_product(product),
        "sku": sku,
        "mpn": manufacturer_sku or sku,
        "brand": {
            "@type": "Brand",
            "name": clean_text(brand),
        },
        "category": clean_text(category),
        "image": images,
        "url": url,
        "offers": {
            "@type": "Offer",
            "url": url,
            "priceCurrency": currency_code,
            "price": str(price_decimal(getattr(product, "price", 0))),
            "availability": product_availability_url(product),
            "itemCondition": product_condition_url(product),
            "seller": {
                "@type": "Organization",
                "name": "Arolana",
                "url": get_site_url(request),
            },
        },
    }

    rating_value = price_decimal(getattr(product, "rating_avg", 0))
    rating_count = int(getattr(product, "rating_count", 0) or 0)

    if rating_value > 0 and rating_count > 0:
        schema["aggregateRating"] = {
            "@type": "AggregateRating",
            "ratingValue": str(rating_value),
            "reviewCount": str(rating_count),
            "bestRating": "5",
            "worstRating": "1",
        }

    reviews = product_reviews_schema(product)
    if reviews:
        schema["review"] = reviews

    return schema


def product_schema_json(product, request=None, currency_code="NGN"):
    return json.dumps(
        product_schema(product, request, currency_code),
        ensure_ascii=False,
        separators=(",", ":"),
    )


def merchant_metadata(product, request=None, currency_code="NGN"):
    images = product_images(product, request)
    price = price_decimal(getattr(product, "price", 0))

    return {
        "id": clean_text(getattr(product, "sku", "") or getattr(product, "id", "")),
        "title": seo_title_for_product(product),
        "description": seo_description_for_product(product),
        "link": canonical_url_for_product(product, request),
        "image_link": images[0] if images else "",
        "availability": "in stock" if product_availability_url(product).endswith("InStock") else "out of stock",
        "price": f"{price} {currency_code}",
        "brand": clean_text(getattr(getattr(product, "brand", None), "name", "") or "Arolana"),
        "condition": "new",
        "google_product_category": clean_text(getattr(getattr(product, "category", None), "name", "")),
    }


def category_seo_title(category):
    if getattr(category, "meta_title", ""):
        return clean_text(category.meta_title, 65)
    return clean_text(f"{getattr(category, 'name', 'Products')} | Buy Online in Nigeria | Arolana", 70)


def category_seo_description(category):
    if getattr(category, "meta_description", ""):
        return clean_text(category.meta_description, 160)

    description = getattr(category, "description", "") or f"Shop {getattr(category, 'name', 'products')} on Arolana."
    return clean_text(description, 160)