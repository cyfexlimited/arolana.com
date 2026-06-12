import re
from decimal import Decimal

from django.db.models import F
from django.urls import reverse
from django.utils import timezone

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
    if (
        not settings_obj.learning_enabled
        or len(normalized) < 8
        or _contains_pii(user_message)
        or _contains_pii(answer)
    ):
        return None
    learned, created = AILearnedKnowledge.objects.get_or_create(
        normalized_question=normalized,
        defaults={
            "proposed_answer": answer,
            "privacy_safe": True,
            "source_conversation": conversation,
            "source_message": source_message,
        },
    )
    if not created:
        learned.occurrence_count = F("occurrence_count") + 1
        if not learned.approved:
            learned.proposed_answer = answer
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
    if not settings_obj.enabled:
        return settings_obj.fallback_message, {
            "source_type": "disabled", "source_label": "AI disabled", "confidence": 0,
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
        if source_type == "knowledge_base":
            AIKnowledgeBase.objects.filter(pk=item.pk).update(
                usage_count=F("usage_count") + 1, last_used_at=timezone.now(),
            )
        reply = item.answer if hasattr(item, "answer") else item.proposed_answer
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
        reply = settings_obj.fallback_message
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
