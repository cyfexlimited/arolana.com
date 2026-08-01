import re
from decimal import Decimal

from arolana_payments.services import get_gateway_options
from django.db.models import Q

from products.models import Category, Product
from .models import AIKnowledgeBase, AITrainingData
from .product_intelligence import product_facts, product_intelligence_reply


GREETING = "greeting"
PRODUCT_SEARCH = "product_search"
PRODUCT_DETAILS = "product_details"
PRODUCT_RECOMMENDATION = "product_recommendation"
PRODUCT_COMPARISON = "product_comparison"
PRODUCT_COMPATIBILITY = "product_compatibility"
PRODUCT_PURCHASE = "product_purchase"
PAYMENT_QUESTION = "payment_question"
DELIVERY_QUESTION = "delivery_question"
ORDER_TRACKING = "order_tracking"
PROPERTY_INQUIRY = "property_inquiry"
CAR_INQUIRY = "car_inquiry"
FOOD_INQUIRY = "food_inquiry"
KITCHEN_ITEM_INQUIRY = "kitchen_item_inquiry"
ART_INQUIRY = "art_inquiry"
SERVICE_INQUIRY = "service_inquiry"
VENDOR_INQUIRY = "vendor_inquiry"
QUOTATION_REQUEST = "quotation_request"
BULK_ORDER = "bulk_order"
WARRANTY_QUESTION = "warranty_question"
RETURN_REFUND = "return_refund"
SUPPORT_REQUEST = "support_request"
HUMAN_HANDOVER = "human_handover"
FOLLOW_UP_QUESTION = "follow_up_question"
CONFUSED_OR_COMPLAINT = "confused_or_complaint"
GENERAL_CONVERSATION = "general_conversation"

PRODUCT_CARD_INTENTS = {
    PRODUCT_SEARCH,
    PRODUCT_DETAILS,
    PRODUCT_RECOMMENDATION,
    PRODUCT_COMPARISON,
    PRODUCT_COMPATIBILITY,
    PROPERTY_INQUIRY,
    CAR_INQUIRY,
    FOOD_INQUIRY,
    KITCHEN_ITEM_INQUIRY,
    ART_INQUIRY,
    SERVICE_INQUIRY,
}

MARKETPLACE_ROUTES = {
    "property": ("property", "properties", "house", "apartment", "land", "rent", "real estate"),
    "vehicle": ("car", "cars", "vehicle", "toyota", "honda", "suv", "sedan", "truck"),
    "food": ("food", "grocery", "groceries", "restaurant", "meal", "rice", "beverage"),
    "home_kitchen": ("kitchen", "cookware", "utensil", "home appliance", "furniture"),
    "art": ("art", "painting", "sculpture", "wall art", "artwork", "canvas"),
    "fashion": ("fashion", "clothing", "dress", "shirt", "shoe", "bag", "jewelry"),
    "industrial": ("industrial", "machinery", "equipment", "factory", "generator", "tool"),
    "service": (
        "service", "installation", "installer", "installers", "install",
        "repair", "maintenance", "consulting", "technician", "provider",
        "engineer", "setup", "set up",
    ),
    "vendor": ("vendor", "manufacturer", "supplier", "wholesaler", "distributor"),
    "technology": (
        "technology", "electronics", "electrical", "smart home", "networking",
        "audio visual", "surveillance", "phone", "computer", "laptop", "camera",
    ),
}

STRONG_CATEGORY_SIGNALS = {
    "video_conferencing": (
        "video conferencing", "conference device", "conferencing device",
        "meeting room camera", "meeting room", "boardroom device", "boardroom",
        "speakerphone", "logitech group", "logitech rally", "zoom room",
        "teams room", "hybrid meeting", "online meeting", "conferencing",
        "conference",
    ),
    "vehicle": (
        "car", "vehicle", "toyota", "benz", "camry", "suv", "mileage",
    ),
    "art": (
        "painting", "wall art", "sculpture", "canvas", "artwork", "drawing",
        "portrait",
    ),
    "property": (
        "house", "apartment", "land", "property", "real estate", "rent a",
        "buy a house",
    ),
}

LOCKED_CATEGORY_LABELS = {
    "video_conferencing": "Technology / Audio Visual / Video Conferencing",
    "vehicle": "Vehicles",
    "art": "Art",
    "property": "Properties",
}


def _text(value):
    value = str(value or "").replace("’", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", value.strip().lower())


def _contains(text, phrases):
    return any(phrase in text for phrase in phrases)


def _route_term_present(text, term):
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text))


