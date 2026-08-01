import re
from decimal import Decimal

from django.db.models import F, Q
from django.urls import reverse
from django.utils import timezone

from ai_core.feature_flags import smart_shopping_enabled
from core.content_i18n import translated_field, translated_key
from products.models import Product
from .models import (
    AICustomerMemory,
    AICategoryRouterLog,
    AIIntentLog,
    AIKnowledgeBase,
    AILearnedKnowledge,
    AISettings,
    AITrainingData,
    AIUnansweredQuestion,
    HumanTakeoverRequest,
    SmartChatConversation,
    SmartChatMessage,
)
from .services import ai_operations_reply
from .brain import (
    route_chat_response,
    update_conversation_context,
)
from .context_state import (
    is_slot_only_followup,
    persist_state,
    prepare_context,
)
from .followup_resolver import (
    ALTERNATIVE_REQUEST,
    BETTER_REQUEST,
    CHEAPER_REQUEST,
    INSTALLATION_REQUEST,
    PRICE_REQUEST,
    RECOMMENDATION_DECISION,
    REQUIREMENT_UPDATE,
    VENDOR_LOCATION,
    resolve_followup,
)
from .recommendation_engine import current_price_reply, recommend
from .intent_guards import (
    CLARIFICATION_REPLY,
    CONVERSATIONAL_GOODBYE,
    CONVERSATIONAL_GRATITUDE,
    CONVERSATIONAL_GREETING,
    CONVERSATIONAL_IDENTITY,
    CONVERSATIONAL_WELLBEING,
    GENERAL_ENQUIRY,
    PLATFORM_INFORMATION,
    SHIPPING_ENQUIRY,
    conversational_reply,
    deterministic_conversation_source,
    general_enquiry_reply,
    platform_information_reply,
    resolve_customer_intent,
    shipping_enquiry_reply,
)
from .response_validator import (
    advance_reply,
    should_advance_duplicate_reply,
    validate_customer_reply,
)
from .topic_resolver import (
    SUPPORT_OVERRIDE,
    apply_topic_resolution,
    explicit_route_reply,
    resolve_topic,
)
from .orchestration import smart_shopping_reply
from .text_normalizer import resolve_contextual_text


def _is_purchase_followup(message):
    text = re.sub(r"\s+", " ", str(message or "").strip().lower())
    return bool(
        re.search(
            r"\b(?:how do i|how can i|where can i|can i)\s+"
            r"(?:buy|purchase|order|get)\s+(?:it|this|this one|the item|the product)\b",
            text,
        )
        or re.search(
            r"\b(?:help me|assist me|can you help me|please help me)\s+"
            r"(?:buy|purchase|order|get)\s+(?:it|this|this one|the item|the product)\b",
            text,
        )
        or re.search(
            r"\b(?:add it to cart|add to cart|checkout|place (?:my )?order|"
            r"i want this one|i'll take it|i will take it)\b",
            text,
        )
    )


def _is_checkout_stage_followup(message):
    text = re.sub(r"\s+", " ", str(message or "").strip().lower())
    if re.search(
        r"^(?:where|what|how|can|could|should|do|does|is|are)\b.*\buse (?:that|this|it)\b",
        text,
    ):
        return False
    return bool(
        re.fullmatch(r"(?:\+?234|0)\d{10}", text)
        or
        re.search(
            r"\b(?:yes this is it|yes this is what i want|yes please do|"
            r"this is it|that's it|that is it|"
            r"what do i do|what next|next step|checkout|bank transfer|"
            r"card|paypal|flutterwave|payment|https?://|sku|recipient|"
            r"delivery window|use that|use this|use it as|use him|use her)\b",
            text,
        )
    )


def _is_product_evaluation_followup(message):
    text = re.sub(r"\s+", " ", str(message or "").strip().lower())
    if not text:
        return False
    if _is_checkout_stage_followup(text) or _is_purchase_followup(text):
        return False
    return bool(
        re.search(
            r"\b(?:advise|advice|best|suitable|good for|fit for|use it for|"
            r"use this for|what i want to use|presentation|presentations|"
            r"hall|auditorium|screen|projection screen|people|audience|"
            r"branch|branches|lights?|light in the hall|dim|bright)\b",
            text,
        )
    )


def _is_installation_after_product_followup(message):
    text = re.sub(r"\s+", " ", str(message or "").strip().lower())
    return bool(
        re.search(r"\b(?:install|installer|installation|set it up|setup)\b", text)
        and re.search(
            r"\b(?:if i buy|if i purchase|after i buy|after purchase|who will|who can|can.*install)\b",
            text,
        )
    )


def _product_evaluation_guidance(conversation, state, message):
    product = getattr(conversation, "product", None)
    if not product:
        return None

    requirements = dict((state or {}).get("requirements") or {})
    text = re.sub(r"\s+", " ", str(message or "").strip().lower())

    if re.search(r"\bpresentation|presentations|powerpoint|slides?\b", text):
        requirements["use_case"] = "presentation"
    audience = re.search(r"\b(\d{2,5})\s*(?:people|persons|audience|participants)\b", text)
    if audience:
        requirements["participant_count"] = int(audience.group(1))
        requirements["capacity"] = int(audience.group(1))
    branches = re.search(r"\b(\d{1,4})\s*(?:branch|branches|locations?|sites?)\b", text)
    if branches:
        requirements["branch_count"] = int(branches.group(1))
        requirements["installation_count"] = int(branches.group(1))
    screen = re.search(r"\b(\d{2,4})\s*x\s*(\d{2,4})\s*(?:inch|inches|in|\"|”)?\b", text)
    if screen:
        requirements["screen_size"] = f"{screen.group(1)}x{screen.group(2)} inches"
    if re.search(r"\b(?:light|lights|bright|lit)\b", text) or re.search(
        r"(?:there'?s|there\s+is)?\s*light(?:s)?\s+in\s+the\s+(?:hall|room|auditorium|venue)",
        text,
    ):
        requirements["ambient_light"] = "lights_on"
    if re.search(r"\b(?:dim|dark|controlled light|lights off)\b", text):
        requirements["ambient_light"] = "controlled"

    state["requirements"] = requirements
    state["conversation_stage"] = "product_evaluation"
    state["intent"] = "product_evaluation"
    state["entity_type"] = "product"
    state["intent_family"] = "commerce"
    state["active_subject"] = product.name
    persist_state(conversation, state)

    specs = f"{getattr(product, 'description', '')} {getattr(product, 'specifications', '')}".lower()
    brightness_match = re.search(r"\b(\d{3,6})\s*(?:ansi\s*)?lumens?\b", specs)
    lumens = int(brightness_match.group(1)) if brightness_match else None
    resolution = "SVGA" if re.search(r"\bsvga\b", specs, re.I) or "svga" in product.name.lower() else ""
    audience_count = requirements.get("participant_count") or requirements.get("capacity")
    branch_count = requirements.get("branch_count") or requirements.get("installation_count")
    screen_label = requirements.get("screen_size")
    light_label = requirements.get("ambient_light")
    use_case = requirements.get("use_case")

    lines = [f"Yes, we’re still talking about {product.name}."]
    if use_case or audience_count or screen_label or branch_count:
        details = []
        if use_case:
            details.append(use_case)
        if audience_count:
            details.append(f"{audience_count} people")
        if screen_label:
            details.append(f"{screen_label} screen")
        if branch_count:
            details.append(f"{branch_count} branches")
        lines.append("For your use case — " + ", ".join(details) + " — here’s the plain advice:")

    caution = []
    if lumens:
        if audience_count and audience_count >= 300:
            caution.append(
                f"{lumens} lumens can work better when the hall lights are controlled, but it may look weak in a bright {audience_count}-person hall."
            )
        else:
            caution.append(f"{lumens} lumens is reasonable for controlled-light presentation spaces.")
    if resolution:
        caution.append(
            f"{resolution} is the main limitation: text-heavy presentations may not look sharp from the back of a large hall."
        )
    if light_label == "lights_on":
        caution.append("Because there is light in the hall, I would prefer a brighter Full HD model if sharp slides are important.")
    if branch_count and branch_count >= 2:
        caution.append(f"10 units makes sense if you are installing one projector in each of your {branch_count} branches.")

    if caution:
        lines.extend(f"• {item}" for item in caution)
    else:
        lines.append("It may fit, but I need the hall brightness, screen size and content type to judge properly.")

    lines.append(
        "My honest recommendation: the Optoma S336 is acceptable for basic presentations, "
        "but for a large, lit hall I would rather compare it with a brighter Full HD projector before you buy all 10 units."
    )
    lines.append(
        "If you want, I can compare the S336 against the Optoma EH412 and tell you which is safer for the branches."
    )

    reply = "\n".join(lines)
    return reply, {
        "source_type": "product_evaluation",
        "source_label": product.name,
        "source_object_id": product.id,
        "confidence": 0.96,
        "intent": "product_evaluation",
        "conversation_intent": "product_evaluation",
        "marketplace_category": getattr(getattr(product, "category", None), "name", "product"),
        "active_subject": product.name,
        "structured_requirements": requirements,
        "state": state,
        "actions": [
            {"type": "compare", "label": "Compare safer options"},
            {"type": "view_product", "label": f"View {product.name}"},
        ],
    }


