import json
from decimal import Decimal
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


def absolute_url(path_or_url, request=None):
    if not path_or_url:
        return ""
    value = str(path_or_url)
    if value.startswith("http://") or value.startswith("https://"):
        return value
    site_url = get_site_url(request)
    if not value.startswith("/"):
        value = f"/{value}"
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
    alt = " ".join([clean_text(p) for p in parts if p])
    if sku:
        alt = f"{alt} SKU {sku}"
    return alt[:160] or "Arolana product image"


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
    bits.extend(["Buy Online in Nigeria", "Arolana"])
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
        "Compare prices, view specifications, check availability, read reviews, and order securely from verified vendors."
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
        for img in product.images.filter(is_active=True).order_by("-is_main", "order", "id")[:8]:
            url = get_image_url(img.image, request)
            if url and url not in images:
                images.append(url)
    except Exception:
        pass
    return images


def price_decimal(value):
    try:
        return Decimal(str(value or "0"))
    except Exception:
        return Decimal("0")


def product_availability_url(product):
    stock = getattr(product, "stock_quantity", 0) or 0
    is_in_stock = getattr(product, "is_in_stock", False) or stock > 0
    return "https://schema.org/InStock" if is_in_stock else "https://schema.org/OutOfStock"


def product_schema(product, request=None, currency_code="NGN"):
    images = product_images(product, request)
    brand = getattr(getattr(product, "brand", None), "name", "") or "Arolana"
    url = canonical_url_for_product(product, request)
    schema = {
        "@context": "https://schema.org/",
        "@type": "Product",
        "name": clean_text(getattr(product, "name", "")),
        "description": seo_description_for_product(product),
        "sku": clean_text(getattr(product, "sku", "")),
        "mpn": clean_text(getattr(product, "sku", "")),
        "brand": {"@type": "Brand", "name": clean_text(brand)},
        "image": images,
        "url": url,
        "offers": {
            "@type": "Offer",
            "url": url,
            "priceCurrency": currency_code,
            "price": str(price_decimal(getattr(product, "price", 0))),
            "availability": product_availability_url(product),
            "itemCondition": "https://schema.org/NewCondition",
            "seller": {"@type": "Organization", "name": "Arolana"},
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
    return schema


def product_schema_json(product, request=None, currency_code="NGN"):
    return json.dumps(product_schema(product, request, currency_code), ensure_ascii=False)


def merchant_metadata(product, request=None, currency_code="NGN"):
    images = product_images(product, request)
    return {
        "id": clean_text(getattr(product, "sku", "") or getattr(product, "id", "")),
        "title": seo_title_for_product(product),
        "description": seo_description_for_product(product),
        "link": canonical_url_for_product(product, request),
        "image_link": images[0] if images else "",
        "availability": "in stock" if product_availability_url(product).endswith("InStock") else "out of stock",
        "price": f"{price_decimal(getattr(product, 'price', 0))} {currency_code}",
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