def _tokenize(value):
    return {
        token
        for token in re.findall(r"[a-z0-9]+", _text(value))
        if len(token) > 1
    }


def _strong_category_signal(message):
    text = _text(message)
    matches = {
        route: [term for term in terms if _route_term_present(text, term)]
        for route, terms in STRONG_CATEGORY_SIGNALS.items()
    }
    matches = {route: terms for route, terms in matches.items() if terms}
    if not matches:
        return "", []
    return max(
        matches.items(),
        key=lambda item: max(len(term) for term in item[1]) + len(item[1]) * 5,
    )


def _category_for_signal(route):
    if route == "video_conferencing":
        phrases = ("video conferencing", "audio visual", "conferencing")
    else:
        phrases = STRONG_CATEGORY_SIGNALS.get(route, ())
    category_query = Q()
    for phrase in phrases:
        category_query |= (
            Q(name__icontains=phrase)
            | Q(description__icontains=phrase)
            | Q(meta_keywords__icontains=phrase)
        )
    return (
        Category.objects.filter(category_query, is_active=True)
        .select_related("parent")
        .order_by("parent_id", "name")
        .first()
        if category_query else None
    )


def _database_category_match(message):
    text = _text(message)
    tokens = _tokenize(text)
    best_category = None
    best_score = Decimal("0")
    matched_terms = []

    categories = Category.objects.filter(is_active=True).select_related("parent").only(
        "id", "name", "slug", "description", "meta_keywords", "parent__name",
    )
    for category in categories:
        name = _text(category.name)
        parent_name = _text(category.parent.name if category.parent else "")
        category_tokens = _tokenize(
            f"{category.name} {parent_name} {category.description} {category.meta_keywords}"
        )
        overlap = tokens & category_tokens
        score = Decimal("0")
        if name and name in text:
            score += Decimal("0.75")
        if parent_name and parent_name in text:
            score += Decimal("0.25")
        if tokens:
            score += Decimal(str(min(len(overlap) / len(tokens), 1))) * Decimal("0.55")
        if score > best_score:
            best_category = category
            best_score = score
            matched_terms = sorted(overlap)

    if best_category and best_score >= Decimal("0.35"):
        return best_category, matched_terms, min(best_score, Decimal("0.99"))

    product_query = Q()
    for token in list(tokens)[:8]:
        product_query |= (
            Q(name__icontains=token)
            | Q(brand__name__icontains=token)
            | Q(category__name__icontains=token)
        )
    product_match = (
        Product.objects.filter(
            product_query,
            is_active=True,
            approval_status="approved",
        ).select_related("category").first()
        if product_query else None
    )
    if product_match:
        return product_match.category, [product_match.name], Decimal("0.90")
    return None, [], Decimal("0")


def _knowledge_category_match(message):
    tokens = _tokenize(message)
    if not tokens:
        return "", [], Decimal("0")
    best_category = ""
    best_terms = []
    best_score = Decimal("0")
    querysets = (
        AIKnowledgeBase.objects.filter(approved=True, is_active=True),
        AITrainingData.objects.filter(approved=True, is_active=True),
    )
    for queryset in querysets:
        for item in queryset.only("category", "keywords")[:500]:
            candidate_tokens = _tokenize(f"{item.category} {item.keywords}")
            overlap = tokens & candidate_tokens
            if not overlap:
                continue
            score = Decimal(str(len(overlap) / len(tokens)))
            if score > best_score:
                best_category = item.category
                best_terms = sorted(overlap)
                best_score = score
    return best_category, best_terms, min(best_score, Decimal("0.85"))


def _marketplace_style(value):
    text = _text(value)
    # Broad words such as "meeting room" can appear in projector, furniture, and
    # office-equipment descriptions. Only lock the catalog route here when the
    # category data itself carries an unambiguous conferencing signal.
    if any(_route_term_present(text, term) for term in (
        "video conferencing", "conference equipment", "conference camera",
        "conference microphone", "conferencing system", "zoom room", "teams room",
        "logitech group", "logitech rally",
    )):
        return "video_conferencing"
    for route, terms in MARKETPLACE_ROUTES.items():
        if any(_route_term_present(text, term) for term in terms):
            return route
    return "general_marketplace"


