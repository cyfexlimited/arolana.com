import re
from copy import deepcopy
from decimal import Decimal, InvalidOperation

from django.db.models import Q

from products.models import Brand, Category


DEFAULT_STATE = {
    "intent": "",
    "intent_family": "",
    "transaction_type": "",
    "previous_intent": "",
    "last_topic": "",
    "active_subject": "",
    "active_category": "",
    "active_subcategory": "",
    "active_service": "",
    "entity_type": "",
    "search_query": "",
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
        "condition": None,
        "brand": None,
        "currency": None,
        "budget_amount": None,
        "minimum_budget": None,
        "maximum_budget": None,
        "location": None,
        "service_location": None,
        "model": None,
        "year_min": None,
        "mileage": None,
        "transmission": None,
        "fuel_type": None,
        "bedrooms": None,
        "bathrooms": None,
        "land_size": None,
        "capacity": None,
        "power": None,
        "horsepower": None,
        "fault_description": None,
        "urgency": None,
        "preferred_date": None,
        "service_type": None,
        "service_needed": None,
        "license_users": None,
        "platform": None,
    },
    "constraints": {},
    "preferences": {},
    "location": {},
    "budget": {},
    "conversation_stage": "",
    "missing_slots": [],
    "completed_slots": [],
    "explicit_subject_change": False,
    "last_user_message_type": "",
    "source_confidence": {},
    "recommendation": {
        "candidate_product_ids": [],
        "current_recommendation_id": None,
        "previous_recommendation_ids": [],
    },
    "topic_stack": [],
    "workflow": {},
    "support": {
        "status": "ai",
        "requires_handoff": False,
        "handoff_reason": "",
    },
}


LOCATION_ALIASES = {
    "lagos": "Lagos",
    "abuja": "Abuja",
    "enugu": "Enugu",
    "owerri": "Owerri",
    "ogun": "Ogun State",
    "ogun state": "Ogun State",
    "ibadan": "Ibadan",
    "port harcourt": "Port Harcourt",
    "ikeja": "Ikeja",
    "lekki": "Lekki",
    "ajah": "Ajah",
    "yaba": "Yaba",
    "surulere": "Surulere",
}

CONDITION_ALIASES = {
    "brand new": "brand_new",
    "new": "brand_new",
    "sealed": "brand_new",
    "open box": "open_box",
    "uk used": "uk_used",
    "foreign used": "foreign_used",
    "locally used": "locally_used",
    "used is fine": "foreign_used",
    "used is acceptable": "foreign_used",
    "used": "foreign_used",
    "refurbished": "refurbished",
    "fairly used": "fairly_used",
    "certified pre owned": "certified_pre_owned",
    "certified pre-owned": "certified_pre_owned",
}

SLOT_KEYS = {
    "budget_min",
    "budget_max",
    "budget_amount",
    "currency",
    "minimum_budget",
    "maximum_budget",
    "delivery_location",
    "location",
    "service_location",
    "condition",
    "brand",
    "brightness_requirement",
    "resolution",
    "quantity",
    "participant_count",
    "screen_size_inches",
    "room_type",
    "use_case",
    "throw_distance",
    "model",
    "year_min",
    "mileage",
    "transmission",
    "fuel_type",
    "bedrooms",
    "bathrooms",
    "land_size",
    "capacity",
    "power",
    "horsepower",
    "fault_description",
    "urgency",
    "preferred_date",
    "service_type",
    "service_needed",
    "license_users",
    "platform",
}

RESET_FLOW_PATTERNS = (
    r"\bstart over\b",
    r"\breset\b",
    r"\bnew search\b",
    r"\bnew request\b",
    r"\bforget (?:that|this)\b",
)

EXPLICIT_CHANGE_PATTERNS = (
    r"^do you have\s+(?!it\b|that\b|this\b)",
    r"^show me\s+(?!another\b|it\b|that\b|this\b)",
    r"\bactually\b.*\bforget\b",
    r"\bforget\b.*\bi (?:need|want)\b",
    r"\binstead\b",
    r"\bchange (?:it|this|category|product)\b",
    r"\bswitch (?:to|from)\b",
    r"\bnow (?:i want|show me|find me|search for)\b",
    r"\b(?:actually|rather),?\s+(?:i want|show me|find me|search for|do you have)\b",
)