def _product_purchase_guidance(conversation):
    product = getattr(conversation, "product", None)
    if not product:
        return None

    try:
        product_url = product.get_absolute_url()
    except Exception:
        product_url = reverse("products:product_detail", kwargs={"slug": product.slug})
    add_to_cart_url = reverse("products:add_to_cart", args=[product.slug])
    in_stock = bool(
        getattr(product, "available_stock", 0) > 0
        or getattr(product, "allow_backorder", False)
    )
    price = f"₦{product.price:,.2f}"
    stock_phrase = "currently in stock" if in_stock else "not currently listed as in stock"
    reply = (
        f"{product.name} is {stock_phrase} at {price}. "
        "Select View product, choose Add to Cart, then complete delivery and payment at checkout."
    )
    return reply, {
        "source_type": "purchase_guidance",
        "source_label": product.name,
        "source_object_id": product.id,
        "confidence": 0.98,
        "intent": "purchase_guidance",
        "product_ids": [product.id],
        "actions": [
            {
                "type": "view_product",
                "label": f"View {product.name}",
                "url": product_url,
            },
            {
                "type": "add_to_cart",
                "label": "Add to Cart",
                "url": add_to_cart_url,
                "product_id": product.id,
            },
        ],
    }


def _product_installation_guidance(conversation, state):
    product = getattr(conversation, "product", None)
    if not product:
        return None

    requirements = dict((state or {}).get("requirements") or {})
    requirements["equipment"] = product.name
    requirements["equipment_to_install"] = product.name
    requirements["asset_involved"] = product.name
    requirements["installation_required"] = True
    state["requirements"] = requirements
    state["entity_type"] = "service_provider"
    state["intent_family"] = "service"
    state["transaction_type"] = "install"
    state["active_subject"] = f"{product.name} installation"
    state["active_service"] = "install"
    state["intent"] = "service_provider_request"
    persist_state(conversation, state)

    reply = (
        f"A verified Arolana conference-room installer can install {product.name} for you. "
        "I can help create an installation request using this product as the equipment. "
        "Please tell me your installation location, preferred date, and whether you need "
        "installation only or supply plus installation."
    )
    return reply, {
        "source_type": "service_marketplace_route",
        "source_label": "Installation service",
        "source_object_id": product.id,
        "confidence": 0.94,
        "intent": "service_provider_request",
        "marketplace_category": "service",
        "product_ids": [product.id],
        "actions": [
            {
                "type": "find_provider",
                "label": "Find installer",
            },
        ],
    }


def _record_informational_detour(conversation, intent, reply):
    context = dict(conversation.context or {})
    context["last_intent"] = intent
    context["last_topic"] = intent
    context["last_bot_response_summary"] = re.sub(r"\s+", " ", reply or "")[:500]
    context["customer_name"] = conversation.customer_display
    context["support_status"] = conversation.status
    conversation.current_intent = intent
    conversation.context = context
    conversation.save(update_fields=["current_intent", "context", "updated_at"])


PII_PATTERNS = [
    re.compile(r"\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b", re.I),
    re.compile(r"(?:\+?\d[\d\s().-]{7,}\d)"),
    re.compile(r"\b(?:order|tracking|account|customer)\s*(?:id|number|no\.?|#)?\s*[:#-]?\s*[a-z0-9-]{5,}\b", re.I),
]
STOP_WORDS = {
    "a", "an", "and", "are", "can", "do", "for", "how", "i", "in", "is", "it",
    "me", "my", "of", "on", "or", "the", "this", "to", "what", "when", "where",
    "with", "you", "your",
}


def normalize_question(value):
    value = re.sub(r"\s+", " ", str(value or "").strip().lower())
    return re.sub(r"[^a-z0-9\s'-]", "", value)[:500]


def _tokens(value):
    return {token for token in normalize_question(value).split() if len(token) > 2 and token not in STOP_WORDS}


def _score(query, question, keywords="", priority=50):
    query_tokens = _tokens(query)
    candidate_tokens = _tokens(f"{question} {keywords}")
    if not query_tokens or not candidate_tokens:
        return Decimal("0")
    overlap = len(query_tokens & candidate_tokens) / len(query_tokens)
    phrase_bonus = 0.2 if normalize_question(question) in normalize_question(query) else 0
    priority_bonus = min(int(priority or 0), 100) / 1000
    return Decimal(str(min(overlap + phrase_bonus + priority_bonus, 1)))


def _best_match(query, queryset):
    best = None
    best_score = Decimal("0")
    for item in queryset[:250]:
        score = _score(query, item.question, item.keywords, getattr(item, "priority", 50))
        if score > best_score:
            best, best_score = item, score
    return best, best_score


