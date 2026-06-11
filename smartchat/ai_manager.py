import re
from decimal import Decimal

from django.db.models import F
from django.utils import timezone

from .models import (
    AICustomerMemory,
    AIKnowledgeBase,
    AILearnedKnowledge,
    AISettings,
    AITrainingData,
    HumanTakeoverRequest,
    SmartChatConversation,
    SmartChatMessage,
)
from .services import ai_operations_reply
from .product_intelligence import product_intelligence_reply


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
    takeover, _ = HumanTakeoverRequest.objects.update_or_create(
        conversation=conversation,
        status=HumanTakeoverRequest.STATUS_PENDING,
        defaults={
            "requested_by": requested_by if getattr(requested_by, "is_authenticated", False) else None,
            "reason": reason,
            "priority": priority,
        },
    )
    return takeover


def generate_managed_reply(conversation, user_message, actor_user=None):
    settings_obj = AISettings.load()
    if not settings_obj.enabled:
        return settings_obj.fallback_message, {
            "source_type": "disabled", "source_label": "AI disabled", "confidence": 0,
        }

    item, confidence, source_type = search_approved_knowledge(user_message, conversation.audience)
    if item and confidence >= settings_obj.minimum_confidence:
        if source_type == "knowledge_base":
            AIKnowledgeBase.objects.filter(pk=item.pk).update(
                usage_count=F("usage_count") + 1, last_used_at=timezone.now(),
            )
        return item.answer if hasattr(item, "answer") else item.proposed_answer, {
            "source_type": source_type,
            "source_label": str(item),
            "source_object_id": item.pk,
            "confidence": float(confidence),
        }

    product_result = product_intelligence_reply(conversation, user_message)
    if product_result:
        reply, product_source = product_result
        if product_source.get("source_type") == "product_database_missing_spec":
            request_human_takeover(conversation, actor_user, user_message)
        return reply, product_source

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

    return reply, {
        "source_type": source_type,
        "source_label": intent.replace("_", " ").title(),
        "confidence": float(confidence),
        "context": context,
    }


def create_managed_ai_message(conversation, user_message, actor_user=None):
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
    record_learning_candidate(conversation, user_message.message, reply, ai_message)
    return ai_message
