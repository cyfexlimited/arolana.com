import re
from decimal import Decimal

from django.db.models import Q

from products.models import Product
from .product_intelligence import product_card, product_facts


def _catalog_queryset():
    return Product.objects.filter(
        is_active=True,
        approval_status="approved",
    ).select_related(
        "category", "category__parent", "brand", "vendor", "vendor__vendor_profile",
        "shipping_info", "manufacturer_warranty",
    ).prefetch_related(
        "images", "additional_videos", "reviews", "questions",
        "product_accessories__accessory", "manufacturer_links__manufacturer",
    )


def _candidate_queryset(state):
    queryset = _catalog_queryset()
    brand = state.get("brand")
    category = state.get("category")
    product_type = state.get("product_type")
    if brand:
        queryset = queryset.filter(brand__name__iexact=brand)
    if category:
        queryset = queryset.filter(
            Q(category__name__iexact=category)
            | Q(category__parent__name__iexact=category)
        )
    elif product_type:
        queryset = queryset.filter(
            Q(category__name__icontains=product_type)
            | Q(category__parent__name__icontains=product_type)
            | Q(name__icontains=product_type)
        )
    requirements = state.get("requirements", {})
    if requirements.get("budget_min") is not None:
        queryset = queryset.filter(price__gte=requirements["budget_min"])
    if requirements.get("budget_max") is not None:
        queryset = queryset.filter(price__lte=requirements["budget_max"])
    return queryset.distinct()


def _haystack(product):
    return re.sub(
        r"\s+",
        " ",
        " ".join([
            product.name,
            str(product.description or ""),
            str(product.specifications or ""),
            product.category.name,
            product.category.parent.name if product.category.parent else "",
            product.brand.name if product.brand else "",
        ]).lower(),
    )


def _score(product, state):
    text = _haystack(product)
    requirements = state.get("requirements", {})
    score = Decimal("0")
    verified = getattr(product.vendor, "vendor_profile", None)
    if product.available_stock > 0:
        score += Decimal("20")
    if verified and verified.approval_status == "approved" and verified.is_active:
        score += Decimal("12")
    score += Decimal(str(product.rating_avg or 0)) * Decimal("2")
    score += min(Decimal(str(product.rating_count or 0)), Decimal("20")) / Decimal("4")
    for key in ("room_type", "use_case", "resolution", "throw_distance", "platform"):
        value = str(requirements.get(key) or "").replace("_", " ").lower()
        if value and all(token in text for token in value.split()):
            score += Decimal("12")
    participants = requirements.get("participant_count")
    if participants and str(participants) in text:
        score += Decimal("8")
    screen = requirements.get("screen_size_inches")
    if screen and str(int(screen)) in text:
        score += Decimal("8")
    brightness = requirements.get("brightness_requirement")
    if brightness and str(brightness) in text:
        score += Decimal("8")
    return score


def ranked_products(state, mode="", limit=4):
    queryset = _candidate_queryset(state)
    recommendation = state.get("recommendation", {})
    previous = list(recommendation.get("previous_recommendation_ids") or [])
    current_id = recommendation.get("current_recommendation_id") or state.get("current_product_id")
    if mode in {"alternative_request", "cheaper_request", "better_request"}:
        excluded = set(previous)
        if current_id:
            excluded.add(current_id)
        queryset = queryset.exclude(pk__in=excluded)
    if mode == "cheaper_request" and current_id:
        current = Product.objects.filter(pk=current_id).only("price").first()
        if current:
            queryset = queryset.filter(price__lt=current.price)
    candidates = list(queryset[:80])
    candidates.sort(
        key=lambda product: (
            _score(product, state),
            product.rating_avg or 0,
            product.rating_count or 0,
            product.sales_count or 0,
        ),
        reverse=True,
    )
    return candidates[:limit]