def detect_marketplace_category(message, conversation=None):
    explicit_route, explicit_terms = _strong_category_signal(message)
    context = dict(getattr(conversation, "context", {}) or {})
    locked_route = context.get("current_category_locked", "")
    locked_label = context.get("locked_category_label", "")

    if explicit_route:
        category = _category_for_signal(explicit_route)
        return {
            "marketplace_category": (
                LOCKED_CATEGORY_LABELS.get(explicit_route)
                or getattr(category, "name", explicit_route)
            ),
            "marketplace_style": explicit_route,
            "catalog_category_id": getattr(category, "id", None),
            "catalog_category_name": getattr(category, "name", ""),
            "matched_terms": explicit_terms,
            "confidence": Decimal("0.99"),
            "source": "high_confidence_category_signal",
        }

    if locked_route:
        return {
            "marketplace_category": locked_label or LOCKED_CATEGORY_LABELS.get(
                locked_route, locked_route,
            ),
            "marketplace_style": locked_route,
            "catalog_category_id": context.get("locked_catalog_category_id"),
            "catalog_category_name": context.get("locked_catalog_category_name", ""),
            "matched_terms": ["conversation category lock"],
            "confidence": Decimal("0.96"),
            "source": "conversation_category_lock",
        }

    category, matched_terms, confidence = _database_category_match(message)
    if category:
        return {
            "marketplace_category": category.name,
            "marketplace_style": _marketplace_style(
                f"{category.name} {category.parent.name if category.parent else ''} "
                f"{category.description} {category.meta_keywords}"
            ),
            "catalog_category_id": category.id,
            "catalog_category_name": category.name,
            "matched_terms": matched_terms,
            "confidence": confidence,
            "source": "active_category_database",
        }

    knowledge_category, knowledge_terms, knowledge_confidence = _knowledge_category_match(message)
    if knowledge_category:
        return {
            "marketplace_category": knowledge_category,
            "marketplace_style": _marketplace_style(knowledge_category),
            "catalog_category_id": None,
            "catalog_category_name": "",
            "matched_terms": knowledge_terms,
            "confidence": knowledge_confidence,
            "source": "approved_knowledge_database",
        }

    text = _text(message)
    matches = {
        route: [term for term in terms if _route_term_present(text, term)]
        for route, terms in MARKETPLACE_ROUTES.items()
    }
    matches = {route: terms for route, terms in matches.items() if terms}
    if matches:
        route, terms = max(matches.items(), key=lambda item: len(item[1]))
        confidence = min(
            Decimal("0.65") + Decimal("0.08") * len(terms),
            Decimal("0.98"),
        )
        return {
            "marketplace_category": route,
            "marketplace_style": route,
            "catalog_category_id": None,
            "catalog_category_name": "",
            "matched_terms": terms,
            "confidence": confidence,
            "source": "semantic_fallback",
        }

    product = getattr(conversation, "product", None)
    category_text = _text(getattr(getattr(product, "category", None), "name", ""))
    for route, terms in MARKETPLACE_ROUTES.items():
        matched = [term for term in terms if _route_term_present(category_text, term)]
        if matched:
            return {
                "marketplace_category": getattr(product.category, "name", route),
                "marketplace_style": route,
                "catalog_category_id": getattr(product, "category_id", None),
                "catalog_category_name": getattr(product.category, "name", ""),
                "matched_terms": matched,
                "confidence": Decimal("0.82"),
                "source": "conversation_product_category",
            }
    return {
        "marketplace_category": "general_marketplace",
        "marketplace_style": "general_marketplace",
        "catalog_category_id": None,
        "catalog_category_name": "",
        "matched_terms": [],
        "confidence": Decimal("0.40"),
        "source": "general_fallback",
    }


