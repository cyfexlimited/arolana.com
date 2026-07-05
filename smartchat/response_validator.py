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