SERVICE_TRANSACTION_TERMS = {
    "repair": "repair",
    "fix": "repair",
    "service": "maintain",
    "maintain": "maintain",
    "install": "install",
    "installation": "install",
    "inspect": "inspect",
    "inspection": "inspect",
    "consult": "consult",
    "valuer": "inspect",
    "valuation": "inspect",
    "technician": "find_provider",
    "installer": "find_provider",
    "provider": "find_provider",
    "engineer": "find_provider",
}

TRANSACTION_TERMS = {
    "buy": "buy",
    "purchase": "buy",
    "sell": "sell",
    "rent": "rent",
    "rental": "rent",
    "lease": "lease",
    "short-let": "short_let",
    "short let": "short_let",
    "hire": "hire",
    "quote": "request_quote",
    "quotation": "request_quote",
    "compare": "compare",
    "source": "source",
    "import": "import",
    "manufacture": "manufacture",
    "custom": "custom_order",
    **SERVICE_TRANSACTION_TERMS,
}

ENTITY_HINTS = (
    ("vehicle", ("car", "cars", "suv", "bus", "buses", "truck", "van", "motorcycle", "tricycle", "hilux", "camry", "corolla", "toyota", "gearbox")),
    ("property", ("apartment", "land", "office space", "warehouse", "short-let", "short let", "bedroom", "bedrooms", "lekki", "ikeja")),
    ("medical_equipment", ("hospital", "patient monitor", "ultrasound", "x-ray", "xray", "hospital bed", "laboratory")),
    ("farm_equipment", ("tractor", "harvester", "poultry", "irrigation", "farm", "hectare", "horsepower")),
    ("service_provider", ("installer", "technician", "repair", "maintenance", "consultant", "logistics", "electrician", "mechanic")),
    ("software", ("software", "licence", "license", "web and mobile", "students", "staff members", "app")),
)


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
    stored_state = dict(context.get("state") or {})
    requirements_were_explicitly_cleared = (
        "requirements" in stored_state
        and stored_state.get("requirements") == {}
    )
    state = _merge_defaults(stored_state, DEFAULT_STATE)

    # An empty requirements dictionary is meaningful: it marks a deliberate
    # topic reset. Do not expand it back into DEFAULT_STATE's None-filled
    # requirement template.
    if requirements_were_explicitly_cleared:
        state["requirements"] = {}

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
    state["intent_family"] = state.get("intent_family") or context.get("intent_family", "")
    state["transaction_type"] = state.get("transaction_type") or context.get("transaction_type", "")
    state["entity_type"] = state.get("entity_type") or context.get("entity_type", "")
    state["search_query"] = state.get("search_query") or context.get("search_query", "")
    state["active_category"] = state.get("active_category") or state.get("category", "")
    state["active_subcategory"] = state.get("active_subcategory") or state.get("subcategory", "")
    state["active_service"] = state.get("active_service") or context.get("active_service", "")
    requirements = state.get("requirements") or {}
    if not requirements_were_explicitly_cleared:
        requirements["room_type"] = requirements.get("room_type") or context.get("room_size")
        requirements["use_case"] = requirements.get("use_case") or context.get("use_case")
        requirements["delivery_location"] = (
            requirements.get("delivery_location")
            or context.get("delivery_location")
            or context.get("user_location")
        )
        budget = str(context.get("user_budget") or "")
        if budget and requirements.get("budget_max") is None:
            values = [int(value.replace(",", "")) for value in re.findall(r"\d[\d,]*", budget)]
            if values:
                requirements["budget_min"] = min(values) if len(values) > 1 else None
                requirements["budget_max"] = max(values)
    return state