def detect_chat_intent(message, conversation=None):
    text = _text(message)
    has_product = bool(getattr(conversation, "product_id", None))
    context = dict(getattr(conversation, "context", {}) or {})
    state = dict(context.get("state") or {})

    active_service_workflow = (
        state.get("entity_type") == "service_provider"
        or state.get("intent_family") == "service"
        or state.get("transaction_type") in {
            "repair", "install", "maintain", "inspect", "consult", "find_provider",
        }
        or context.get("marketplace_category") == "service"
    )
    generic_help_followup = bool(re.fullmatch(
        r"(?:please\s+)?(?:do\s+)?(?:help|help me|assist|assist me)(?:\s+please)?[.!?]*",
        text,
    ))
    if active_service_workflow and generic_help_followup:
        return SERVICE_INQUIRY

    if _contains(text, (
        "you are not helping", "you're not helping", "you are not saying anything",
        "you're not saying anything", "not saying anything", "this is frustrating",
        "not answering", "same answer", "stop repeating", "complaint",
    )):
        return CONFUSED_OR_COMPLAINT
    if _contains(text, (
        "human", "real person", "live agent", "customer care", "call me",
        "speak to someone", "talk to someone", "connect me to support",
    )):
        return HUMAN_HANDOVER
    if text in {
        "hi", "hello", "hey", "good morning", "good afternoon", "good evening",
        "are you there", "you there", "you there?", "hello?",
    }:
        return GREETING
    if _contains(text, ("track my order", "order status", "tracking", "where is my order")):
        return ORDER_TRACKING
    if _contains(text, ("refund", "return item", "return this", "money back", "wrong item", "damaged item")):
        return RETURN_REFUND
    if _contains(text, ("quotation", "request quote", "send quote", "rfq", "formal quote")):
        return QUOTATION_REQUEST
    if _contains(text, ("bulk order", "wholesale order", "large quantity", "buy in bulk", "moq")):
        return BULK_ORDER
    if _contains(text, (
        "payment", "paystack", "flutterwave", "stripe", "paypal", "bank transfer",
        "pay on delivery", "payment option", "payment method", "how can i pay",
    )):
        return PAYMENT_QUESTION
    if _contains(text, (
        "delivery", "shipping", "dispatch", "how long will it take",
        "when will it arrive", "deliver to", "delivery fee",
    )):
        return DELIVERY_QUESTION
    if _contains(text, (
        "how do i get it", "how can i get it", "how do i buy", "how can i buy",
        "what do i need to do", "add to cart", "checkout", "place my order",
        "place an order", "purchase it", "buy it", "order it",
    )):
        return PRODUCT_PURCHASE
    if _contains(text, ("warranty", "guarantee", "coverage period")):
        return WARRANTY_QUESTION
    if _contains(text, ("compare", "versus", " vs ", "difference between", "which is better")):
        return PRODUCT_COMPARISON
    if _contains(text, ("compatible", "compatibility", "work with", "works with", "support my")):
        return PRODUCT_COMPATIBILITY
    if _contains(text, ("recommend", "suggest", "best for", "which should i", "help me choose")):
        return PRODUCT_RECOMMENDATION

    category_route = detect_marketplace_category(message, conversation)
    marketplace_category = category_route["marketplace_style"]
    if marketplace_category == "video_conferencing":
        if _contains(text, (
            "function", "what does", "what is this", "where can i use",
            "where is it used", "use this", "used for",
        )):
            return PRODUCT_DETAILS if has_product else PRODUCT_RECOMMENDATION
        if _contains(text, ("looking for", "need a", "recommend", "suggest")):
            return PRODUCT_RECOMMENDATION
        if re.fullmatch(r"[\s₦n$,\d.-]+", text) and context.get("current_category_locked"):
            return PRODUCT_RECOMMENDATION
    specialized_intents = {
        "property": PROPERTY_INQUIRY,
        "vehicle": CAR_INQUIRY,
        "food": FOOD_INQUIRY,
        "home_kitchen": KITCHEN_ITEM_INQUIRY,
        "art": ART_INQUIRY,
        "service": SERVICE_INQUIRY,
        "vendor": VENDOR_INQUIRY,
    }
    if marketplace_category in specialized_intents:
        return specialized_intents[marketplace_category]
    if category_route["source"] == "active_category_database":
        return PRODUCT_SEARCH
    if _contains(text, (
        "specification", "specifications", "specs", "features", "reviews", "ratings",
        "accessories", "tell me more", "more about", "details",
    )):
        return PRODUCT_DETAILS if has_product else PRODUCT_SEARCH
    if _contains(text, (
        "find", "search", "show me", "do you have", "in stock", "price of",
        "tell me about",
    )):
        return PRODUCT_SEARCH
    if _contains(text, ("support", "agent", "i need help", "help me")):
        return SUPPORT_REQUEST
    if has_product and (
        " it" in f" {text}"
        or text in {"it", "this", "that", "the product", "this product", "that product"}
        or "this product" in text
        or _contains(text, ("i love it", "i like it", "looks good", "great choice"))
        or text.startswith(("what about", "how about", "does it", "is it", "can it"))
    ):
        return FOLLOW_UP_QUESTION
    return GENERAL_CONVERSATION


def _money(value):
    try:
        return f"₦{Decimal(str(value or 0)):,.2f}"
    except Exception:
        return f"₦{value}"


def _current_product_context(conversation):
    product = getattr(conversation, "product", None)
    return (product, product_facts(product)) if product else (None, {})


