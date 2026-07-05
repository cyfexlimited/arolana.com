import re
from difflib import SequenceMatcher

from .context_state import normalized_state


SAFE_TOKEN_CORRECTIONS = {
    "conferening": "conferencing",
    "conferencng": "conferencing",
    "anoda": "another",
    "anoder": "another",
    "rom": "room",
}

CONTEXTUAL_TOKEN_CORRECTIONS = {
    "sale": ("sell", {"vendor_registration", "vendor_onboarding_guidance"}),
    "mush": ("much", {"price_question", "product_details", "product_recommendation"}),
}

VENDOR_TOPICS = {
    "vendor_registration",
    "vendor_onboarding_guidance",
    "vendor_onboarding_next",
    "vendor_subscription_overview",
}


def _clean(value):
    return re.sub(r"\s+", " ", str(value or "").strip())


def _active_topics(conversation):
    state = normalized_state(conversation)
    context = conversation.context or {}
    return {
        str(state.get("intent") or ""),
        str(state.get("last_topic") or ""),
        str(conversation.current_intent or ""),
        str((context.get("last_topic_resolution") or {}).get("intent") or ""),
        str((state.get("workflow") or {}).get("type") or ""),
    }


def _replace_token(text, old, new):
    return re.sub(rf"\b{re.escape(old)}\b", new, text, flags=re.I)


def resolve_contextual_text(conversation, message):
    original = _clean(message)
    corrected = original
    topics = _active_topics(conversation)
    corrections = []
    confidence = 1.0

    for token, replacement in SAFE_TOKEN_CORRECTIONS.items():
        if re.search(rf"\b{re.escape(token)}\b", corrected, re.I):
            corrected = _replace_token(corrected, token, replacement)
            similarity = SequenceMatcher(None, token, replacement).ratio()
            corrections.append({
                "from": token,
                "to": replacement,
                "reason": "common_customer_typo",
                "confidence": round(max(similarity, 0.88), 2),
            })
            confidence = min(confidence, max(similarity, 0.88))

    for token, (replacement, allowed_topics) in CONTEXTUAL_TOKEN_CORRECTIONS.items():
        if (
            re.search(rf"\b{re.escape(token)}\b", corrected, re.I)
            and (
                topics.intersection(allowed_topics)
                or (token == "mush" and conversation.product_id)
            )
        ):
            corrected = _replace_token(corrected, token, replacement)
            corrections.append({
                "from": token,
                "to": replacement,
                "reason": "active_topic",
                "confidence": 0.94,
            })
            confidence = min(confidence, 0.94)

    lowered = corrected.lower()
    guard_request = bool(re.search(r"\bguard\s+(?:me|us)\b", lowered))
    security_context = bool(re.search(
        r"\b(account|password|login|security|secure|protect|protection|fraud|money)\b",
        lowered,
    ))
    vendor_context = bool(topics.intersection(VENDOR_TOPICS) or "vendor_onboarding" in topics)
    clarification = ""
    if guard_request and vendor_context and not security_context:
        corrected = _replace_token(corrected, "guard", "guide")
        corrections.append({
            "from": "guard",
            "to": "guide",
            "reason": "vendor_onboarding_context",
            "confidence": 0.97,
        })
        confidence = min(confidence, 0.97)
    elif guard_request and not security_context:
        clarification = "Do you mean you want me to guide you through the current process?"

    # These phrase corrections are safe only in their corresponding meaning.
    phrase_rules = (
        (r"\bhow do i sale on arolana\b", "how do i sell on Arolana", 0.98),
        (r"\bhow mush\b", "how much", 0.95),
        (r"\bfor small room\b", "for a small room", 0.96),
    )
    for pattern, replacement, score in phrase_rules:
        if re.search(pattern, corrected, re.I):
            if "how mush" not in pattern or topics.intersection(
                {"price_question", "product_details", "product_recommendation"}
            ):
                before = corrected
                corrected = re.sub(pattern, replacement, corrected, flags=re.I)
                corrections.append({
                    "from": before,
                    "to": corrected,
                    "reason": "contextual_phrase",
                    "confidence": score,
                })
                confidence = min(confidence, score)

    return {
        "original": original,
        "normalized": corrected,
        "applied": corrected != original,
        "corrections": corrections,
        "confidence": round(confidence if corrections else 1.0, 2),
        "clarification": clarification,
    }