def _money_matches(text):
    matches = []
    for match in re.finditer(
        r"(?P<prefix>₦|ngn|naira|n|\$|usd|dollars?)?\s*"
        r"(?P<number>\d[\d,]*(?:\.\d+)?)\s*"
        r"(?P<word>thousand|million|m|k)?",
        text,
    ):
        prefix = (match.group("prefix") or "").lower()
        number = match.group("number")
        suffix = (match.group("word") or "").lower()
        tail = text[match.end():match.end() + 16]
        window = text[max(0, match.start() - 32):match.end() + 32]
        if re.match(r"[-\s]*(?:ansi\s*)?(?:lumens?|inch|inches|people|participants|users|students|staff|beds?|units?|hectares?|horsepower|hp|sqm|square)\b", tail):
            continue
        has_budget_context = re.search(
            r"\b(?:budget|price|cost|under|below|around|about|up to|for about|not more than|between)\b",
            window,
        )
        if not (prefix or suffix or has_budget_context):
            continue
        try:
            value = Decimal(number.replace(",", ""))
        except InvalidOperation:
            continue
        if suffix in {"k", "thousand"}:
            value *= 1000
        elif suffix in {"m", "million"}:
            value *= 1000000
        if value >= 1000:
            currency = "USD" if prefix in {"$", "usd", "dollar", "dollars"} else "NGN" if prefix in {"₦", "ngn", "naira", "n"} else ""
            matches.append({"value": int(value), "currency": currency, "start": match.start(), "end": match.end()})
    return matches


def _money_values(text):
    return [item["value"] for item in _money_matches(text)]


def _contextual_budget_values(text):
    comparable = re.sub(r"\s+", " ", str(text or "").strip().lower()).strip(" .,!?:;")
    if not re.fullmatch(
        r"(?:₦|ngn|naira|n|\$|usd)?\s*[\d,.]+\s*[km]?"
        r"(?:\s*-\s*(?:₦|ngn|naira|n|\$|usd)?\s*[\d,.]+\s*[km]?)?",
        comparable,
    ):
        return []

    values = []
    for match in re.finditer(
        r"(?P<prefix>₦|ngn|naira|n|\$|usd)?\s*"
        r"(?P<number>\d[\d,]*(?:\.\d+)?)\s*"
        r"(?P<suffix>[km])?",
        comparable,
    ):
        try:
            value = Decimal(match.group("number").replace(",", ""))
        except InvalidOperation:
            continue
        suffix = (match.group("suffix") or "").lower()
        if suffix == "k":
            value *= 1000
        elif suffix == "m":
            value *= 1000000
        if value >= 1000:
            values.append(int(value))
    return values


def _category_name_variants(category):
    if not category:
        return set()
    names = {str(category.name or "").strip().lower()}
    slug = str(getattr(category, "slug", "") or "").replace("-", " ").strip().lower()
    if slug:
        names.add(slug)
    for name in list(names):
        if name.endswith("s") and len(name) > 4:
            names.add(name[:-1])
        elif name:
            names.add(f"{name}s")
    return {name for name in names if name}


def _find_category_for_product_type(text):
    lowered = text.lower()
    subject = _subject_from_text(lowered)
    if subject:
        query = Q(name__icontains=subject) | Q(slug__icontains=subject.replace(" ", "-"))
        for token in [token for token in subject.split() if len(token) > 2][:4]:
            query |= Q(name__icontains=token) | Q(slug__icontains=token)
        return (
            Category.objects.filter(query, is_active=True)
            .select_related("parent")
            .order_by("parent_id", "name")
            .first()
        )
    return None