def _purchase_reply(conversation):
    product, facts = _current_product_context(conversation)
    if not product:
        return (
            "Tell me which item you want. I’ll check its current price and availability, "
            "then guide you through checkout or a quote request."
        )
    stock_text = "in stock" if facts.get("is_in_stock") else "not currently listed as in stock"
    estimate = facts.get("delivery", {}).get("estimate") or "calculated from your delivery location"
    return (
        f"Great choice. {product.name} is {stock_text} at {_money(product.price)}. "
        "Click Add to Cart, open your cart, enter your delivery details, choose an available "
        f"payment method, and place your order. Delivery is {estimate}."
    )


def _payment_reply(conversation):
    options = [
        option["display_name"]
        for option in get_gateway_options()
        if option.get("available")
    ]
    payment_text = (
        f"The payment options currently available on Arolana include {', '.join(options)}."
        if options
        else "Payment options are shown at checkout based on the methods currently enabled by Arolana."
    )
    product_name = getattr(getattr(conversation, "product", None), "name", "the item")
    return (
        f"{payment_text} Add {product_name} to your cart and continue to checkout to see "
        "the methods available for your order."
    )


def _delivery_reply(conversation):
    product, facts = _current_product_context(conversation)
    if not product:
        return (
            "Delivery time and cost depend on the listing, vendor, package size, and destination. "
            "Tell me the item and delivery location, and I’ll check the information listed on Arolana."
        )
    delivery = facts.get("delivery", {})
    estimate = delivery.get("estimate")
    lead_days = delivery.get("lead_time_days")
    if not estimate and lead_days:
        estimate = f"about {lead_days} day{'s' if lead_days != 1 else ''}"
    estimate = estimate or "calculated from your address during checkout"
    fee_text = (
        "Free shipping is listed."
        if delivery.get("free_shipping")
        else "The delivery fee is calculated from your location and fulfilment option."
    )
    return f"Delivery for {product.name} is {estimate}. {fee_text}"


