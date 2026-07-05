import re
from decimal import Decimal

from django.db.models import F
from django.urls import reverse
from django.utils import timezone

from core.content_i18n import translated_field, translated_key
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
from .context_state import persist_state, prepare_context
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
from .response_validator import advance_reply, is_duplicate_reply


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

    state = prepare_context(conversation, user_message)
    followup_type = resolve_followup(user_message, state)
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

    intent, routed_reply, routed_source, needs_handoff = route_chat_response(
        conversation,
        user_message,
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

    item, confidence, source_type = search_approved_knowledge(user_message, conversation.audience)
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
        if answer_type in {"internal_rule", "escalation_rule"}:
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
        user_message,
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
    reply, source = generate_managed_reply(conversation, user_message.message, actor_user)
    latest_ai = conversation.messages.filter(
        sender_type=SmartChatMessage.SENDER_AI,
        is_private_note=False,
    ).order_by("-id").first()
    same_source = not source.get("source_object_id") or (
        latest_ai and latest_ai.source_object_id == source.get("source_object_id")
    )
    if (
        not source.get("recommendation_mode")
        and same_source
        and is_duplicate_reply(conversation, reply)
    ):
        reply = advance_reply((conversation.context or {}).get("state") or {})
        source = {
            **source,
            "source_type": "duplicate_response_prevention",
            "source_label": "Conversation state",
            "confidence": max(float(source.get("confidence") or 0), 0.75),
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