def search_approved_knowledge(query, audience):
    allowed_audiences = ["all", audience]
    knowledge, knowledge_score = _best_match(
        query,
        AIKnowledgeBase.objects.filter(
            approved=True, is_active=True, audience__in=allowed_audiences,
        ).order_by("-priority"),
    )
    training, training_score = _best_match(
        query,
        AITrainingData.objects.filter(
            approved=True, is_active=True, audience__in=allowed_audiences,
        ).order_by("-priority"),
    )
    primary = (knowledge, knowledge_score, "knowledge_base")
    if training_score > knowledge_score:
        primary = (training, training_score, "training_data")
    if primary[0] and primary[1] >= Decimal("0.45"):
        return primary

    best = None
    best_score = Decimal("0")
    for item in AILearnedKnowledge.objects.filter(
        approved=True, rejected=False, privacy_safe=True, is_active=True,
    )[:250]:
        score = _score(query, item.normalized_question, item.keywords, 50)
        if score > best_score:
            best, best_score = item, score
    return best, best_score, "learned_knowledge"


def customer_memories_for(conversation):
    queryset = AICustomerMemory.objects.filter(is_active=True)
    if conversation.user_id:
        return queryset.filter(user_id=conversation.user_id)
    if conversation.device_id:
        return queryset.filter(user__isnull=True, device_id=conversation.device_id)
    if conversation.session_key:
        return queryset.filter(
            user__isnull=True, device_id="", session_key=conversation.session_key,
        )
    return queryset.none()


def _contains_pii(value):
    return any(pattern.search(str(value or "")) for pattern in PII_PATTERNS)


def remember_explicit_preference(conversation, message):
    settings_obj = AISettings.load()
    if not settings_obj.memory_enabled:
        return None
    match = re.search(
        r"\b(?:i prefer|my preferred|i like|my favorite|my favourite)\s+(.{2,180})",
        str(message or ""), re.I,
    )
    if not match:
        return None
    preference = match.group(1).strip(" .,!?:;")
    if not preference or _contains_pii(preference):
        return None
    identity = {}
    if conversation.user_id:
        identity["user_id"] = conversation.user_id
    elif conversation.device_id:
        identity["device_id"] = conversation.device_id
    elif conversation.session_key:
        identity["session_key"] = conversation.session_key
    else:
        return None
    memory, _ = AICustomerMemory.objects.update_or_create(
        **identity,
        memory_key="shopping_preference",
        defaults={
            "memory_value": preference,
            "category": "preference",
            "source_conversation": conversation,
        },
    )
    return memory


def record_learning_candidate(conversation, user_message, answer, source_message=None):
    settings_obj = AISettings.load()
    normalized = normalize_question(user_message)
    state = (conversation.context or {}).get("state") or {}
    followup_type = resolve_followup(user_message, state)
    if not followup_type and re.fullmatch(
        r"\s*(?:\d{2,3}\s*(?:inch|inches|in)|(?:small|medium|large)\s+room|"
        r"\d{1,3}\s*(?:people|participants)|(?:full\s*hd|1080p|4k|short\s+throw))[\s.!?]*",
        str(user_message or ""),
        re.I,
    ):
        followup_type = REQUIREMENT_UPDATE
    if (
        not settings_obj.learning_enabled
        or len(normalized) < 8
        or _contains_pii(user_message)
        or (_contains_pii(answer) and not followup_type)
    ):
        return None
    type_map = {
        REQUIREMENT_UPDATE: "follow_up_context",
        RECOMMENDATION_DECISION: "recommendation_decision",
        ALTERNATIVE_REQUEST: "recommendation_request",
        CHEAPER_REQUEST: "recommendation_request",
        BETTER_REQUEST: "recommendation_request",
        PRICE_REQUEST: "price_question",
        INSTALLATION_REQUEST: "service_request",
        VENDOR_LOCATION: "vendor_question",
    }
    knowledge_type = type_map.get(followup_type, "standalone_question")
    requirements = state.get("requirements") or {}
    context_type = ""
    context_value = ""
    if knowledge_type == "follow_up_context":
        for key, value in requirements.items():
            if value not in (None, ""):
                context_type, context_value = key, str(value)
    proposed_answer = (
        f"Context signal: {context_type}={context_value}"
        if knowledge_type == "follow_up_context"
        else answer
    )
    learned, created = AILearnedKnowledge.objects.get_or_create(
        normalized_question=normalized,
        defaults={
            "proposed_answer": proposed_answer,
            "answer_type": (
                "internal_rule"
                if knowledge_type == "follow_up_context"
                else "catalog_lookup_rule"
                if knowledge_type in {"price_question", "recommendation_request", "recommendation_decision"}
                else "customer_answer"
            ),
            "knowledge_type": knowledge_type,
            "context_type": context_type,
            "context_value": context_value,
            "requires_previous_context": bool(followup_type),
            "requires_live_catalog": knowledge_type in {
                "price_question", "recommendation_request", "recommendation_decision",
            },
            "privacy_safe": True,
            "source_conversation": conversation,
            "source_message": source_message,
        },
    )
    if not created:
        learned.occurrence_count = F("occurrence_count") + 1
        if not learned.approved:
            learned.proposed_answer = proposed_answer
        learned.source_conversation = conversation
        learned.source_message = source_message
        learned.save(
            update_fields=[
                "occurrence_count", "proposed_answer", "source_conversation",
                "source_message", "updated_at",
            ]
        )
        learned.refresh_from_db()
    return learned


def _marketplace_money_label(requirements):
    amount = requirements.get("budget_max") or requirements.get("budget_amount")
    if not amount:
        return ""
    currency = requirements.get("currency") or "NGN"
    symbol = "₦" if currency == "NGN" else f"{currency} "
    try:
        return f"{symbol}{int(amount):,}"
    except (TypeError, ValueError):
        return f"{symbol}{amount}"


def _safe_product_image_url(product):
    if not getattr(product, "main_image", None):
        return ""
    try:
        return product.main_image.url
    except Exception:
        return ""


def _marketplace_product_text(product):
    return re.sub(
        r"\s+",
        " ",
        " ".join(
            str(part or "").lower()
            for part in (
                getattr(product, "name", ""),
                getattr(product, "description", ""),
                getattr(product, "specifications", ""),
                getattr(getattr(product, "category", None), "name", ""),
                getattr(getattr(product, "brand", None), "name", ""),
            )
        ),
    )


def _marketplace_product_role(product):
    text = _marketplace_product_text(product)
    if re.search(
        r"\b(?:mounting kit|wall mount|mount|mic pod|accessory|"
        r"cable|bracket|adapter|hub|display hub|table hub)\b",
        text,
    ):
        return "accessory"
    if re.search(r"\b(?:webcam|stream webcam)\b", text):
        return "webcam"
    if re.search(
        r"\b(?:all-in-one|video conferencing system|conferencing system|"
        r"conference system|rally bar|logitech group|meetup)\b",
        text,
    ):
        return "complete_system"
    return "main_device"


