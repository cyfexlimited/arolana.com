import re
from difflib import SequenceMatcher


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