def route_chat_response(conversation, message):
    intent = detect_chat_intent(message, conversation)
    category_route = detect_marketplace_category(
        message,
        conversation,
    )
    route_metadata = {
        "marketplace_category": category_route["marketplace_category"],
        "marketplace_style": category_route["marketplace_style"],
        "catalog_category_id": category_route["catalog_category_id"],
        "catalog_category_name": category_route["catalog_category_name"],
        "category_matched_terms": category_route["matched_terms"],
        "category_confidence": float(category_route["confidence"]),
        "category_route_source": category_route["source"],
    }

    if intent == GREETING:
        return intent, (
            "Yes, I’m here. I can help you shop, compare products, track orders, "
            "request a quote, or connect you with Arolana support."
        ), route_metadata, False
    if intent == PRODUCT_PURCHASE:
        return intent, _purchase_reply(conversation), route_metadata, False
    if intent == PAYMENT_QUESTION:
        return intent, _payment_reply(conversation), route_metadata, False
    if intent == DELIVERY_QUESTION:
        return intent, _delivery_reply(conversation), route_metadata, False
    if intent == ORDER_TRACKING:
        return intent, (
            "Send your order number or tracking code. If you are logged in, I can help check "
            "your order without exposing another customer’s information."
        ), route_metadata, False
    if intent == RETURN_REFUND:
        return intent, (
            "I’m sorry there is a problem with the order. Refunds and returns need secure "
            "order verification, so I’ve connected this conversation to Arolana support."
        ), route_metadata, True
    if intent in {QUOTATION_REQUEST, BULK_ORDER}:
        product_name = getattr(getattr(conversation, "product", None), "name", "the item")
        return intent, (
            f"I can help request a quote for {product_name}. Send the quantity, budget, "
            "delivery location, and required date. Staff or the vendor will confirm price and lead time."
        ), route_metadata, True
    if intent == WARRANTY_QUESTION:
        product, facts = _current_product_context(conversation)
        warranty = facts.get("warranty", {}) if product else {}
        if warranty.get("duration"):
            return intent, (
                f"{product.name} lists a warranty of {warranty['duration']}. "
                f"{warranty.get('description') or 'Open the product page for its listed coverage terms.'}"
            ), route_metadata, False
        return intent, (
            "I don’t have a confirmed warranty term for this item yet. "
            "I’ll connect you with Arolana support so the vendor can confirm it."
        ), route_metadata, True
    if intent == FOLLOW_UP_QUESTION and conversation.product:
        return intent, (
            f"We’re discussing {conversation.product.name}. I can help you buy it, check delivery, "
            "explain payment options, compare it, or confirm compatibility."
        ), route_metadata, False
    if intent == PRODUCT_DETAILS and conversation.product and _contains(
        _text(message),
        ("function", "what does", "where can i use", "where is it used", "used for"),
    ):
        facts = product_facts(conversation.product)
        description = facts.get("description") or facts.get("specifications") or ""
        if route_metadata["marketplace_style"] == "video_conferencing":
            if "where" in _text(message) or "use" in _text(message):
                reply = (
                    f"You can use {conversation.product.name} in boardrooms, meeting rooms, "
                    "classrooms, training rooms, churches, conference halls, Zoom or Teams "
                    "meetings, and hybrid work spaces."
                )
            else:
                reply = (
                    f"{conversation.product.name} is used for video conferencing. It helps people "
                    "in a room see, hear, and speak clearly during online or hybrid meetings."
                )
            if description:
                reply += " This is based on the product information listed on Arolana."
            return intent, reply, route_metadata, False
    if intent in {HUMAN_HANDOVER, SUPPORT_REQUEST, CONFUSED_OR_COMPLAINT}:
        reply = (
            "Sorry about that. I’m here. Do you want help buying this item, checking delivery, "
            "confirming payment options, or speaking with support? I’ve also alerted Arolana support."
            if intent == CONFUSED_OR_COMPLAINT
            else "I’ve alerted Arolana support. A real person can continue with you in this chat."
        )
        return intent, reply, route_metadata, True
    if intent in PRODUCT_CARD_INTENTS:
        catalog_label = " ".join(
            str(value or "").lower()
            for value in (
                route_metadata.get("catalog_category_name"),
                route_metadata.get("marketplace_category"),
                route_metadata.get("marketplace_style"),
            )
        )
        under_specified_projector_use_case = (
            (
                "projector" in catalog_label
                or "projector" in _text(message).lower()
            )
            and not re.search(r"\b(?:budget|under|below|around|about|₦|ngn|naira|n\s*\d|\d[\d,]*\s*(?:k|m|million|thousand))\b", _text(message))
            and _contains(
                _text(message),
                ("church", "hall", "classroom", "boardroom", "meeting room", "conference room"),
            )
        )
        if under_specified_projector_use_case:
            metadata = {
                **route_metadata,
                "source_type": "clarification",
                "source_label": "Projector requirement clarification",
            }
            return intent, (
                "Sure. What budget should I work with for the projector?"
            ), metadata, False

        if (
            route_metadata["marketplace_style"] == "video_conferencing"
            and not conversation.product_id
            and not re.search(r"\d", _text(message))
            and not _contains(_text(message), ("logitech group", "logitech rally", "budget"))
        ):
            return intent, (
                "Sure. Is it for a small room, boardroom, classroom, church, or conference hall? "
                "What is your budget?"
            ), route_metadata, False
        use_current = intent != PRODUCT_SEARCH or not _contains(
            _text(message),
            ("find", "search", "show me", "do you have", "tell me about"),
        )
        result = product_intelligence_reply(
            conversation,
            message,
            use_current_product=use_current,
        )
        if result:
            reply, metadata = result
            metadata = {**route_metadata, **metadata}
            needs_handoff = metadata.get("source_type") == "product_database_missing_spec"
            return intent, reply, metadata, needs_handoff

        qualifier_replies = {
            PROPERTY_INQUIRY: "Sure. Are you looking to rent or buy, what location do you prefer, and what is your budget?",
            CAR_INQUIRY: (
                "Sure. For the vehicle rental, what passenger capacity, pickup location, "
                "rental date, and budget do you have?"
                if re.search(r"\b(?:rent|rental|hire)\b", _text(message))
                else "Sure. What year range, budget, condition, and location do you prefer?"
            ),
            FOOD_INQUIRY: "Sure. Are you looking for groceries, restaurant meals, bulk food supply, or packaged food?",
            KITCHEN_ITEM_INQUIRY: "What kitchen item do you need, what size or capacity, and what budget should I work with?",
            ART_INQUIRY: "Nice. Do you prefer wall art, paintings, sculptures, prints, or custom artwork, and what is your budget?",
            SERVICE_INQUIRY: "What service do you need, where is it required, and when do you need it completed?",
        }
        if intent in qualifier_replies:
            return intent, qualifier_replies[intent], route_metadata, False
    if intent == VENDOR_INQUIRY:
        return intent, (
            "I can help you find a verified vendor, manufacturer, wholesaler, distributor, "
            "or service provider. Tell me the item or service, quantity, and delivery location."
        ), route_metadata, False
    return intent, "", route_metadata, False


