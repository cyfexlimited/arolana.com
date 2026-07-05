import re


PRICE_REQUEST = "price_request"
ALTERNATIVE_REQUEST = "alternative_request"
CHEAPER_REQUEST = "cheaper_request"
BETTER_REQUEST = "better_request"
RECOMMENDATION_DECISION = "recommendation_decision"
REQUIREMENT_UPDATE = "requirement_update"
INSTALLATION_REQUEST = "installation_request"
VENDOR_LOCATION = "vendor_location"


def resolve_followup(message, state):
    text = re.sub(r"\s+", " ", str(message or "").strip().lower())
    comparable = text.strip(" .,!?:;")
    has_context = bool(
        state.get("active_subject")
        or state.get("current_product_id")
        or state.get("recommendation", {}).get("candidate_product_ids")
    )
    if not has_context:
        return ""
    if comparable in {"how much", "price", "what is the price", "what's the price"}:
        return PRICE_REQUEST
    if re.search(r"\b(?:show me\s+)?another(?:\s+one)?\b", text):
        return ALTERNATIVE_REQUEST
    if re.search(r"\b(?:a\s+)?cheaper(?:\s+one|\s+option)?\b", text):
        return CHEAPER_REQUEST
    if re.search(r"\b(?:a\s+)?better(?:\s+one|\s+option)?\b", text):
        return BETTER_REQUEST
    if any(phrase in text for phrase in (
        "make a choice for me", "choose for me", "pick one for me",
        "which one should i get", "decide for me",
    )):
        return RECOMMENDATION_DECISION
    if any(phrase in text for phrase in ("can you install", "installation", "set it up", "setup service")):
        return INSTALLATION_REQUEST
    if any(phrase in text for phrase in ("where is the vendor", "vendor location", "where is the seller")):
        return VENDOR_LOCATION
    requirements = state.get("requirements", {})
    if any(value not in (None, "") for value in requirements.values()):
        if (
            re.fullmatch(r"(?:for\s+)?\d{1,3}\s*(?:people|persons|participants|users|seats)", comparable)
            or re.fullmatch(r"\d{2,3}(?:\.\d+)?\s*(?:inch|inches|in|”|\")", comparable)
            or re.fullmatch(r"(?:for\s+)?(?:a\s+)?(?:small|medium|large)\s+(?:room|hall|church|office|space)", comparable)
            or re.fullmatch(r"(?:₦|ngn|n|\$)?\s*[\d,.]+\s*[km]?(?:\s*-\s*(?:₦|ngn|n|\$)?\s*[\d,.]+\s*[km]?)?", comparable)
            or comparable in {"full hd", "1080p", "4k", "short throw", "ultra short throw"}
        ):
            return REQUIREMENT_UPDATE
    return ""
