import json
import os
import re

from django.conf import settings
from django.db.models import Q
from django.utils.html import strip_tags

from products.models import Product


MISSING_SPEC_MESSAGE = (
    "I don’t have that specification listed yet. "
    "Let me connect you with Arolana support."
)
PRODUCT_QUESTION_TERMS = {
    "accessories", "accessory", "available", "brand", "buy", "compatible",
    "compatibility", "compare", "cost", "delivery", "description", "features",
    "good for", "image", "images", "in stock", "manufacturer", "price",
    "product", "rating", "ratings", "recommend", "review", "reviews", "spec",
    "specification", "specifications", "stock", "video", "videos", "warranty",
}
SPEC_ALIASES = {
    "brightness": ("brightness", "lumen", "lumens", "ansi"),
    "lumens": ("lumen", "lumens", "ansi", "brightness"),
    "resolution": ("resolution", "1080p", "full hd", "4k", "uhd", "720p"),
    "throw distance": ("throw distance", "throw ratio", "projection distance"),
    "compatibility": ("compatible", "compatibility", "supports", "works with"),
    "warranty": ("warranty", "guarantee", "coverage"),
    "delivery": ("delivery", "shipping", "dispatch", "lead time"),
    "stock": ("stock", "availability", "available"),
    "price": ("price", "cost", "amount"),
    "weight": ("weight", "kg", "kilogram", "lbs", "pound"),
    "dimensions": ("dimension", "dimensions", "size", "length", "width", "height"),
}


def _clean(value, limit=3500):
    return re.sub(r"\s+", " ", strip_tags(str(value or ""))).strip()[:limit]


def _is_product_question(message, conversation=None):
    text = str(message or "").lower()
    return bool(getattr(conversation, "product_id", None)) or any(term in text for term in PRODUCT_QUESTION_TERMS)


def _search_terms(message):
    text = re.sub(r"[^a-z0-9\s-]", " ", str(message or "").lower())
    stop = {
        "a", "about", "and", "are", "can", "do", "does", "for", "good", "how",
        "i", "is", "it", "me", "of", "on", "please", "show", "tell", "the",
        "this", "to", "what", "which", "with", "would", "you",
    } | PRODUCT_QUESTION_TERMS
    return [word for word in text.split() if len(word) > 2 and word not in stop][:10]


def find_products(message, conversation=None, limit=4):
    queryset = Product.objects.filter(
        is_active=True,
        approval_status="approved",
    ).select_related(
        "category", "brand", "vendor", "shipping_info", "manufacturer_warranty",
    ).prefetch_related(
        "images", "additional_videos", "reviews", "questions",
        "product_accessories__accessory", "manufacturer_links__manufacturer",
    )
    attached = getattr(conversation, "product", None)
    if attached and attached.is_active and attached.approval_status == "approved":
        first = queryset.filter(pk=attached.pk).first()
        related = queryset.filter(category=attached.category).exclude(pk=attached.pk).order_by(
            "-rating_avg", "-rating_count", "-sales_count",
        )[: max(limit - 1, 0)]
        return [first, *related] if first else list(related)

    terms = _search_terms(message)
    if not terms:
        return []
    search = Q()
    for term in terms:
        search |= (
            Q(name__icontains=term)
            | Q(sku__icontains=term)
            | Q(manufacturer_sku__icontains=term)
            | Q(description__icontains=term)
            | Q(specifications__icontains=term)
            | Q(category__name__icontains=term)
            | Q(category__description__icontains=term)
            | Q(brand__name__icontains=term)
            | Q(brand__description__icontains=term)
            | Q(manufacturer_links__manufacturer__name__icontains=term)
        )
    return list(
        queryset.filter(search).distinct().order_by(
            "-rating_avg", "-rating_count", "-sales_count",
        )[:limit]
    )