def _subject_from_text(text):
    cleaned = re.sub(r"\s+", " ", str(text or "").lower()).strip(" .,!?:;")
    has_subject_intent = bool(
        re.search(
            r"\b(?:do you have|show me|find me|search for|i need|i want|"
            r"find|i am looking for|i'm looking for|looking for)\b",
            cleaned,
        )
    )
    if (
        not has_subject_intent
        and (
            _money_matches(cleaned)
            or _condition_from_text(cleaned)
            or _location_from_text(cleaned)
            or re.fullmatch(r"\d{2,6}\s*(?:ansi\s*)?lumens?", cleaned)
            or re.fullmatch(r"(?:for\s+)?\d{1,3}\s*(?:people|persons|participants|users|seats)", cleaned)
            or re.fullmatch(r"(?:about\s+|around\s+)?\d[\d,]*\s*(?:square\s*metres|sqm|m2|hectares?|acres?)", cleaned)
            or re.fullmatch(r"(?:full\s*hd|1080p|720p|4k|8k|uhd|qhd)", cleaned)
        )
    ):
        return ""
    explicit_new = re.search(
        r"\b(?:actually|instead|rather|forget .+?\.?|forget .+?;)?\s*"
        r"(?:i need|i want|show me|find me|search for)\s+(?:(?:a|an|some|the)\s+)?"
        r"(.+?)(?:\s+(?:under|below|around|about|in|for|with|delivered|next|this week)\b|[.!?]|$)",
        cleaned,
    )
    if explicit_new and re.search(r"\b(?:actually|instead|rather|forget)\b", cleaned):
        subject = explicit_new.group(1).strip(" .,!?:;")
        subject = re.sub(r"^(?:to\s+)?(?:buy|rent|repair|install|maintain|inspect|service)\s+", "", subject)
        subject = re.sub(r"^(?:a|an|the|some)\s+", "", subject)
        return subject[:120]
    for pattern in (
        r"\b(?:forget|no longer need)\s+(?:the\s+)?(.+?)(?:;|,|\band\b|\.)",
        r"\b(?:do you have|show me|find me|find|search for)\s+(?:(?:a|an|some)\s+)?(.+?)(?:\s+(?:under|below|around|about|in|for|with|delivered|next|this week)\b|[.!?]|$)",
        r"\b(?:i need|i want|i am looking for|i'm looking for|looking for)\s+(?:someone to\s+)?(?:(?:a|an|some)\s+)?(.+?)(?:\s+(?:under|below|around|about|in|for|with|delivered|next|this week)\b|[.!?]|$)",
    ):
        match = re.search(pattern, cleaned)
        if match:
            subject = match.group(1).strip(" .,!?:;")
            subject = re.sub(r"^(?:to\s+)?(?:buy|rent|repair|install|maintain|inspect|service)\s+", "", subject)
            subject = re.sub(r"^(?:a|an|the|some)\s+", "", subject)
            return subject[:120]
    if len(cleaned.split()) <= 5 and not slot_updates_from_facts({"requirements": _slot_facts_only(cleaned)}):
        return cleaned[:120]
    return ""


def _entity_type_from_text(text, subject=""):
    haystack = f"{text} {subject}".lower()
    if re.search(r"\bdeveloper|designer|consultant|provider|installer|technician|valuer|mechanic\b", haystack):
        return "service_provider"
    for entity_type, terms in ENTITY_HINTS:
        if any(re.search(rf"\b{re.escape(term)}s?\b", haystack) for term in terms):
            return entity_type
    return "service_provider" if any(term in haystack for term in SERVICE_TRANSACTION_TERMS) else "product"


def _transaction_type_from_text(text, entity_type=""):
    lowered = text.lower()
    if entity_type == "property" and re.search(r"\b(?:rent|lease|yearly|per year|per annum|short-let|short let)\b", lowered):
        return "rent"
    if entity_type == "vehicle" and re.search(r"\b(?:rent|rental|hire)\b", lowered):
        return "rent"
    for term, transaction in TRANSACTION_TERMS.items():
        if re.search(rf"\b{re.escape(term)}\b", lowered):
            return transaction
    if entity_type == "property":
        if re.search(r"\b(?:rent|lease|yearly|per year|short-let|short let)\b", lowered):
            return "rent"
        return "find_property"
    if entity_type == "service_provider":
        return "find_provider"
    return "buy"


def _intent_family(entity_type, transaction_type):
    if transaction_type in {"repair", "install", "maintain", "inspect", "consult", "find_provider"}:
        return "service"
    if entity_type == "property":
        return "real_estate"
    if entity_type == "vehicle":
        return "vehicle"
    if entity_type == "software":
        return "software"
    return "commerce"


def _slot_facts_only(text):
    facts = {}
    condition = _condition_from_text(text)
    if condition:
        facts["condition"] = condition
    location = _location_from_text(text)
    if location:
        facts["delivery_location"] = location
    return facts


def _catalog_entities(text):
    lowered = text.lower()
    brand = ""
    category = None
    for item in Brand.objects.filter(is_active=True).only("id", "name").order_by("-name"):
        if item.name.lower() in lowered:
            brand = item.name
            break
    for item in Category.objects.filter(is_active=True).select_related("parent").only(
        "id", "name", "slug", "parent__name",
    ).order_by("-name"):
        names = _category_name_variants(item)
        if any(re.search(rf"\b{re.escape(name)}\b", lowered) for name in names):
            category = item
            break
    return brand, category


def _condition_from_text(text):
    for phrase, value in CONDITION_ALIASES.items():
        if re.search(rf"\b{re.escape(phrase)}\b", text):
            return value
    return ""