def update_conversation_context(conversation, intent, reply, metadata=None):
    from .context_state import normalized_state

    context = dict(conversation.context or {})
    product = getattr(conversation, "product", None)

    if not getattr(product, "id", None) and metadata:
        product_ref = metadata.get("source_object_id")

        if not product_ref:
            product_cards = metadata.get("product_cards") or []
            if product_cards:
                product_ref = product_cards[0].get("id")

        if product_ref:
            product_query = (
                Q(slug=str(product_ref))
                | Q(sku=str(product_ref))
            )

            if (
                isinstance(product_ref, int)
                or str(product_ref).strip().isdigit()
            ):
                product_query |= Q(pk=int(product_ref))

            product = (
                Product.objects
                .filter(
                    product_query,
                    approval_status="approved",
                    is_active=True,
                )
                .select_related("brand", "category")
                .first()
            )

            if product:
                conversation.product = product
                conversation.save(
                    update_fields=["product", "updated_at"]
                )
    recent_user_message = (
        conversation.messages.filter(
            sender_type="user",
            is_private_note=False,
        ).order_by("-created_at").values_list("message", flat=True).first()
        or ""
    )
    message_text = _text(recent_user_message)
    message_is_phone_number = bool(
        re.fullmatch(r"(?:\+?234|0)\d{10}", message_text.strip())
    )
    budget_match = re.search(
        r"\b(?:budget|under|below|around)\s*(?:is\s*)?[₦n$]?\s*([\d,]+(?:\.\d+)?)",
        message_text,
    )
    room_match = re.search(
        r"\b(small|medium|large)\s+(?:room|hall|church|office|space)\b",
        message_text,
    )
    location_match = re.search(
        r"\b(?:deliver(?:ed|y)?\s+to|located in|i am in|i'm in|in)\s+([a-z][a-z\s-]{2,60})",
        message_text,
    )
    use_case_match = re.search(
        r"\b(?:for|use it for|need it for)\s+"
        r"(church|school|office|home|gaming|medical|business|training|boardroom|classroom)\b",
        message_text,
    )
    marketplace_category = (metadata or {}).get(
        "marketplace_category",
        context.get("marketplace_category", "general_marketplace"),
    )
    marketplace_style = (metadata or {}).get("marketplace_style", "")

    # Prefer a canonical marketplace style. Compatibility metadata may carry a
    # free-text label such as "conferencing device"; the strong-signal router
    # converts that back to "video_conferencing".
    explicit_style, _explicit_terms = _strong_category_signal(
        " ".join(
            str(value or "")
            for value in (
                message_text,
                marketplace_style,
                marketplace_category,
                (metadata or {}).get("active_subject"),
                (metadata or {}).get("search_query"),
            )
        )
    )
    if explicit_style:
        marketplace_style = explicit_style

    if marketplace_style in {
        "property", "vehicle", "food", "home_kitchen", "art", "fashion",
        "industrial", "service", "vendor", "technology",
    }:
        marketplace_category = marketplace_style
    topic_label = (
        (metadata or {}).get("route")
        if (metadata or {}).get("source_type") == "platform_database"
        else marketplace_category
    ) or marketplace_category
    context.update({
        "current_product_id": getattr(product, "id", None),
        "current_product_name": getattr(product, "name", ""),
        "current_property_id": context.get("current_property_id"),
        "current_vehicle_id": context.get("current_vehicle_id"),
        "current_brand": getattr(getattr(product, "brand", None), "name", ""),
        "current_category": (
            (metadata or {}).get("catalog_category_name")
            or context.get("current_category", "")
            or getattr(getattr(product, "category", None), "name", "")
        ),
        "marketplace_category": marketplace_category,
        "last_intent": intent,
        "last_topic": topic_label,
        "last_bot_response_summary": re.sub(r"\s+", " ", reply or "")[:500],
        "customer_name": conversation.customer_display,
        "support_status": conversation.status,
    })
    category_confidence = Decimal(str((metadata or {}).get("category_confidence") or 0))
    should_lock_category = (
        marketplace_style == "video_conferencing"
        or (
            marketplace_style
            and marketplace_style != "general_marketplace"
            and category_confidence >= Decimal("0.90")
        )
    )
    if should_lock_category:
        context["current_category_locked"] = marketplace_style
        context["locked_category_label"] = marketplace_category
        context["locked_catalog_category_id"] = (metadata or {}).get("catalog_category_id")
        context["locked_catalog_category_name"] = (metadata or {}).get(
            "catalog_category_name", "",
        )
    if budget_match and not message_is_phone_number:
        context["user_budget"] = budget_match.group(1).replace(",", "")
    elif not message_is_phone_number and context.get("current_category_locked") and re.fullmatch(
        r"[\s₦n$,\d.-]+", message_text,
    ):
        budget_values = re.findall(r"\d[\d,]{3,}", message_text)
        if budget_values:
            context["user_budget"] = " - ".join(
                value.replace(",", "") for value in budget_values[:2]
            )
    if room_match:
        context["room_size"] = room_match.group(0)
    if location_match:
        context["user_location"] = location_match.group(1).strip(" .,!?:;")
        if "deliver" in message_text:
            context["delivery_location"] = context["user_location"]
    if use_case_match:
        context["use_case"] = use_case_match.group(1).strip(" .,!?:;")
    if (
        metadata
        and str(metadata.get("source_type", "")).startswith("product_database")
        and metadata.get("source_object_id")
    ):
        context["current_product_id"] = metadata["source_object_id"]
    state = normalized_state(conversation)
    structured_requirements = (
        (metadata or {}).get("structured_requirements")
        or ((metadata or {}).get("structured_response") or {}).get("structured_requirements")
        or {}
    )
    if isinstance(structured_requirements, dict):
        requirements = dict(state.get("requirements") or {})
        for key, value in structured_requirements.items():
            if value not in (None, ""):
                requirements[key] = value
        state["requirements"] = requirements
    state["previous_intent"] = state.get("intent") or context.get("last_intent", "")
    state["intent"] = intent
    state["last_topic"] = topic_label
    metadata_subject = (metadata or {}).get("active_subject") or (metadata or {}).get("search_query")
    previous_subject = state.get("active_subject", "")
    if metadata_subject:
        state["active_subject"] = metadata_subject
    elif (metadata or {}).get("source_type") == "deterministic_conversation":
        state["active_subject"] = previous_subject
    else:
        state["active_subject"] = (
            getattr(product, "name", "")
            or state.get("active_subject")
            or " ".join(
                value for value in (state.get("brand"), state.get("product_type")) if value
            )
        )
    compatibility_state = (
        (metadata or {}).get("shopping_session")
        or (metadata or {}).get("state")
        or {}
    )
    clear_requirements = bool(
        (metadata or {}).get("topic_changed")
        or (metadata or {}).get("_clear_legacy_requirements")
        or (
            isinstance(compatibility_state, dict)
            and compatibility_state.get("_clear_legacy_requirements")
        )
    )
    explicit_new_subject = bool(
        metadata_subject
        and previous_subject
        and _text(metadata_subject) != _text(previous_subject)
        and (metadata or {}).get("intent") != "services.match_providers"
        and re.search(
            r"^(?:do you have|show me|find me|search for|i need|i want|"
            r"i am looking for|i'm looking for|looking for)\b",
            message_text,
        )
    )
    if clear_requirements or explicit_new_subject:
        state["requirements"] = {}
        for key in (
            "room_size",
            "use_case",
            "delivery_location",
            "user_location",
            "user_budget",
        ):
            context.pop(key, None)
    if (metadata or {}).get("route") in {"shopping_requirements", "recommendation", "quote_request"}:
        state["flow"] = (metadata or {}).get("route")
    elif (metadata or {}).get("source_type") == "catalog_empty_result":
        state["flow"] = "catalog_search"
    if (metadata or {}).get("search_query"):
        state["last_search_query"] = (metadata or {}).get("search_query")
    state["current_product_id"] = context.get("current_product_id")
    state["current_product_name"] = context.get("current_product_name", "")
    state["brand"] = context.get("current_brand", "") or state.get("brand", "")
    routed_category_name = (metadata or {}).get("catalog_category_name") or ""
    state["category"] = (
        routed_category_name
        or state.get("category", "")
        or context.get("current_category", "")
    )
    product_ids = list((metadata or {}).get("product_ids") or [])
    if product_ids:
        state["recommendation"]["candidate_product_ids"] = product_ids
    if (metadata or {}).get("source_object_id"):
        state["recommendation"]["current_recommendation_id"] = metadata["source_object_id"]
    state["support"]["status"] = conversation.status
    state["support"]["requires_handoff"] = conversation.status in {
        conversation.STATUS_ADMIN_REQUESTED,
        conversation.STATUS_ADMIN_ACTIVE,
    }
    context["state"] = state
    conversation.current_intent = intent
    conversation.context = context
    conversation.save(update_fields=["current_intent", "context", "updated_at"])
    return context
