UNSUPPORTED_INTENT = "unsupported"
UNSUPPORTED_MARKETPLACE_INTENTS = {
    "vehicle",
    "vehicles",
    "car",
    "cars",
    "property",
    "properties",
    "real_estate",
    "rental",
    "rentals",
    "land",
}


def normalize_primary_intent(value):
    intent = str(value or "").strip().lower().replace("-", "_")
    if intent in UNSUPPORTED_MARKETPLACE_INTENTS:
        return UNSUPPORTED_INTENT
    return intent


def validate_single_primary_intent(payload):
    """
    Validate the V1 AI response contract: exactly one primary intent string.

    This intentionally rejects multi-intent lists until the output schema is
    explicitly changed.
    """
    if not isinstance(payload, dict):
        raise ValueError("AI response payload must be an object.")

    if "intents" in payload:
        raise ValueError("Multiple intents are not supported in this response schema.")

    intent = payload.get("intent")

    if isinstance(intent, (list, tuple, set)):
        raise ValueError("Intent must be one primary string, not a collection.")

    primary_intent = normalize_primary_intent(intent)

    if not primary_intent:
        raise ValueError("A primary intent is required.")

    return primary_intent


def unsupported_marketplace_response():
    return {
        "intent": UNSUPPORTED_INTENT,
        "requires_handoff": True,
        "message": (
            "That request is not supported in Smart Shopping V1. "
            "I can connect you with human assistance instead."
        ),
    }