def _location_from_text(text):
    location = re.search(
        r"\b(?:deliver(?:ed|y)?\s+to|located\s+in|i(?:'m| am)\s+in|in)\s+([a-z][a-z\s-]{2,60})",
        text,
    )
    if location:
        candidate = location.group(1).strip(" .,!?:;")
        for alias, label in LOCATION_ALIASES.items():
            if alias in candidate:
                return label
        return candidate.title()
    comparable = text.strip(" .,!?:;")
    for alias, label in LOCATION_ALIASES.items():
        if comparable == alias or comparable == label.lower():
            return label
    return LOCATION_ALIASES.get(comparable, "")


def is_explicit_category_change(message):
    text = re.sub(r"\s+", " ", str(message or "").strip().lower())
    return any(re.search(pattern, text) for pattern in EXPLICIT_CHANGE_PATTERNS)


def is_flow_reset(message):
    text = re.sub(r"\s+", " ", str(message or "").strip().lower())
    return any(re.search(pattern, text) for pattern in RESET_FLOW_PATTERNS)


def shopping_category_label(state):
    return (
        state.get("locked_category")
        or state.get("product_type")
        or state.get("category")
        or state.get("active_subject")
        or ""
    )


def has_locked_shopping_category(state):
    return bool(
        state.get("shopping_category_locked")
        and shopping_category_label(state)
    )


def _active_service_flow(state):
    return (
        state.get("entity_type") == "service_provider"
        or state.get("intent_family") == "service"
        or state.get("transaction_type") in {
            "install",
            "repair",
            "maintain",
            "inspect",
            "consult",
            "book_service",
            "find_provider",
        }
    )


def _explicit_product_request(message):
    text = re.sub(r"\s+", " ", str(message or "").strip().lower())
    return bool(
        re.search(
            r"\b(?:show me|find|search for|compare|price of|how much|"
            r"buy|purchase|do you have|what equipment|which equipment|"
            r"products?|devices?|catalogue|catalog)\b",
            text,
        )
        and not re.search(
            r"\b(?:installer|install it|installing|installation|technician|"
            r"provider|engineer|repair|setup|set up|service)\b",
            text,
        )
    )


def slot_updates_from_facts(facts):
    updates = {}
    requirements = facts.get("requirements") or {}
    for key in SLOT_KEYS:
        value = requirements.get(key)
        if value not in (None, ""):
            updates[key] = value
    if facts.get("brand"):
        updates["brand"] = facts["brand"]
    return updates


def is_slot_only_followup(message, state):
    facts = extract_facts(message)
    updates = {
        key: value
        for key, value in slot_updates_from_facts(facts).items()
        if key not in {"subject", "entity_type", "transaction_type", "intent_family"}
    }
    explicit_category = facts.get("category") or facts.get("product_type")
    return bool(
        has_locked_shopping_category(state)
        and updates
        and not facts.get("subject")
        and not explicit_category
        and not is_explicit_category_change(message)
        and not is_flow_reset(message)
    )