def product_facts(product):
    reviews = list(product.reviews.filter(is_active=True).order_by(
        "-verified_purchase", "-helpful_count", "-created_at",
    )[:8])
    questions = list(product.questions.filter(
        is_active=True, is_public=True,
    ).exclude(answer__isnull=True).exclude(answer="").order_by("-helpful_count")[:8])
    accessories = [
        {
            "name": link.accessory.name,
            "description": _clean(link.accessory.description, 500),
            "price": str(link.accessory.price),
            "stock_quantity": link.accessory.stock_quantity,
            "required": link.required,
        }
        for link in product.product_accessories.all()
        if link.accessory.is_active
    ][:10]
    videos = []
    if product.video_url or product.local_video:
        videos.append({
            "title": product.video_title or "Product video",
            "source": product.video_type,
            "has_url": bool(product.video_url),
            "has_local_file": bool(product.local_video),
        })
    videos.extend({
        "title": video.title or "Product video",
        "description": _clean(video.description, 500),
        "source": video.source,
        "has_url": bool(video.youtube_url or video.vimeo_url),
        "has_local_file": bool(video.local_video),
    } for video in product.additional_videos.all()[:8])
    warranty = getattr(product, "manufacturer_warranty", None)
    shipping = getattr(product, "shipping_info", None)
    manufacturers = [
        {
            "name": link.manufacturer.name,
            "description": _clean(link.manufacturer.description, 800),
            "rating": str(link.manufacturer.rating_avg),
        }
        for link in product.manufacturer_links.all()
        if link.is_approved and link.manufacturer.is_active
    ][:5]
    image_metadata = [{
        "alt_text": image.alt_text,
        "is_main": image.is_main,
        "order": image.order,
    } for image in product.images.all()[:12]]
    return {
        "id": product.id,
        "title": product.name,
        "sku": product.sku,
        "manufacturer_sku": product.manufacturer_sku,
        "description": _clean(product.description),
        "specifications": _clean(product.specifications),
        "category": {
            "name": product.category.name,
            "description": _clean(product.category.description, 1200),
        },
        "brand": {
            "name": product.brand.name if product.brand else "",
            "description": _clean(product.brand.description, 1200) if product.brand else "",
        },
        "manufacturers": manufacturers,
        "price": str(product.price),
        "compare_price": str(product.compare_price or ""),
        "stock_quantity": product.available_stock,
        "is_in_stock": product.available_stock > 0,
        "allow_backorder": product.allow_backorder,
        "condition": product.get_condition_display(),
        "rating": str(product.rating_avg),
        "rating_count": product.rating_count,
        "reviews": [{
            "rating": review.rating,
            "title": _clean(review.title, 300),
            "review": _clean(review.review, 900),
            "verified_purchase": review.verified_purchase,
            "helpful_count": review.helpful_count,
        } for review in reviews],
        "questions_and_answers": [{
            "question": _clean(question.question, 700),
            "answer": _clean(question.answer, 1200),
            "helpful_count": question.helpful_count,
        } for question in questions],
        "accessories": accessories,
        "warranty": {
            "duration": warranty.duration_text() if warranty else (
                f"{product.warranty_years} year{'s' if product.warranty_years != 1 else ''}"
                if product.warranty_years is not None else ""
            ),
            "description": _clean(
                warranty.coverage_details if warranty else product.warranty_description,
                1500,
            ),
            "exclusions": _clean(warranty.exclusions, 800) if warranty else "",
        },
        "delivery": {
            "estimate": shipping.delivery_estimate() if shipping else "",
            "free_shipping": shipping.free_shipping if shipping else False,
            "restrictions": _clean(shipping.shipping_restrictions, 800) if shipping else "",
            "lead_time_days": product.lead_time_days,
        },
        "media": {
            "has_main_image": bool(product.main_image),
            "images": image_metadata,
            "videos": videos,
            "has_manual_pdf": bool(product.manual_pdf),
        },
    }


def _requested_missing_specs(message, facts):
    text = str(message or "").lower()
    searchable = " ".join([
        facts["description"],
        facts["specifications"],
        json.dumps(facts["questions_and_answers"]),
        json.dumps(facts["accessories"]),
        json.dumps(facts["warranty"]),
        json.dumps(facts["delivery"]),
    ]).lower()
    missing = []
    for label, aliases in SPEC_ALIASES.items():
        if any(alias in text for alias in aliases) and not any(alias in searchable for alias in aliases):
            if label == "stock" and "stock" in facts:
                continue
            if label == "price" and facts.get("price"):
                continue
            if label == "warranty" and facts["warranty"].get("duration"):
                continue
            if label == "delivery" and (
                facts["delivery"].get("estimate") or facts["delivery"].get("lead_time_days")
            ):
                continue
            missing.append(label)
    return missing