def _is_room_conferencing_marketplace_state(state, products):
    requirements = state.get("requirements") or {}
    text = " ".join(
        str(part or "").replace("_", " ").lower()
        for part in (
            state.get("active_subject"),
            state.get("locked_category"),
            state.get("current_category_locked"),
            state.get("category"),
            state.get("product_type"),
            state.get("user_budget"),
            requirements.get("participant_count"),
            requirements.get("capacity"),
            requirements.get("room_type"),
            requirements.get("budget_max"),
        )
    )
    product_text = " ".join(_marketplace_product_text(product) for product in products[:8])
    combined = f"{text} {product_text}"
    return bool(
        any(
            marker in combined
            for marker in (
                "video conferencing",
                "conferencing",
                "conference room",
                "meeting room",
                "boardroom",
                "rally bar",
                "logitech group",
                "meetup",
            )
        )
        and (
            requirements.get("participant_count")
            or requirements.get("capacity")
            or requirements.get("budget_max")
            or state.get("user_budget")
            or re.search(r"\b\d+\s*(?:people|persons?|sitters?|seats?)\b", combined)
        )
    )


def _split_marketplace_primary_products(state, products):
    if not _is_room_conferencing_marketplace_state(state, products):
        return products, []
    primary = []
    accessories = []
    for product in products:
        role = _marketplace_product_role(product)
        if role in {"accessory", "webcam"}:
            accessories.append(product)
        else:
            primary.append(product)
    return (primary or products), accessories


def _marketplace_card(product):
    return {
        "id": product.id,
        "slug": product.slug,
        "name": product.name,
        "title": product.name,
        "price": f"₦{product.price:,.2f}",
        "price_display": f"₦{product.price:,.2f}",
        "url": product.get_absolute_url(),
        "product_url": product.get_absolute_url(),
        "image_url": _safe_product_image_url(product),
        "add_to_cart_url": reverse("products:add_to_cart", args=[product.slug]),
        "rating": float(product.rating_avg or 0),
        "rating_count": product.rating_count,
        "review_count": product.rating_count,
        "in_stock": product.available_stock > 0 or product.allow_backorder,
        "popular_qa": [
            {
                "question": item.question,
                "answer": item.answer,
            }
            for item in product.questions.filter(is_public=True).exclude(answer="")[:3]
        ],
    }


def _stateful_marketplace_fallback(conversation, state, user_message):
    """Flag-safe marketplace response used when Smart Shopping is disabled."""
    requirements = state.get("requirements") or {}
    subject = (
        state.get("active_subject")
        or state.get("locked_category")
        or state.get("category")
        or state.get("search_query")
        or str(user_message or "").strip()
        or "your request"
    )
    entity_type = state.get("entity_type") or "product"
    transaction = state.get("transaction_type") or "buy"
    location = (
        requirements.get("service_location")
        or requirements.get("delivery_location")
        or requirements.get("location")
        or ""
    )
    budget_label = _marketplace_money_label(requirements)
    service_transactions = {"repair", "install", "maintain", "inspect", "consult", "find_provider"}

    product_cards = []
    compatible_accessories = []
    result_count = 0
    tool_name = None
    if entity_type in {"property", "vehicle"} and transaction in {"rent", "lease", "short_let", "find_property", "find_vehicle"}:
        details = ", ".join(
            item for item in (
                f"location: {location}" if location else "",
                f"budget: {budget_label}" if budget_label else "",
            ) if item
        )
        reply = (
            f"I’ll keep this as a {subject} {transaction.replace('_', ' ')} request"
            f"{(' (' + details + ')') if details else ''}. "
            "I couldn’t find a matching live listing in this response, so the next useful step "
            "is to refine the location or connect you with Arolana support."
        )
        source_type = "marketplace_state_property"
    elif transaction in service_transactions or entity_type == "service_provider":
        reply = (
            f"I’ll keep this as a {subject} service-provider request"
            f"{(' in ' + location) if location else ''}. "
            "I couldn’t confirm a matching provider in this response yet, but I can help refine "
            "the service details or connect you with Arolana support."
        )
        source_type = "marketplace_state_provider"
    else:
        queryset = Product.objects.filter(is_active=True, approval_status="approved")
        if state.get("catalog_category_id"):
            queryset = queryset.filter(category_id=state["catalog_category_id"])
        query_text = " ".join(
            part for part in (
                subject,
                state.get("brand"),
                requirements.get("brand"),
                str(requirements.get("resolution") or "").replace("_", " "),
                str(requirements.get("brightness_requirement") or ""),
            ) if part
        )
        terms = [term for term in re.findall(r"[a-zA-Z0-9]+", query_text.lower()) if len(term) > 2][:8]
        if terms:
            q = Q()
            for term in terms:
                q |= (
                    Q(name__icontains=term)
                    | Q(description__icontains=term)
                    | Q(specifications__icontains=term)
                    | Q(category__name__icontains=term)
                    | Q(brand__name__icontains=term)
                )
            queryset = queryset.filter(q)
        exact_queryset = queryset
        if requirements.get("budget_max"):
            exact_queryset = exact_queryset.filter(price__lte=requirements["budget_max"])
        products = list(
            exact_queryset.select_related("brand", "category").order_by("price", "name")[:4]
        )
        relaxed = False
        if not products and requirements.get("budget_max"):
            products = list(queryset.select_related("brand", "category").order_by("price", "name")[:4])
            relaxed = True
        products, compatible_accessories = _split_marketplace_primary_products(
            state,
            products,
        )
        product_cards = [_marketplace_card(product) for product in products]
        result_count = len(products)
        tool_name = "django.approved_catalog_lookup"
        if products:
            conversation.product = products[0]
            conversation.save(update_fields=["product", "updated_at"])
            intro = (
                f"I couldn’t find an exact {subject} match at or below {budget_label}, "
                "but these are the closest relevant live options:"
                if relaxed and budget_label else
                f"Here are relevant live {subject} options I found:"
            )
            reply = "\n".join(
                [intro]
                + [f"- {product.name} — ₦{product.price:,.2f}" for product in products]
            )
            if compatible_accessories:
                reply = (
                    f"{reply}\nI kept accessories out of the main product cards; "
                    "they can be reviewed later as add-ons for the room setup."
                )
            details = []
            if requirements.get("participant_count"):
                details.append(f"{requirements['participant_count']} people")
            if requirements.get("brightness_requirement"):
                details.append(f"{requirements['brightness_requirement']} lumens")
            if requirements.get("delivery_location"):
                details.append(f"delivery in {requirements['delivery_location']}")
            if budget_label:
                details.append(f"budget {budget_label}")
            if details:
                reply = f"{reply}\nI used your requirement for {', '.join(details[:4])}."
        else:
            details = []
            if requirements.get("brightness_requirement"):
                details.append(f"{requirements['brightness_requirement']} lumens")
            if budget_label:
                details.append(f"budget {budget_label}")
            if location:
                details.append(f"location {location}")
            qualifier = f" with {', '.join(details)}" if details else ""
            reply = (
                f"I couldn’t find an active approved {subject} match{qualifier} in the live Arolana catalogue. "
                "I can try a wider search, look for a verified supplier, or connect you with support."
            )
        source_type = "product_database"

    source = {
        "source_type": source_type,
        "source_label": "Arolana marketplace state",
        "confidence": 0.82,
        "intent": "product_search" if source_type == "product_database" else "marketplace_state",
        "marketplace_category": state.get("category") or subject,
        "category_confidence": 0.95 if state.get("catalog_category_id") else 0.72,
        "category_matched_terms": [subject],
        "category_route_source": "active_category_database" if state.get("catalog_category_id") else source_type,
        "catalog_category_id": state.get("catalog_category_id"),
        "result_count": result_count,
        "product_cards": product_cards,
        "product_ids": [card["id"] for card in product_cards],
        "compatible_accessories": [
            _marketplace_card(product) for product in compatible_accessories[:4]
        ],
        "source_object_id": product_cards[0]["id"] if product_cards else None,
        "active_subject": subject,
        "search_query": subject,
        "tool_name": tool_name,
        "structured_response": {
            "answer": reply,
            "products": product_cards,
            "compatible_accessories": [
                _marketplace_card(product) for product in compatible_accessories[:4]
            ],
            "structured_requirements": requirements,
        },
    }
    update_conversation_context(conversation, source["intent"], reply, source)
    return reply, source