def extract_facts(message):
    text = re.sub(r"\s+", " ", str(message or "").strip().lower())
    facts = {"requirements": {}}
    brand, category = _catalog_entities(text)
    subject = _subject_from_text(text)
    if subject:
        facts["subject"] = subject
    if brand:
        facts["brand"] = brand
    if category:
        facts["category"] = category.name
        facts["subcategory"] = category.name if category.parent_id else ""
        facts["product_type"] = category.name
        facts["catalog_category_id"] = category.id

    entity_type = _entity_type_from_text(text, subject)
    transaction_type = _transaction_type_from_text(text, entity_type)
    facts["entity_type"] = entity_type
    facts["transaction_type"] = transaction_type
    facts["intent_family"] = _intent_family(entity_type, transaction_type)

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
    participants = re.search(r"\b(?:for\s+)?(\d{1,3})\s*(?:people|persons|participants|users|seats|seaters|sitters)\b", text)
    if participants:
        facts["requirements"]["participant_count"] = int(participants.group(1))
        facts["requirements"]["capacity"] = int(participants.group(1))
    quantity = re.search(r"\b(?:quantity|qty|need|order)\s*(?:of|:|is)?\s*(\d{1,6})\s*(?:units?|items?|pieces?)?\b", text)
    if not quantity:
        quantity = re.search(r"\b(\d{1,6})\s*(?:units?|items?|pieces?|beds?|cameras?)\b", text)
    if quantity:
        facts["requirements"]["quantity"] = int(quantity.group(1))
    else:
        word_quantity = re.search(r"\b(one|two|three|four|five|six|seven|eight|nine|ten|sixteen|twenty)\s+(?:units?|items?|pieces?|beds?|cameras?|people|persons)\b", text)
        if word_quantity:
            facts["requirements"]["quantity"] = {
                "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
                "sixteen": 16, "twenty": 20,
            }[word_quantity.group(1)]

    values = _money_values(text)
    if values:
        if len(values) > 1:
            facts["requirements"]["budget_min"] = min(values)
            facts["requirements"]["minimum_budget"] = min(values)
        facts["requirements"]["budget_max"] = max(values)
        facts["requirements"]["maximum_budget"] = max(values)
        facts["requirements"]["budget_amount"] = max(values)
        money_matches = _money_matches(text)
        currency = next((item["currency"] for item in money_matches if item.get("currency")), "")
        if currency:
            facts["requirements"]["currency"] = currency
    resolution = re.search(r"\b(4k|8k|full\s*hd|1080p|720p|uhd|qhd)\b", text)
    if resolution:
        facts["requirements"]["resolution"] = resolution.group(1).replace(" ", "_")
    brightness = re.search(r"\b(\d{3,6})\s*(?:ansi\s*)?lumens?\b", text)
    if brightness:
        facts["requirements"]["brightness_requirement"] = int(brightness.group(1))
    condition = _condition_from_text(text)
    if condition:
        facts["requirements"]["condition"] = condition
    if "short throw" in text:
        facts["requirements"]["throw_distance"] = "short_throw"
    elif "ultra short throw" in text:
        facts["requirements"]["throw_distance"] = "ultra_short_throw"
    platform = next((name for name in ("zoom", "teams", "meet", "webex") if name in text), "")
    if platform:
        facts["requirements"]["platform"] = platform
    location = _location_from_text(text)
    if location:
        facts["requirements"]["delivery_location"] = location
        facts["requirements"]["location"] = location
        if transaction_type in {"repair", "install", "maintain", "inspect", "consult", "find_provider"}:
            facts["requirements"]["service_location"] = location
    use_case = re.search(r"\b(?:for|use it for|need it for)\s+(church|school|office|home|gaming|medical|business|training|conference room|boardroom)\b", text)
    if use_case:
        facts["requirements"]["use_case"] = use_case.group(1)
    if re.search(r"\b(?:conference room|conferencing|video conferencing|boardroom)\b", text):
        facts["requirements"]["service_type"] = "conference_room_setup"
        facts["requirements"]["service_needed"] = "Conference room setup"
    bedrooms = re.search(r"\b(?:two|2|three|3|four|4|five|5)\s*-?\s*bed(?:room)?s?\b", text)
    if bedrooms:
        word = bedrooms.group(0).split("-")[0].split()[0]
        facts["requirements"]["bedrooms"] = {"two": 2, "three": 3, "four": 4, "five": 5}.get(word, int(word) if word.isdigit() else None)
    year = re.search(r"\b(20\d{2}|19\d{2})\s*(?:or newer|and newer|minimum|min)?\b", text)
    if year:
        facts["requirements"]["year_min"] = int(year.group(1))
    horsepower = re.search(r"\b(?:at least\s+)?(\d{2,4})\s*(?:horsepower|hp)\b", text)
    if horsepower:
        facts["requirements"]["horsepower"] = int(horsepower.group(1))
    land_size = re.search(r"\b(\d[\d,]*)\s*(?:square\s*metres|sqm|m2|hectares?|acres?)\b", text)
    if land_size:
        facts["requirements"]["land_size"] = land_size.group(0)
    if re.search(r"\bgearbox problem\b", text):
        facts["requirements"]["fault_description"] = "gearbox problem"
    elif re.search(r"\bnot powering on\b", text):
        facts["requirements"]["fault_description"] = "not powering on"
    urgency_match = re.search(
        r"\b(this week|next week|today|tomorrow|urgent|urgently|emergency|asap|as soon as possible|immediately|very soon)\b",
        text,
    )
    if urgency_match:
        urgency = urgency_match.group(1)
        if urgency in {"urgent", "urgently", "emergency", "asap", "as soon as possible", "immediately", "very soon"}:
            urgency = "urgent"
        facts["requirements"]["urgency"] = urgency
        facts["requirements"]["preferred_date"] = facts["requirements"]["urgency"]
    fuel = re.search(r"\b(diesel|petrol|gasoline|electric|hybrid)\b", text)
    if fuel:
        facts["requirements"]["fuel_type"] = fuel.group(1)
    transmission = re.search(r"\b(automatic|manual)\b", text)
    if transmission:
        facts["requirements"]["transmission"] = transmission.group(1)
    users = re.search(r"\b(?:for\s+)?(\d[\d,]*)\s*(?:users|students|staff members|staff)\b", text)
    if users:
        facts["requirements"]["license_users"] = int(users.group(1).replace(",", ""))
    return facts


