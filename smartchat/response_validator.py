import re
from difflib import SequenceMatcher

from ai_core.tool_contracts import TOOL_CATALOG_SEARCH_PRODUCTS


NON_ADVANCEABLE_SOURCE_TYPES = {
    "catalog_empty_result",
    "ai_core_safe_fallback",
    "tool_error",
    "tool_validation_error",
    "permission_fallback",
    "feature_disabled",
    "deterministic_conversation",
    "clarification",
    "support_route",
    "purchase_guidance",
    "service_marketplace_route",
}
REQUIREMENT_FLOWS = {
    "shopping_requirements",
    "recommendation",
    "quote_request",
}
GENERIC_SUBJECTS = {
    "",
    "general_marketplace",
    "this request",
}


def _normalize(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def is_duplicate_reply(conversation, reply, threshold=0.88):
    candidate = _normalize(reply)
    if not candidate:
        return False
    recent = conversation.messages.filter(
        sender_type="ai",
        is_private_note=False,
    ).order_by("-id").values_list("message", flat=True)[:5]
    return any(
        SequenceMatcher(None, candidate, _normalize(message)).ratio() >= threshold
        for message in recent
    )


def advance_reply(state):
    requirements = state.get("requirements", {})
    subject = state.get("active_subject") or "this request"
    has_requirements = any(value not in (None, "") for value in requirements.values())
    has_meaningful_subject = str(subject or "").strip().lower() not in GENERIC_SUBJECTS
    is_requirement_flow = state.get("flow") in REQUIREMENT_FLOWS
    if not (has_requirements and has_meaningful_subject and is_requirement_flow):
        return ""
    missing = []
    if not requirements.get("budget_max"):
        missing.append("budget")
    if not requirements.get("use_case") and not requirements.get("room_type"):
        missing.append("where or how you will use it")
    if missing:
        return f"I’ve kept the details for {subject}. To move forward, tell me your {missing[0]}."
    return (
        f"I’ve kept your requirements for {subject}. "
        "I can now choose the best live option, show a cheaper alternative, or connect you with support."
    )


def should_advance_duplicate_reply(*, conversation, reply, source, same_source):
    structured = source.get("structured_response") or {}
    primary_intent = (
        structured.get("primary_intent")
        or source.get("intent")
        or ""
    )
    products = structured.get("products")
    source_type = source.get("source_type", "")
    state = (conversation.context or {}).get("state") or {}

    if source_type in NON_ADVANCEABLE_SOURCE_TYPES:
        return False, f"source_type:{source_type}"
    if (
        primary_intent == TOOL_CATALOG_SEARCH_PRODUCTS
        and isinstance(products, list)
        and not products
    ):
        return False, "catalog_empty_result"
    if source.get("fallback_reason"):
        return False, "fallback_reason"
    if source.get("recommendation_mode"):
        return False, "recommendation_mode"
    if not same_source:
        return False, "different_source"
    if not is_duplicate_reply(conversation, reply):
        return False, "not_duplicate"
    if not advance_reply(state):
        return False, "not_requirement_flow"
    return True, "eligible_requirement_flow"


INTERNAL_INSTRUCTION_PATTERNS = (
    r"\bexisting conversation context\b",
    r"\bdetected intent\b",
    r"\bescalation reason\b",
    r"\broute decision\b",
    r"\b(?:admin|human) can take over\b",
    r"\buse customer memory\b",
    r"\bdo not expose\b",
    r"\bif confidence is low\b",
    r"\bsystem prompt\b",
)


def validate_customer_reply(reply, source):
    text = str(reply or "").strip()
    answer_type = str(source.get("answer_type") or "")
    unsafe = answer_type in {"internal_rule", "routing_rule", "escalation_rule"}
    unsafe = unsafe or any(re.search(pattern, text, re.I) for pattern in INTERNAL_INSTRUCTION_PATTERNS)
    if not unsafe:
        return text, {**source, "response_validation_result": "allowed"}
    safe_reply = (
        "I can help with shopping, orders, vendors, quotes, delivery, services, or connect "
        "you with Arolana support. Tell me what you would like to do."
    )
    return safe_reply, {
        **source,
        "source_type": "response_safety_fallback",
        "source_label": "Customer-safe response",
        "confidence": 0.65,
        "cards": [],
        "actions": [],
        "response_validation_result": "blocked",
        "safety_block_reason": "internal_instruction",
        "blocked_source_type": source.get("source_type", ""),
        "blocked_source_object_id": source.get("source_object_id"),
    }