def _should_use_marketplace_workflow(conversation, message, state, deterministic_intent):
    text = str(message or "").lower()
    direct_request = bool(
        re.search(
            r"\b(?:do you have|show me|find(?: me)?|search for|i need|i want|"
            r"i am looking for|i'm looking for|looking for)\b",
            text,
        )
    )
    if is_slot_only_followup(message, state):
        return True
    if (
        state.get("entity_type") == "service_provider"
        or state.get("intent_family") == "service"
        or state.get("transaction_type") in {
            "install", "repair", "maintain", "inspect", "consult",
            "book_service", "find_provider",
        }
    ):
        if not re.search(
            r"\b(?:show me|find products?|search products?|compare|price of|"
            r"how much|buy|purchase|do you have)\b",
            text,
        ):
            return True
    if _is_contextual_marketplace_help_followup(message, state):
        return not bool(getattr(conversation, "product_id", None))
    if deterministic_intent not in {
        "catalog.search_products",
        "shopping_requirements",
        "services.match_providers",
        SHIPPING_ENQUIRY,
    }:
        return False
    entity_type = state.get("entity_type")
    transaction = state.get("transaction_type")
    if entity_type in {
        "property", "vehicle", "medical_equipment", "farm_equipment",
        "software", "service_provider",
    }:
        if (
            entity_type == "property"
            and not re.search(r"\b(?:rent|lease|short-let|short let|buy|purchase|sale|yearly|per year)\b", text)
        ):
            return False
        return direct_request or transaction in {
            "rent", "lease", "short_let", "repair", "install", "maintain",
            "inspect", "consult", "find_provider", "find_property",
            "find_vehicle",
        }
    return (
        direct_request
        and bool(state.get("catalog_category_id"))
        and not bool(getattr(conversation, "product_id", None))
    )


def _is_contextual_marketplace_help_followup(message, state):
    if not state or not state.get("active_subject"):
        return False
    text = re.sub(r"\s+", " ", str(message or "").strip().lower())
    if not text:
        return False
    return bool(
        re.search(
            r"\b(?:help me|please help|yes|ok|okay|go ahead|continue|proceed|what next|next step)\b",
            text,
        )
        and (
            state.get("entity_type") in {"property", "vehicle", "software", "service_provider"}
            or state.get("intent_family") in {"service", "real_estate", "vehicle", "software"}
            or state.get("transaction_type") in {
                "rent", "lease", "short_let", "hire", "repair", "install",
                "maintain", "inspect", "consult", "find_provider",
                "find_property", "find_vehicle",
            }
        )
    )


def request_human_takeover(conversation, requested_by=None, reason="", priority="high"):
    conversation.mark_admin_requested()
    context = dict(conversation.context or {})
    entity_name = (
        context.get("current_product_name")
        or context.get("current_property_name")
        or context.get("current_vehicle_name")
        or ""
    )
    summary_parts = [
        f"Customer: {conversation.customer_display}",
        f"Intent: {conversation.current_intent or context.get('last_intent') or 'unknown'}",
        f"Category: {context.get('marketplace_category') or context.get('current_category') or 'general marketplace'}",
    ]
    if entity_name:
        summary_parts.append(f"Current listing: {entity_name}")
    if context.get("user_location") or context.get("delivery_location"):
        summary_parts.append(
            f"Location: {context.get('delivery_location') or context.get('user_location')}"
        )
    if context.get("user_budget"):
        summary_parts.append(f"Budget: {context['user_budget']}")
    if context.get("use_case"):
        summary_parts.append(f"Use case: {context['use_case']}")
    summary_parts.append(f"Escalation reason: {reason or 'Human support requested'}")
    conversation.ai_summary = "\n".join(summary_parts)
    context["support_status"] = conversation.status
    context["handover_reason"] = reason or "Human support requested"
    conversation.context = context
    conversation.save(update_fields=["ai_summary", "context", "updated_at"])
    takeover, created = HumanTakeoverRequest.objects.update_or_create(
        conversation=conversation,
        status=HumanTakeoverRequest.STATUS_PENDING,
        defaults={
            "requested_by": requested_by if getattr(requested_by, "is_authenticated", False) else None,
            "reason": reason,
            "priority": priority,
        },
    )
    if created:
        try:
            from django.contrib.auth import get_user_model
            from notifications.models import Notification

            for admin in get_user_model().objects.filter(is_staff=True, is_active=True)[:25]:
                Notification.send(
                    user=admin,
                    notification_type="message",
                    title=f"Smart Chat handover #{conversation.id}",
                    message=(reason or "A customer requested human support.")[:500],
                    link=reverse("smartchat:admin_conversation", args=[conversation.id]),
                    metadata={
                        "smartchat_conversation_id": conversation.id,
                        "takeover_request_id": takeover.id,
                    },
                    priority=4 if priority == "urgent" else 3,
                )
        except Exception:
            pass
    return takeover