def _completed_slots(requirements):
    return sorted(key for key, value in (requirements or {}).items() if value not in (None, ""))


def _missing_slots(state):
    requirements = state.get("requirements") or {}
    transaction = state.get("transaction_type") or ""
    entity = state.get("entity_type") or ""
    missing = []
    if transaction in {"repair", "install", "maintain", "inspect", "consult", "find_provider"}:
        if not (requirements.get("service_location") or requirements.get("delivery_location") or requirements.get("location")):
            missing.append("location")
        if transaction == "repair" and not requirements.get("fault_description"):
            missing.append("problem description")
    elif entity == "property":
        if not (requirements.get("delivery_location") or requirements.get("location")):
            missing.append("location")
        if not requirements.get("budget_max"):
            missing.append("budget")
    else:
        if not requirements.get("budget_max"):
            missing.append("budget")
    return missing


def _apply_universal_state_fields(state, facts, *, explicit_change=False, reset_flow=False):
    subject = facts.get("subject") or facts.get("category") or facts.get("product_type") or ""
    can_change_subject = bool(subject and (not has_locked_shopping_category(state) or explicit_change or reset_flow))
    if can_change_subject:
        state["active_subject"] = subject
        state["search_query"] = subject
        state["shopping_category_locked"] = True
        state["locked_category"] = facts.get("category") or subject
        if facts.get("category"):
            state["active_category"] = facts["category"]
            state["category"] = facts["category"]
        if facts.get("product_type"):
            state["product_type"] = facts["product_type"]
    if facts.get("intent_family") and (can_change_subject or not state.get("intent_family")):
        state["intent_family"] = facts["intent_family"]
    if facts.get("transaction_type") and (can_change_subject or not state.get("transaction_type")):
        state["transaction_type"] = facts["transaction_type"]
    if facts.get("entity_type") and (can_change_subject or not state.get("entity_type")):
        state["entity_type"] = facts["entity_type"]
    state["active_category"] = state.get("category") or facts.get("category") or state.get("active_category", "")
    state["active_subcategory"] = state.get("subcategory") or facts.get("subcategory") or state.get("active_subcategory", "")
    if state.get("transaction_type") in {"repair", "install", "maintain", "inspect", "consult", "find_provider"}:
        state["active_service"] = state.get("transaction_type")
    requirements = state.get("requirements") or {}
    state["budget"] = {
        "amount": requirements.get("budget_amount") or requirements.get("budget_max"),
        "min": requirements.get("budget_min"),
        "max": requirements.get("budget_max"),
        "currency": requirements.get("currency"),
    }
    state["location"] = {
        "delivery": requirements.get("delivery_location"),
        "service": requirements.get("service_location"),
        "value": requirements.get("location") or requirements.get("delivery_location") or requirements.get("service_location"),
    }
    state["completed_slots"] = _completed_slots(requirements)
    state["missing_slots"] = _missing_slots(state)
    state["conversation_stage"] = "ready_to_search" if state.get("active_subject") else "needs_subject"