def _deterministic_reply(message, products, facts):
    product = products[0]
    lines = [
        f"Here is what Arolana lists for {product.name}:",
        f"• Price: ₦{product.price:,.2f}",
        f"• Stock: {facts['stock_quantity']} available" if facts["is_in_stock"] else "• Stock: currently unavailable",
        f"• Rating: {facts['rating']}/5 from {facts['rating_count']} rating(s)",
    ]
    if facts["specifications"]:
        lines.append(f"• Listed specifications: {facts['specifications'][:500]}")
    if facts["accessories"]:
        lines.append("• Accessories: " + ", ".join(item["name"] for item in facts["accessories"][:5]))
    if facts["warranty"]["duration"]:
        lines.append(f"• Warranty: {facts['warranty']['duration']}")
    if facts["delivery"]["estimate"]:
        lines.append(f"• Delivery estimate: {facts['delivery']['estimate']}")
    if facts["reviews"]:
        lines.append(
            f"• Review signal: {len(facts['reviews'])} recent review(s) were checked, "
            f"including {sum(1 for item in facts['reviews'] if item['verified_purchase'])} verified purchase review(s)."
        )
    if len(products) > 1 and any(term in str(message).lower() for term in ("compare", "better", "recommend", "larger", "alternative")):
        lines.append(
            "• Related options to compare: "
            + ", ".join(f"{item.name} (₦{item.price:,.2f}, {item.rating_avg}/5)" for item in products[1:])
        )
    lines.append("I based this only on the product information currently stored on Arolana.")
    return "\n".join(lines)


def product_intelligence_reply(conversation, message):
    if not _is_product_question(message, conversation):
        return None
    products = find_products(message, conversation)
    if not products:
        return None
    facts = product_facts(products[0])
    missing = _requested_missing_specs(message, facts)
    if missing:
        return MISSING_SPEC_MESSAGE, {
            "source_type": "product_database_missing_spec",
            "source_label": products[0].name,
            "source_object_id": products[0].id,
            "confidence": 0.2,
            "missing_specs": missing,
            "product_ids": [item.id for item in products],
        }

    api_key = getattr(settings, "OPENAI_API_KEY", None) or os.environ.get("OPENAI_API_KEY")
    reply = ""
    if api_key:
        try:
            from openai import OpenAI

            client = OpenAI(api_key=api_key)
            response = client.responses.create(
                model=getattr(settings, "AROLANA_AI_MODEL", "gpt-5.5"),
                instructions=(
                    "You are Arolana Product Intelligence. Answer only from the supplied "
                    "Arolana product facts. Consider description, specifications, accessories, "
                    "compatibility notes, media metadata, reviews, ratings, Q&A, category, brand, "
                    "manufacturer, warranty, delivery, stock and price. Compare supplied related "
                    "products when useful. Never infer or invent a specification. If a fact needed "
                    f"for the answer is absent, reply exactly: {MISSING_SPEC_MESSAGE}"
                ),
                input=json.dumps({
                    "customer_question": message,
                    "primary_product": facts,
                    "related_products": [product_facts(item) for item in products[1:]],
                }, default=str),
            )
            reply = (getattr(response, "output_text", "") or "").strip()
        except Exception:
            reply = ""
    if not reply:
        reply = _deterministic_reply(message, products, facts)
    return reply, {
        "source_type": "product_database",
        "source_label": products[0].name,
        "source_object_id": products[0].id,
        "confidence": 0.9,
        "product_ids": [item.id for item in products],
        "facts_checked": [
            "description", "specifications", "accessories", "media", "reviews",
            "ratings", "questions_and_answers", "category", "brand", "manufacturer",
            "warranty", "delivery", "stock", "price",
        ],
    }