def generate_managed_reply(conversation, user_message, actor_user=None):
    settings_obj = AISettings.load()
    preferred_language = (conversation.context or {}).get("preferred_language") or "en"
    if not settings_obj.enabled:
        return translated_key(
            "smartchat.fallback",
            settings_obj.fallback_message,
            language_code=preferred_language,
        ), {
            "source_type": "disabled", "source_label": "AI disabled", "confidence": 0,
        }

    text_resolution = resolve_contextual_text(conversation, user_message)
    resolved_message = text_resolution["normalized"]
    context = dict(conversation.context or {})
    context["last_text_resolution"] = text_resolution
    conversation.context = context
    conversation.save(update_fields=["context", "updated_at"])
    if text_resolution.get("clarification"):
        return text_resolution["clarification"], {
            "source_type": "contextual_clarification",
            "source_label": "Typo clarification",
            "confidence": 0.55,
            "intent": conversation.current_intent or "clarification",
            "route": "clarification",
            "cards": [],
            "actions": [],
            "text_resolution": text_resolution,
        }

    deterministic_intent = resolve_customer_intent(resolved_message)
    if deterministic_intent in {
        CONVERSATIONAL_GREETING,
        CONVERSATIONAL_GRATITUDE,
        CONVERSATIONAL_IDENTITY,
        CONVERSATIONAL_GOODBYE,
        CONVERSATIONAL_WELLBEING,
    }:
        reply = conversational_reply(deterministic_intent)
        source = deterministic_conversation_source(deterministic_intent)
        update_conversation_context(conversation, deterministic_intent, reply, source)
        return reply, source

    if deterministic_intent == PLATFORM_INFORMATION:
        reply = platform_information_reply()
        source = {
            **deterministic_conversation_source(PLATFORM_INFORMATION),
            "source_type": "platform_information",
            "source_label": "Arolana platform information",
            "marketplace_category": "platform_information",
            "product_cards": [],
            "product_ids": [],
            "result_count": 0,
            "actions": [
                {"type": "browse_products", "label": "Browse products"},
                {"type": "find_service_provider", "label": "Find service providers"},
                {"type": "contact_support", "label": "Contact support"},
            ],
        }
        _record_informational_detour(conversation, PLATFORM_INFORMATION, reply)
        return reply, source

    if deterministic_intent == GENERAL_ENQUIRY and not (
        conversation.product_id
        and (
            _is_purchase_followup(resolved_message)
            or _is_checkout_stage_followup(resolved_message)
            or _is_product_evaluation_followup(resolved_message)
        )
    ):
        reply = general_enquiry_reply()
        source = {
            **deterministic_conversation_source(GENERAL_ENQUIRY),
            "source_type": "general_enquiry",
            "source_label": "General enquiry clarification",
            "marketplace_category": "general_enquiry",
            "product_cards": [],
            "product_ids": [],
            "result_count": 0,
            "actions": [
                {"type": "browse_products", "label": "Ask about a product"},
                {"type": "track_order", "label": "Track an order"},
                {"type": "find_service_provider", "label": "Find services"},
                {"type": "contact_support", "label": "Contact support"},
            ],
        }
        _record_informational_detour(conversation, GENERAL_ENQUIRY, reply)
        return reply, source

    if deterministic_intent == SHIPPING_ENQUIRY and not smart_shopping_enabled():
        reply = shipping_enquiry_reply()
        source = {
            **deterministic_conversation_source(SHIPPING_ENQUIRY),
            "source_type": "shipping_enquiry",
            "source_label": "Shipping enquiry",
            "marketplace_category": "delivery",
            "product_cards": [],
            "product_ids": [],
            "result_count": 0,
            "actions": [
                {"type": "open_cart", "label": "Open cart"},
                {"type": "checkout", "label": "Proceed to checkout"},
                {"type": "contact_support", "label": "Contact support"},
            ],
        }
        _record_informational_detour(conversation, SHIPPING_ENQUIRY, reply)
        return reply, source

    state = prepare_context(conversation, resolved_message)
    if conversation.product_id and _is_product_evaluation_followup(resolved_message):
        evaluation_result = _product_evaluation_guidance(conversation, state, resolved_message)
        if evaluation_result:
            reply, source = evaluation_result
            update_conversation_context(conversation, source["intent"], reply, source)
            return reply, source

    if conversation.product_id and _is_installation_after_product_followup(resolved_message):
        install_result = _product_installation_guidance(conversation, state)
        if install_result:
            reply, source = install_result
            update_conversation_context(conversation, source["intent"], reply, source)
            return reply, source

    if (
        conversation.product_id
        and _is_checkout_stage_followup(resolved_message)
        and smart_shopping_enabled()
    ):
        smart_shopping_result = smart_shopping_reply(
            conversation,
            resolved_message,
            actor_user=actor_user,
            application_source=conversation.channel or "smartchat",
        )
        if smart_shopping_result:
            reply, source = smart_shopping_result
            update_conversation_context(
                conversation,
                source.get("conversation_intent")
                or source.get("intent", "purchase_preparation"),
                reply,
                source,
            )
            return reply, source

    if conversation.product_id and _is_purchase_followup(resolved_message):
        purchase_result = _product_purchase_guidance(conversation)
        if purchase_result:
            reply, source = purchase_result
            update_conversation_context(conversation, source["intent"], reply, source)
            return reply, source

    if _should_use_marketplace_workflow(conversation, resolved_message, state, deterministic_intent):
        smart_shopping_result = smart_shopping_reply(
            conversation,
            resolved_message,
            actor_user=actor_user,
            application_source=conversation.channel or "smartchat",
        )
        if smart_shopping_result:
            reply, source = smart_shopping_result
            update_conversation_context(
                conversation,
                source.get("conversation_intent")
                or source.get("intent", "smart_shopping"),
                reply,
                source,
            )
            if source.get("structured_response", {}).get("handoff_required"):
                request_human_takeover(
                    conversation,
                    actor_user,
                    user_message,
                )
            return reply, source
        return _stateful_marketplace_fallback(conversation, state, resolved_message)

    topic_resolution = resolve_topic(conversation, resolved_message)
    state = apply_topic_resolution(conversation, topic_resolution)
    explicit_result = explicit_route_reply(topic_resolution, conversation)
    if explicit_result:
        reply, source = explicit_result
        if topic_resolution["relation"] == SUPPORT_OVERRIDE:
            request_human_takeover(conversation, actor_user, user_message)
        update_conversation_context(
            conversation,
            source["intent"],
            reply,
            source,
        )
        return reply, source

    state = prepare_context(conversation, resolved_message)
    if conversation.product_id and _is_product_evaluation_followup(resolved_message):
        evaluation_result = _product_evaluation_guidance(conversation, state, resolved_message)
        if evaluation_result:
            reply, source = evaluation_result
            update_conversation_context(conversation, source["intent"], reply, source)
            return reply, source

    if conversation.product_id and _is_installation_after_product_followup(resolved_message):
        install_result = _product_installation_guidance(conversation, state)
        if install_result:
            reply, source = install_result
            update_conversation_context(conversation, source["intent"], reply, source)
            return reply, source

    if (
        conversation.product_id
        and _is_checkout_stage_followup(resolved_message)
        and smart_shopping_enabled()
    ):
        smart_shopping_result = smart_shopping_reply(
            conversation,
            resolved_message,
            actor_user=actor_user,
            application_source=conversation.channel or "smartchat",
        )
        if smart_shopping_result:
            reply, source = smart_shopping_result
            update_conversation_context(
                conversation,
                source.get("conversation_intent")
                or source.get("intent", "purchase_preparation"),
                reply,
                source,
            )
            return reply, source

    if conversation.product_id and _is_purchase_followup(resolved_message):
        purchase_result = _product_purchase_guidance(conversation)
        if purchase_result:
            reply, source = purchase_result
            update_conversation_context(conversation, source["intent"], reply, source)
            return reply, source

    if _should_use_marketplace_workflow(conversation, resolved_message, state, deterministic_intent):
        smart_shopping_result = smart_shopping_reply(
            conversation,
            resolved_message,
            actor_user=actor_user,
            application_source=conversation.channel or "smartchat",
        )
        if smart_shopping_result:
            reply, source = smart_shopping_result
            update_conversation_context(
                conversation,
                source.get("conversation_intent")
                or source.get("intent", "smart_shopping"),
                reply,
                source,
            )
            if source.get("structured_response", {}).get("handoff_required"):
                request_human_takeover(
                    conversation,
                    actor_user,
                    user_message,
                )
            return reply, source
        return _stateful_marketplace_fallback(conversation, state, resolved_message)

    followup_type = resolve_followup(resolved_message, state)
    if followup_type == PRICE_REQUEST:
        result = current_price_reply(state)
        if result:
            reply, source, product = result
            conversation.product = product
            conversation.save(update_fields=["product", "updated_at"])
            state["intent"] = "price_question"
            state["current_product_id"] = product.id
            state["current_product_name"] = product.name
            persist_state(conversation, state)
            return reply, {"intent": "price_question", **source}
    if followup_type in {
        RECOMMENDATION_DECISION, ALTERNATIVE_REQUEST, CHEAPER_REQUEST, BETTER_REQUEST,
    }:
        result = recommend(state, mode=followup_type)
        if result:
            reply, source, state, product = result
            state["intent"] = "product_recommendation"
            conversation.product = product
            conversation.save(update_fields=["product", "updated_at"])
            persist_state(conversation, state)
            return reply, {"intent": "product_recommendation", **source}
    if followup_type == REQUIREMENT_UPDATE:
        requirements = state.get("requirements", {})
        should_recommend = bool(
            requirements.get("screen_size_inches")
            or requirements.get("participant_count")
            or requirements.get("budget_max")
        )
        if should_recommend:
            result = recommend(state, mode="requirements_update")
            if result:
                reply, source, state, product = result
                state["intent"] = "product_recommendation"
                conversation.product = product
                conversation.save(update_fields=["product", "updated_at"])
                persist_state(conversation, state)
                return reply, {"intent": "product_recommendation", **source}
        state["intent"] = "product_recommendation"
        persist_state(conversation, state)
        subject = state.get("active_subject") or "that product"
        return (
            f"Got it. I’ve kept {subject} and your room requirement. "
            "What screen size, participant count, or budget should I use to narrow the live options?"
        ), {
            "source_type": "conversation_context",
            "source_label": "Requirement follow-up",
            "confidence": 0.86,
            "intent": "product_recommendation",
        }
    if followup_type == INSTALLATION_REQUEST:
        state["intent"] = "service_inquiry"
        persist_state(conversation, state)
        return (
            "Yes. Arolana can connect this product request to approved installers or service "
            "providers. Tell me the installation location and preferred date, or ask me to connect support."
        ), {
            "source_type": "service_marketplace_route",
            "source_label": "Installation service",
            "confidence": 0.86,
            "intent": "service_inquiry",
        }
    if followup_type == VENDOR_LOCATION and conversation.product_id:
        profile = getattr(conversation.product.vendor, "vendor_profile", None)
        location = ", ".join(
            value for value in (
                getattr(profile, "city", ""),
                getattr(profile, "state", ""),
                getattr(profile, "country", ""),
            ) if value
        )
        reply = (
            f"{conversation.product.name} is sold by {profile.store_name}. "
            f"The listed vendor location is {location}."
            if profile and location
            else "The vendor location is not listed clearly yet. Let me connect you with Arolana support."
        )
        return reply, {
            "source_type": "vendor_database",
            "source_label": getattr(profile, "store_name", "Vendor"),
            "confidence": 0.94 if location else 0.3,
            "intent": "vendor_inquiry",
        }

    if (
        deterministic_intent != "clarification"
        or _is_contextual_marketplace_help_followup(resolved_message, state)
    ):
        smart_shopping_result = smart_shopping_reply(
            conversation,
            resolved_message,
            actor_user=actor_user,
            application_source=conversation.channel or "smartchat",
        )
        if smart_shopping_result:
            reply, source = smart_shopping_result
            update_conversation_context(
                conversation,
                source.get("conversation_intent")
                or source.get("intent", "smart_shopping"),
                reply,
                source,
            )
            if source.get("structured_response", {}).get("handoff_required"):
                request_human_takeover(conversation, actor_user, user_message)
            return reply, source
    intent, routed_reply, routed_source, needs_handoff = route_chat_response(
        conversation,
        resolved_message,
    )
    if routed_source.get("source_object_id"):
        conversation.product_id = routed_source["source_object_id"]
        conversation.save(update_fields=["product", "updated_at"])
        conversation.refresh_from_db(fields=["product"])
    if routed_reply:
        source = {
            "source_type": routed_source.get("source_type", "conversation_router"),
            "source_label": intent.replace("_", " ").title(),
            "source_object_id": routed_source.get("source_object_id"),
            "confidence": routed_source.get("confidence", 0.95),
            "intent": intent,
            **routed_source,
        }
        update_conversation_context(conversation, intent, routed_reply, source)
        if needs_handoff:
            request_human_takeover(conversation, actor_user, user_message)
        return routed_reply, source

    item, confidence, source_type = search_approved_knowledge(
        resolved_message,
        conversation.audience,
    )
    if item and confidence >= settings_obj.minimum_confidence:
        answer_type = getattr(item, "answer_type", "customer_answer")
        if answer_type in {"catalog_lookup_rule", "recommendation_rule"}:
            result = recommend(state, mode="recommendation_decision")
            if result:
                reply, source, state, product = result
                conversation.product = product
                conversation.save(update_fields=["product", "updated_at"])
                persist_state(conversation, state)
                return reply, {"intent": "product_recommendation", **source}
        if answer_type in {"internal_rule", "routing_rule", "escalation_rule"}:
            if answer_type == "escalation_rule":
                request_human_takeover(conversation, actor_user, user_message)
            item = None
    if item and confidence >= settings_obj.minimum_confidence:
        if source_type == "knowledge_base":
            AIKnowledgeBase.objects.filter(pk=item.pk).update(
                usage_count=F("usage_count") + 1, last_used_at=timezone.now(),
            )
        answer_field = "answer" if hasattr(item, "answer") else "proposed_answer"
        reply = translated_field(
            item,
            answer_field,
            language_code=preferred_language,
        )
        source = {
            "source_type": source_type,
            "source_label": str(item),
            "source_object_id": item.pk,
            "confidence": float(confidence),
            "intent": intent,
            "answer_type": answer_type,
            "marketplace_category": routed_source.get(
                "marketplace_category",
                "general_marketplace",
            ),
        }
        update_conversation_context(conversation, intent, reply, source)
        return reply, source

    private_memory = [
        {"key": memory.memory_key, "value": memory.memory_value}
        for memory in customer_memories_for(conversation)[:20]
    ] if settings_obj.memory_enabled else []
    reply, context = ai_operations_reply(
        conversation,
        resolved_message,
        audience=conversation.audience,
        actor_user=actor_user,
        customer_memory=private_memory,
    )
    intent = (context.get("intent") or {}).get("intent", "general_support")
    has_structured_data = any(context.get(key) for key in ("products", "order", "vendor", "rider"))
    confidence = Decimal("0.80") if has_structured_data else Decimal("0.58")
    source_type = "arolana_data" if has_structured_data else "ai_model"
    if intent in {"human_handoff", "sensitive_admin_action"}:
        confidence = Decimal("0.20")

    if confidence < settings_obj.minimum_confidence:
        request_human_takeover(conversation, actor_user, user_message)
        reply = translated_key(
            "smartchat.fallback",
            settings_obj.fallback_message,
            language_code=preferred_language,
        )
        source_type = "human_handoff"

    source = {
        "source_type": source_type,
        "source_label": intent.replace("_", " ").title(),
        "confidence": float(confidence),
        "context": context,
        "intent": intent,
        "marketplace_category": routed_source.get(
            "marketplace_category",
            "general_marketplace",
        ),
        "category_confidence": routed_source.get("category_confidence", 0),
        "category_matched_terms": routed_source.get("category_matched_terms", []),
    }
    update_conversation_context(conversation, intent, reply, source)
    return reply, source