def prepare_context(conversation, message):
    context = dict(conversation.context or {})
    state = normalized_state(conversation)
    facts = extract_facts(message)
    if _active_service_flow(state) and not _explicit_product_request(message):
        facts["entity_type"] = "service_provider"
        facts["intent_family"] = "service"
        facts["transaction_type"] = (
            "install"
            if re.search(r"\binstall(?:er|ation|ing)?|setup|set up\b", str(message or "").lower())
            else facts.get("transaction_type") or state.get("transaction_type") or "find_provider"
        )
        facts.pop("category", None)
        facts.pop("subcategory", None)
        facts.pop("product_type", None)
        facts.pop("catalog_category_id", None)
        fact_requirements = facts.setdefault("requirements", {})
        if fact_requirements.get("delivery_location") and not fact_requirements.get("service_location"):
            fact_requirements["service_location"] = fact_requirements["delivery_location"]
    contextual_budget_values = (
        _contextual_budget_values(message)
        if has_locked_shopping_category(state)
        else []
    )
    if contextual_budget_values and not facts["requirements"].get("budget_max"):
        if len(contextual_budget_values) > 1:
            facts["requirements"]["budget_min"] = min(contextual_budget_values)
            facts["requirements"]["minimum_budget"] = min(contextual_budget_values)
        facts["requirements"]["budget_max"] = max(contextual_budget_values)
        facts["requirements"]["maximum_budget"] = max(contextual_budget_values)
        facts["requirements"]["budget_amount"] = max(contextual_budget_values)
    previous_category = shopping_category_label(state)
    explicit_change = is_explicit_category_change(message)
    reset_flow = is_flow_reset(message)

    if explicit_change and facts.get("subject") and has_locked_shopping_category(state):
        replacement = (
            Category.objects.filter(is_active=True, name__iexact=facts["subject"])
            .select_related("parent")
            .first()
        )
        if replacement:
            facts["category"] = replacement.name
            facts["product_type"] = replacement.name
            facts["subcategory"] = replacement.name if replacement.parent_id else ""
            facts["catalog_category_id"] = replacement.id
        else:
            facts.pop("category", None)
            facts.pop("product_type", None)
            facts.pop("subcategory", None)
            facts.pop("catalog_category_id", None)

    if reset_flow:
        state["shopping_category_locked"] = False
        state["locked_category"] = ""
        state["active_subject"] = ""
        state["search_query"] = ""
        state["requirements"] = {}

    for key in (
        "brand", "category", "subcategory", "product_type", "catalog_category_id",
    ):
        if facts.get(key) not in (None, "") and (
            key not in {"category", "subcategory", "product_type", "catalog_category_id"}
            or not has_locked_shopping_category(state)
            or explicit_change
            or reset_flow
        ):
            state[key] = facts[key]
    if facts.get("category") and (not previous_category or explicit_change or reset_flow):
        state["shopping_category_locked"] = True
        state["locked_category"] = facts["category"]
    for key, value in facts["requirements"].items():
        if value not in (None, ""):
            state["requirements"][key] = value
            if key == "brand":
                state["brand"] = value
    if (
        state.get("transaction_type") in {"repair", "install", "maintain", "inspect", "consult", "find_provider"}
        and state["requirements"].get("delivery_location")
        and not state["requirements"].get("service_location")
    ):
        state["requirements"]["service_location"] = state["requirements"]["delivery_location"]
    if state.get("entity_type") == "property" and re.search(
        r"\b(?:rent|lease|yearly|per year|per annum|annual|annually)\b",
        str(message or "").lower(),
    ):
        state["transaction_type"] = "rent"
    slot_updates = slot_updates_from_facts(facts)
    _apply_universal_state_fields(
        state,
        facts,
        explicit_change=explicit_change,
        reset_flow=reset_flow,
    )
    state["previous_intent"] = state.get("intent") or conversation.current_intent or context.get("last_intent", "")
    derived_subject = (
        state.get("current_product_name")
        or shopping_category_label(state)
        or " ".join(part for part in (state.get("brand"), state.get("product_type")) if part)
        or state.get("category")
        or state.get("last_topic")
    )
    if str(derived_subject or "").strip().lower() in {"", "general_marketplace"}:
        derived_subject = ""
    state["active_subject"] = derived_subject
    state["last_slot_updates"] = slot_updates
    state["explicit_subject_change"] = explicit_change or reset_flow
    state["last_user_message_type"] = "slot_update" if slot_updates else "subject_or_intent"
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
        "intent_family": state.get("intent_family", ""),
        "transaction_type": state.get("transaction_type", ""),
        "entity_type": state.get("entity_type", ""),
        "search_query": state.get("search_query", ""),
        "active_service": state.get("active_service", ""),
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
