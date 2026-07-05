import re
from copy import deepcopy
from decimal import Decimal, InvalidOperation

from products.models import Brand, Category


DEFAULT_STATE = {
    "intent": "",
    "previous_intent": "",
    "last_topic": "",
    "active_subject": "",
    "brand": "",
    "category": "",
    "subcategory": "",
    "product_type": "",
    "current_product_id": None,
    "current_product_name": "",
    "current_vendor_id": None,
    "current_order_id": None,
    "current_quote_request_id": None,
    "current_service_provider_id": None,
    "requirements": {
        "room_type": None,
        "use_case": None,
        "screen_size_inches": None,
        "throw_distance": None,
        "budget_min": None,
        "budget_max": None,
        "resolution": None,
        "brightness_requirement": None,
        "participant_count": None,
        "platform": None,
        "delivery_location": None,
        "quantity": None,
    },
    "recommendation": {
        "candidate_product_ids": [],
        "current_recommendation_id": None,
        "previous_recommendation_ids": [],
    },
    "topic_stack": [],
    "support": {
        "status": "ai",
        "requires_handoff": False,
        "handoff_reason": "",
    },
}


def _merge_defaults(existing, defaults):
    result = deepcopy(defaults)
    for key, value in (existing or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge_defaults(value, result[key])
        elif value not in (None, ""):
            result[key] = value
    return result


def normalized_state(conversation):
    context = dict(conversation.context or {})
    state = _merge_defaults(context.get("state"), DEFAULT_STATE)
    product = getattr(conversation, "product", None)
    if product:
        state["current_product_id"] = product.id
        state["current_product_name"] = product.name
        state["current_vendor_id"] = product.vendor_id
        state["brand"] = getattr(getattr(product, "brand", None), "name", "") or state["brand"]
        state["category"] = product.category.name or state["category"]
        state["subcategory"] = product.category.name if product.category.parent_id else state["subcategory"]
        state["product_type"] = state["product_type"] or product.category.name
    # Read legacy state so old conversations remain useful.
    state["brand"] = state["brand"] or context.get("current_brand", "")
    state["category"] = state["category"] or context.get("current_category", "")
    state["current_product_id"] = state["current_product_id"] or context.get("current_product_id")
    state["current_product_name"] = state["current_product_name"] or context.get("current_product_name", "")
    requirements = state["requirements"]
    requirements["room_type"] = requirements["room_type"] or context.get("room_size")
    requirements["use_case"] = requirements["use_case"] or context.get("use_case")
    requirements["delivery_location"] = (
        requirements["delivery_location"]
        or context.get("delivery_location")
        or context.get("user_location")
    )
    budget = str(context.get("user_budget") or "")
    if budget and requirements["budget_max"] is None:
        values = [int(value.replace(",", "")) for value in re.findall(r"\d[\d,]*", budget)]
        if values:
            requirements["budget_min"] = min(values) if len(values) > 1 else None
            requirements["budget_max"] = max(values)
    return state


def _money_values(text):
    values = []
    for raw in re.findall(r"(?:₦|ngn|n|\$)?\s*(\d[\d,]*(?:\.\d+)?)\s*([kKmM]?)", text):
        number, suffix = raw
        try:
            value = Decimal(number.replace(",", ""))
        except InvalidOperation:
            continue
        if suffix.lower() == "k":
            value *= 1000
        elif suffix.lower() == "m":
            value *= 1000000
        if value >= 1000:
            values.append(int(value))
    return values


def _catalog_entities(text):
    lowered = text.lower()
    brand = ""
    category = None
    for item in Brand.objects.filter(is_active=True).only("id", "name").order_by("-name"):
        if item.name.lower() in lowered:
            brand = item.name
            break
    for item in Category.objects.filter(is_active=True).select_related("parent").only(
        "id", "name", "parent__name",
    ).order_by("-name"):
        name = item.name.lower()
        singular = name[:-1] if name.endswith("s") else name
        if name in lowered or (len(singular) > 3 and re.search(rf"\b{re.escape(singular)}s?\b", lowered)):
            category = item
            break
    return brand, category


def extract_facts(message):
    text = re.sub(r"\s+", " ", str(message or "").strip().lower())
    facts = {"requirements": {}}
    brand, category = _catalog_entities(text)
    if brand:
        facts["brand"] = brand
    if category:
        facts["category"] = category.name
        facts["subcategory"] = category.name if category.parent_id else ""
        facts["product_type"] = category.name
        facts["catalog_category_id"] = category.id

    room = re.search(
        r"\b(small|medium|mid(?:-sized)?|large)\s+(room|hall|church|office|space|classroom|boardroom)\b",
        text,
    )
    if room:
        facts["requirements"]["room_type"] = f"{room.group(1)}_{room.group(2)}".replace("-", "_")
    elif text.strip() in {"small room", "medium room", "large room", "boardroom", "church", "classroom"}:
        facts["requirements"]["room_type"] = text.strip().replace(" ", "_")

    screen = re.search(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:inch|inches|in|”|\")\b", text)
    if screen:
        facts["requirements"]["screen_size_inches"] = float(screen.group(1))
    participants = re.search(r"\b(?:for\s+)?(\d{1,3})\s*(?:people|persons|participants|users|seats)\b", text)
    if participants:
        facts["requirements"]["participant_count"] = int(participants.group(1))
    quantity = re.search(r"\b(?:quantity|qty|need|order)\s*(?:of|:|is)?\s*(\d{1,6})\s*(?:units?|items?|pieces?)?\b", text)
    if quantity:
        facts["requirements"]["quantity"] = int(quantity.group(1))

    values = _money_values(text)
    if values:
        if len(values) > 1:
            facts["requirements"]["budget_min"] = min(values)
        facts["requirements"]["budget_max"] = max(values)
    resolution = re.search(r"\b(4k|8k|full\s*hd|1080p|720p|uhd|qhd)\b", text)
    if resolution:
        facts["requirements"]["resolution"] = resolution.group(1).replace(" ", "_")
    brightness = re.search(r"\b(\d{3,6})\s*(?:ansi\s*)?lumens?\b", text)
    if brightness:
        facts["requirements"]["brightness_requirement"] = int(brightness.group(1))
    if "short throw" in text:
        facts["requirements"]["throw_distance"] = "short_throw"
    elif "ultra short throw" in text:
        facts["requirements"]["throw_distance"] = "ultra_short_throw"
    platform = next((name for name in ("zoom", "teams", "meet", "webex") if name in text), "")
    if platform:
        facts["requirements"]["platform"] = platform
    location = re.search(
        r"\b(?:deliver(?:ed|y)?\s+to|located\s+in|i(?:'m| am)\s+in)\s+([a-z][a-z\s-]{2,60})",
        text,
    )
    if location:
        facts["requirements"]["delivery_location"] = location.group(1).strip(" .,!?:;")
    use_case = re.search(r"\b(?:for|use it for|need it for)\s+(church|school|office|home|gaming|medical|business|training)\b", text)
    if use_case:
        facts["requirements"]["use_case"] = use_case.group(1)
    return facts


def prepare_context(conversation, message):
    context = dict(conversation.context or {})
    state = normalized_state(conversation)
    facts = extract_facts(message)
    for key in (
        "brand", "category", "subcategory", "product_type", "catalog_category_id",
    ):
        if facts.get(key) not in (None, ""):
            state[key] = facts[key]
    for key, value in facts["requirements"].items():
        if value not in (None, ""):
            state["requirements"][key] = value
    state["previous_intent"] = state.get("intent") or conversation.current_intent or context.get("last_intent", "")
    state["active_subject"] = (
        state.get("current_product_name")
        or " ".join(part for part in (state.get("brand"), state.get("product_type")) if part)
        or state.get("category")
        or state.get("last_topic")
    )
    context["state"] = state
    conversation.context = context
    conversation.save(update_fields=["context", "updated_at"])
    return state


def persist_state(conversation, state):
    context = dict(conversation.context or {})
    context["state"] = state
    requirements = state["requirements"]
    context.update({
        "current_product_id": state.get("current_product_id"),
        "current_product_name": state.get("current_product_name", ""),
        "current_brand": state.get("brand", ""),
        "current_category": state.get("category", ""),
        "room_size": requirements.get("room_type"),
        "use_case": requirements.get("use_case"),
        "delivery_location": requirements.get("delivery_location"),
        "user_budget": (
            f"{requirements.get('budget_min')} - {requirements.get('budget_max')}"
            if requirements.get("budget_min")
            else requirements.get("budget_max")
        ),
        "last_intent": state.get("intent", ""),
        "last_topic": state.get("last_topic", ""),
    })
    conversation.context = context
    conversation.current_intent = state.get("intent", conversation.current_intent)
    conversation.save(update_fields=["context", "current_intent", "updated_at"])
    return context
