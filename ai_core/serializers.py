from django.utils.html import strip_tags

from .redaction import redact_mapping


def _text(value, limit=1200):
    return " ".join(strip_tags(str(value or "")).split())[:limit]


def _money(value):
    return str(value or "") if value not in (None, "") else ""


def product_safe_payload(product):
    category = getattr(product, "category", None)
    brand = getattr(product, "brand", None)
    return redact_mapping({
        "type": "product",
        "id": product.id,
        "name": _text(getattr(product, "name", ""), 240),
        "slug": getattr(product, "slug", ""),
        "sku": getattr(product, "sku", ""),
        "manufacturer_sku": getattr(product, "manufacturer_sku", ""),
        "category": _text(getattr(category, "name", ""), 160) if category else "",
        "brand": _text(getattr(brand, "name", ""), 160) if brand else "",
        "price": _money(getattr(product, "price", "")),
        "compare_price": _money(getattr(product, "compare_price", "")),
        "description": _text(getattr(product, "description", ""), 1800),
        "specifications": _text(getattr(product, "specifications", ""), 2200),
        "stock_quantity": getattr(product, "stock_quantity", 0),
        "is_in_stock": bool(getattr(product, "is_in_stock", False)),
        "rating_avg": _money(getattr(product, "rating_avg", "")),
        "rating_count": getattr(product, "rating_count", 0),
        "warranty_years": getattr(product, "warranty_years", None),
        "lead_time_days": getattr(product, "lead_time_days", None),
    })


def vendor_safe_payload(vendor):
    return redact_mapping({
        "type": "vendor",
        "id": vendor.id,
        "store_name": _text(getattr(vendor, "store_name", ""), 240),
        "vendor_type": getattr(vendor, "vendor_type", ""),
        "description": _text(getattr(vendor, "description", ""), 1600),
        "city": getattr(vendor, "city", ""),
        "state": getattr(vendor, "state", ""),
        "country": getattr(vendor, "country", ""),
        "is_verified": bool(getattr(vendor, "is_verified", False)),
        "approval_status": getattr(vendor, "approval_status", ""),
        "subscription_tier": getattr(vendor, "subscription_tier", ""),
        "rating_avg": _money(getattr(vendor, "rating_avg", "")),
        "total_sales": getattr(vendor, "total_sales", 0),
        "total_reviews": getattr(vendor, "total_reviews", 0),
        "fulfillment_rate": _money(getattr(vendor, "fulfillment_rate", "")),
        "return_rate": _money(getattr(vendor, "return_rate", "")),
    })


def provider_safe_payload(provider):
    return redact_mapping({
        "type": "service_provider",
        "id": provider.id,
        "business_name": _text(getattr(provider, "business_name", ""), 240),
        "provider_type": getattr(provider, "provider_type", ""),
        "country": getattr(provider, "country", ""),
        "state": getattr(provider, "state", ""),
        "city": getattr(provider, "city", ""),
        "service_coverage": _text(getattr(provider, "service_coverage", ""), 500),
        "description": _text(getattr(provider, "description", ""), 1600),
        "years_of_experience": getattr(provider, "years_of_experience", 0),
        "verification_status": getattr(provider, "verification_status", ""),
        "kyc_status": getattr(provider, "kyc_status", ""),
        "subscription_plan": getattr(provider, "subscription_plan", ""),
        "subscription_status": getattr(provider, "subscription_status", ""),
        "availability_status": getattr(provider, "availability_status", ""),
        "average_rating": _money(getattr(provider, "average_rating", "")),
        "total_reviews": getattr(provider, "total_reviews", 0),
        "total_completed_jobs": getattr(provider, "total_completed_jobs", 0),
    })


def order_safe_payload(order):
    return redact_mapping({
        "type": "order",
        "id": order.id,
        "order_number": getattr(order, "order_number", ""),
        "status": getattr(order, "status", ""),
        "payment_status": getattr(order, "payment_status", ""),
        "subtotal": _money(getattr(order, "subtotal", "")),
        "shipping_cost": _money(getattr(order, "shipping_cost", "")),
        "tax": _money(getattr(order, "tax", "")),
        "total": _money(getattr(order, "total", "")),
        "created_at": getattr(getattr(order, "created_at", None), "isoformat", lambda: "")(),
    })


SAFE_SERIALIZERS = {
    "products.Product": product_safe_payload,
    "vendors.VendorProfile": vendor_safe_payload,
    "installers.ServiceProviderProfile": provider_safe_payload,
    "orders.Order": order_safe_payload,
}


def serialize_ai_safe(obj):
    label = obj._meta.label
    serializer = SAFE_SERIALIZERS.get(label)
    if not serializer:
        raise PermissionError(f"No AI-safe serializer registered for {label}.")
    return serializer(obj)
