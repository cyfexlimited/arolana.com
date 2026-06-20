import json
import re

from django import template
from django.conf import settings
from django.utils.html import strip_tags
from django.utils.safestring import mark_safe


register = template.Library()


def _clean_text(value, max_chars=None):
    text = strip_tags(str(value or ""))
    text = re.sub(r"\s+", " ", text).strip()

    if max_chars and len(text) > max_chars:
        return text[: max_chars - 1].rsplit(" ", 1)[0].rstrip(".,;:") + "…"

    return text


def _name(value):
    if not value:
        return ""
    return _clean_text(getattr(value, "name", value), 120)


def _absolute_url(request, url):
    url = str(url or "").strip()

    if not url:
        return ""

    if url.startswith("http://") or url.startswith("https://"):
        return url

    if request:
        try:
            return request.build_absolute_uri(url)
        except Exception:
            pass

    site_url = str(getattr(settings, "SITE_URL", "https://arolana.com") or "https://arolana.com").rstrip("/")
    return f"{site_url}/{url.lstrip('/')}"


def _product_url(product, request=None):
    try:
        url = product.get_absolute_url()
    except Exception:
        url = ""
    return _absolute_url(request, url)


def _answered_questions(product, limit=6):
    if not product:
        return []

    manager = getattr(product, "questions", None)
    if not manager:
        return []

    try:
        qs = (
            manager.filter(is_public=True)
            .exclude(answer__isnull=True)
            .exclude(answer__exact="")
            .order_by("-answered_at", "-created_at")
        )
    except Exception:
        try:
            qs = manager.all()
        except Exception:
            return []

    items = []

    try:
        iterable = qs[:limit]
    except Exception:
        iterable = qs

    for item in iterable:
        question = _clean_text(getattr(item, "question", ""), 180)
        answer = _clean_text(getattr(item, "answer", ""), 500)

        if question and answer:
            items.append({"question": question, "answer": answer})

        if len(items) >= limit:
            break

    return items


def _extract_spec_points(product, limit=6):
    raw = _clean_text(getattr(product, "specifications", ""), 1200)

    if not raw:
        return []

    parts = re.split(r"(?:\s{2,}| • | \| |\n|;)", raw)
    points = []

    for part in parts:
        item = _clean_text(part, 120)

        if len(item) < 8:
            continue

        if item.lower() in {"specifications", "description", "features"}:
            continue

        if item not in points:
            points.append(item)

        if len(points) >= limit:
            break

    return points


@register.simple_tag
def ai_product_summary(product):
    if not product:
        return {}

    brand = _name(getattr(product, "brand", ""))
    category = _name(getattr(product, "category", ""))
    name = _clean_text(getattr(product, "name", ""), 180)

    short_answer = (
        _clean_text(getattr(product, "meta_description", ""), 280)
        or _clean_text(getattr(product, "description", ""), 280)
        or name
    )

    best_for = []

    if category:
        best_for.append(f"Customers shopping for {category.lower()}.")

    if brand:
        best_for.append(f"Buyers who prefer {brand} products.")

    if getattr(product, "stock_quantity", None) is not None:
        best_for.append("Customers who want to confirm availability before checkout.")

    best_for.append("Customers who need delivery, payment, and order support from Arolana.")

    key_facts = []

    sku = _clean_text(getattr(product, "sku", ""), 80)
    manufacturer_sku = _clean_text(getattr(product, "manufacturer_sku", ""), 80)
    condition = _clean_text(getattr(product, "condition", ""), 80)
    warranty_years = getattr(product, "warranty_years", None)

    if brand:
        key_facts.append(("Brand", brand))
    if category:
        key_facts.append(("Category", category))
    if sku:
        key_facts.append(("Arolana SKU", sku))
    if manufacturer_sku:
        key_facts.append(("Manufacturer SKU", manufacturer_sku))
    if condition:
        key_facts.append(("Condition", condition.replace("_", " ").title()))

    try:
        warranty_number = int(warranty_years or 0)
    except (TypeError, ValueError):
        warranty_number = 0

    if warranty_number:
        key_facts.append(("Warranty", f"{warranty_number} year{'s' if warranty_number != 1 else ''}"))

    shipping_note = "Delivery options and cost are confirmed at checkout based on location, package size, and provider availability."

    try:
        shipping = getattr(product, "shipping_info", None)
    except Exception:
        shipping = None

    if shipping:
        min_days = getattr(shipping, "estimated_delivery_days_min", None)
        max_days = getattr(shipping, "estimated_delivery_days_max", None)

        if min_days and max_days:
            shipping_note = f"Estimated delivery is usually {min_days}–{max_days} days, subject to location and provider availability."

    return {
        "name": name,
        "short_answer": short_answer,
        "best_for": best_for[:4],
        "key_facts": key_facts[:8],
        "spec_points": _extract_spec_points(product),
        "shipping_note": shipping_note,
        "support_note": "Arolana support can help with product guidance, checkout, payment confirmation, delivery updates, and order questions.",
        "faqs": _answered_questions(product, limit=4),
    }


@register.simple_tag(takes_context=True)
def product_faq_schema_json(context, product):
    request = context.get("request")
    faqs = _answered_questions(product, limit=6)

    if not faqs:
        return ""

    schema = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": item["question"],
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": item["answer"],
                },
            }
            for item in faqs
        ],
    }

    url = _product_url(product, request=request)

    if url:
        schema["url"] = url

    return mark_safe(json.dumps(schema, ensure_ascii=False, separators=(",", ":")))