def create_managed_ai_message(conversation, user_message, actor_user=None):
    settings_obj = AISettings.load()
    previous_intent = conversation.current_intent
    remember_explicit_preference(conversation, user_message.message)
    initial_text_resolution = resolve_contextual_text(
        conversation,
        user_message.message,
    )
    reply, source = generate_managed_reply(conversation, user_message.message, actor_user)
    text_resolution = (
        (conversation.context or {}).get("last_text_resolution")
        or initial_text_resolution
    )
    if not text_resolution.get("applied") and initial_text_resolution.get("applied"):
        text_resolution = initial_text_resolution
    if text_resolution.get("applied") or text_resolution.get("clarification"):
        source = {**source, "text_resolution": text_resolution}
    reply, source = validate_customer_reply(reply, source)
    structured_response = source.get("structured_response") or {}
    if (
        "result_count" not in source
        and isinstance(structured_response.get("products"), list)
    ):
        source = {**source, "result_count": len(structured_response["products"])}
    latest_ai = conversation.messages.filter(
        sender_type=SmartChatMessage.SENDER_AI,
        is_private_note=False,
    ).order_by("-id").first()
    same_source = not source.get("source_object_id") or (
        latest_ai and latest_ai.source_object_id == source.get("source_object_id")
    )
    should_advance, duplicate_reason = should_advance_duplicate_reply(
        conversation=conversation,
        reply=reply,
        source=source,
        same_source=bool(same_source),
    )
    source = {
        **source,
        "duplicate_check": "advance" if should_advance else "skipped",
        "duplicate_skip_reason": "" if should_advance else duplicate_reason,
    }
    if should_advance:
        advanced_reply = advance_reply((conversation.context or {}).get("state") or {})
        reply = advanced_reply or CLARIFICATION_REPLY
        source = {
            **source,
            "source_type": "duplicate_response_prevention",
            "source_label": "Conversation state",
            "confidence": max(
                float(source.get("confidence") or 0),
                0.75,
            ),
            "duplicate_advance_reason": duplicate_reason,
        }
    ai_message = SmartChatMessage.objects.create(
        conversation=conversation,
        sender_type=SmartChatMessage.SENDER_AI,
        message=reply,
        source_type=source.get("source_type", ""),
        source_label=source.get("source_label", ""),
        source_object_id=source.get("source_object_id"),
        confidence=source.get("confidence"),
        metadata={"ai_manager": True, **source},
    )
    intent = source.get("intent") or conversation.current_intent or "general_conversation"
    marketplace_category = source.get("marketplace_category", "general_marketplace")
    style = source.get("marketplace_style")
    route_label = str(source.get("marketplace_category") or "").lower()
    canonical_route_labels = {
        "property": {"property", "properties", "real estate"},
        "vehicle": {"vehicle", "vehicles", "cars"},
        "food": {"food", "foods"},
        "home_kitchen": {"home kitchen", "home & kitchen"},
        "art": {"art", "arts"},
        "fashion": {"fashion"},
        "industrial": {"industrial", "industrial goods"},
        "service": {"service", "services"},
        "vendor": {"vendor", "vendors"},
        "technology": {"technology", "electronics"},
    }
    if style in canonical_route_labels and route_label in canonical_route_labels[style]:
        marketplace_category = style
    used_memory = bool(
        conversation.product_id
        or (conversation.context or {}).get("last_topic")
        or customer_memories_for(conversation).exists()
    )
    AIIntentLog.objects.create(
        conversation=conversation,
        message=user_message,
        intent=intent,
        previous_intent=previous_intent,
        confidence=source.get("confidence") or 0,
        channel=conversation.channel,
        used_memory=used_memory,
        triggered_search=bool(source.get("product_ids")),
        triggered_handover=conversation.status == SmartChatConversation.STATUS_ADMIN_REQUESTED,
        metadata={
            "source_type": source.get("source_type", ""),
            "source_label": source.get("source_label", ""),
            "resolved_intent": source.get("intent", ""),
            "selected_route": source.get("route") or source.get("intent", ""),
            "tool_name": (
                (source.get("tool_calls") or [""])[0]
                if isinstance(source.get("tool_calls"), list)
                else source.get("tool_name", "")
            ),
            "tool_result_count": source.get("result_count"),
            "duplicate_check": source.get("duplicate_check", ""),
            "duplicate_skip_reason": source.get("duplicate_skip_reason", ""),
            "request_id": source.get("request_id", ""),
        },
    )
    AICategoryRouterLog.objects.create(
        conversation=conversation,
        message=user_message,
        marketplace_category=marketplace_category,
        catalog_category_id=(
            source.get("catalog_category_id")
            or getattr(getattr(conversation, "product", None), "category_id", None)
        ),
        confidence=source.get("category_confidence") or 0,
        matched_terms=source.get("category_matched_terms") or [],
        route_source=source.get("category_route_source") or source.get("source_type", ""),
        entity_type="product" if conversation.product_id else "",
        entity_id=conversation.product_id,
    )
    confidence = Decimal(str(source.get("confidence") or 0))
    if confidence < settings_obj.minimum_confidence or source.get("source_type") in {
        "human_handoff",
        "product_database_missing_spec",
    }:
        normalized = normalize_question(user_message.message)
        unanswered, created = AIUnansweredQuestion.objects.get_or_create(
            normalized_question=normalized,
            is_resolved=False,
            defaults={
                "conversation": conversation,
                "message": user_message,
                "question": user_message.message,
                "detected_intent": intent,
                "marketplace_category": marketplace_category,
                "confidence": confidence,
                "reason": source.get("source_type", "low_confidence"),
                "context_snapshot": conversation.context or {},
            },
        )
        if not created:
            unanswered.occurrence_count = F("occurrence_count") + 1
            unanswered.conversation = conversation
            unanswered.message = user_message
            unanswered.context_snapshot = conversation.context or {}
            unanswered.save(
                update_fields=[
                    "occurrence_count", "conversation", "message",
                    "context_snapshot", "updated_at",
                ]
            )
    record_learning_candidate(conversation, user_message.message, reply, ai_message)
    return ai_message