def _format_requirement_summary(state):
    requirements = state.get("requirements", {})
    parts = []
    if state.get("brand"):
        parts.append(state["brand"])
    if state.get("product_type") or state.get("category"):
        parts.append(state.get("product_type") or state["category"])
    if requirements.get("room_type"):
        parts.append(str(requirements["room_type"]).replace("_", " "))
    if requirements.get("screen_size_inches"):
        parts.append(f"{requirements['screen_size_inches']:g}-inch screen")
    if requirements.get("participant_count"):
        parts.append(f"{requirements['participant_count']} people")
    if requirements.get("budget_max"):
        parts.append(f"budget up to ₦{requirements['budget_max']:,.0f}")
    return ", ".join(parts)


def recommend(state, mode="recommendation_decision"):
    products = ranked_products(state, mode=mode)
    if not products:
        return None
    product = products[0]
    facts = product_facts(product)
    recommendation = state["recommendation"]
    old_current = recommendation.get("current_recommendation_id")
    previous = list(recommendation.get("previous_recommendation_ids") or [])
    if old_current and old_current != product.id and old_current not in previous:
        previous.append(old_current)
    recommendation["previous_recommendation_ids"] = previous[-20:]
    recommendation["candidate_product_ids"] = [item.id for item in products]
    recommendation["current_recommendation_id"] = product.id
    state["current_product_id"] = product.id
    state["current_product_name"] = product.name
    state["current_vendor_id"] = product.vendor_id
    state["brand"] = getattr(getattr(product, "brand", None), "name", "") or state.get("brand", "")
    state["category"] = product.category.name

    requirement_summary = _format_requirement_summary(state)
    reason_parts = []
    if facts["is_in_stock"]:
        reason_parts.append("it is currently listed as available")
    if facts["rating_count"]:
        reason_parts.append(f"it has {facts['rating']}/5 from {facts['rating_count']} rating(s)")
    requirements = state.get("requirements", {})
    text = _haystack(product)
    for key in ("resolution", "throw_distance", "platform"):
        value = str(requirements.get(key) or "").replace("_", " ")
        if value and value in text:
            reason_parts.append(f"its listing confirms {value}")
    reason = "; ".join(reason_parts) or "it is the strongest live catalog match for the requirements provided"

    limitations = []
    if requirements.get("screen_size_inches") and not re.search(r"\bthrow\b|\bprojection distance\b", text):
        limitations.append("the listing does not include verified throw-distance data")
    if requirements.get("participant_count") and str(requirements["participant_count"]) not in text:
        limitations.append("the exact participant capacity is not stated in the listing")
    limitation = (
        " Important limitation: " + "; ".join(limitations) + "."
        if limitations else ""
    )
    prefix = {
        "alternative_request": "Another suitable option is",
        "cheaper_request": "A cheaper suitable option is",
        "better_request": "A stronger premium option is",
    }.get(mode, "My best live Arolana match is")
    reply = (
        f"{prefix} {product.name} at ₦{product.price:,.2f}. "
        f"For {requirement_summary or 'your request'}, I chose it because {reason}."
        f"{limitation} Stock: {facts['stock_quantity']} available."
    )
    return reply, {
        "source_type": "live_catalog_recommendation",
        "source_label": product.name,
        "source_object_id": product.id,
        "confidence": 0.88 if not limitations else 0.72,
        "product_ids": [item.id for item in products],
        "product_cards": [product_card(item) for item in products[:2]],
        "recommendation_mode": mode,
        "limitations": limitations,
    }, state, product


def current_price_reply(state):
    product_id = (
        state.get("recommendation", {}).get("current_recommendation_id")
        or state.get("current_product_id")
    )
    product = _catalog_queryset().filter(pk=product_id).first() if product_id else None
    if not product:
        return None
    return (
        f"{product.name} is currently listed at ₦{product.price:,.2f} on Arolana. "
        f"{'It is in stock.' if product.available_stock > 0 else 'It is currently out of stock.'}",
        {
            "source_type": "live_product_price",
            "source_label": product.name,
            "source_object_id": product.id,
            "confidence": 0.98,
            "product_ids": [product.id],
        },
        product,
    )
