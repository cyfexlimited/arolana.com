import re

from ai_core.tool_contracts import (
    TOOL_CATALOG_COMPARE_PRODUCTS,
    TOOL_CATALOG_SEARCH_PRODUCTS,
    TOOL_QUOTES_CREATE_QUOTE_REQUEST,
    TOOL_SERVICES_MATCH_PROVIDERS,
)


CONVERSATIONAL_GREETING = "conversational_greeting"
CONVERSATIONAL_GRATITUDE = "conversational_gratitude"
CONVERSATIONAL_IDENTITY = "conversational_identity"
CONVERSATIONAL_GOODBYE = "conversational_goodbye"
ORDER_INTENT = "order_tracking"
SUPPORT_INTENT = "support_request"
REQUIREMENTS_INTENT = "shopping_requirements"
CLARIFICATION_INTENT = "clarification"

GREETING_REPLY = (
    "Hello! Welcome to Arolana. I can help you find and compare products, "
    "track an order, locate an installer or connect you with Arolana support. "
    "What are you looking for today?"
)
IDENTITY_REPLY = (
    "I’m Arolana Chat, Arolana’s shopping assistant. I can help you search "
    "the marketplace, compare products, check availability, track orders and "
    "connect you with support."
)
GRATITUDE_REPLY = "You’re welcome. Is there anything else you would like help with?"
GOODBYE_REPLY = "Thank you for visiting Arolana. Have a great day!"
CLARIFICATION_REPLY = (
    "What would you like help with—finding a product, tracking an order, "
    "locating an installer or contacting support?"
)
REQUIREMENTS_REPLY = (
    "I can help narrow that down. What budget, room lighting, screen size or "
    "throw distance should I use for the recommendation?"
)


_NOISE_PATTERN = re.compile(r"[^a-z0-9\s'-]+")

CONVERSATIONAL_PATTERNS = (
    (CONVERSATIONAL_GREETING, (
        r"^(hello|hi|hey|hello there|hi there)$",
        r"^good (morning|afternoon|evening)$",
        r"^(how are you|can you help me)$",
    )),
    (CONVERSATIONAL_GRATITUDE, (
        r"^(thanks|thank you|many thanks|okay|ok|alright)$",
    )),
    (CONVERSATIONAL_IDENTITY, (
        r"^(who are you|what are you|what can you do)$",
    )),
    (CONVERSATIONAL_GOODBYE, (
        r"^(bye|goodbye|see you|see you later)$",
    )),
)

PRODUCT_SEARCH_PATTERNS = (
    r"\bi (?:need|want|am looking for|m looking for)\b",
    r"\bdo you have\b",
    r"\bshow me\b",
    r"\bhow much (?:is|for|are)\b",
    r"\b(?:price|cost) (?:of|for)\b",
    r"\b(?:in stock|available|availability)\b",
    r"\b(?:buy|purchase|order)\b",
    r"\b(?:projector|screen|webcam|camera|speaker|microphone|laptop|monitor|conference-room cameras?)\b",
    r"\b(?:logitech|epson|jabra|rally|c920|group|optoma)\b",
)

REQUIREMENTS_PATTERNS = (
    r"\bi need (?:a|an|some)?\s*(?:projector|screen|camera|webcam|speaker|microphone)?\s*for\b",
    r"\bwhat (?:webcam|camera|projector|screen|speaker|microphone).*\bworks? for\b",
    r"\b(?:recommend|suggest|best for|help me choose)\b",
)

ORDER_PATTERNS = (r"\btrack (?:my |an? )?order\b", r"\bwhere is my order\b")
INSTALLER_PATTERNS = (
    r"\bi need (?:an? )?(?:installer|engineer|technician)\b",
    r"\bi need (?:an? )?(?:[a-z0-9-]+\s+){1,6}(?:installer|engineer|technician)\b",
    r"\bi need someone to (?:repair|install|maintain|inspect|service)\b",
    r"\bfind (?:someone|a|an) to (?:repair|install|maintain|inspect|service)\b",
    r"\b(?:repair|installation|maintenance|inspection) (?:technician|provider|service)\b",
    r"\bfind (?:an? )?(?:installer|engineer|service provider)\b",
    r"\bfind (?:an? )?(?:[a-z0-9-]+\s+){1,6}(?:installer|engineer|technician|service provider)\b",
)
SUPPORT_PATTERNS = (r"\bcontact support\b", r"\bconnect me (?:to|with) support\b")
COMPARISON_PATTERNS = (r"\bcompare\b", r"\bversus\b", r"\bvs\b")
QUOTE_PATTERNS = (
    r"\b(?:quote|quotation|proposal|professional estimate|send request)\b",
)

QUERY_CLEANERS = (
    r"^(?:do you have|have you got|is there|is the|are there)\s+",
    r"^(?:how much is|how much are|how much for)\s+",
    r"^(?:show me|find me|search for|i need|i want|looking for)\s+",
    r"\s+(?:available|in stock|on arolana)$",
    r"\s+(?:price|cost)$",
)


def normalize_message(value: str) -> str:
    text = str(value or "").replace("’", "'").lower()
    text = _NOISE_PATTERN.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def _matches(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def detect_conversational_intent(message: str) -> str:
    text = normalize_message(message)
    for intent, patterns in CONVERSATIONAL_PATTERNS:
        if _matches(text, patterns):
            return intent
    return ""


def conversational_reply(intent: str) -> str:
    return {
        CONVERSATIONAL_GREETING: GREETING_REPLY,
        CONVERSATIONAL_GRATITUDE: GRATITUDE_REPLY,
        CONVERSATIONAL_IDENTITY: IDENTITY_REPLY,
        CONVERSATIONAL_GOODBYE: GOODBYE_REPLY,
    }.get(intent, "")


def resolve_customer_intent(message: str) -> str:
    text = normalize_message(message)
    conversational = detect_conversational_intent(text)
    if conversational:
        return conversational
    if _matches(text, ORDER_PATTERNS):
        return ORDER_INTENT
    if _matches(text, INSTALLER_PATTERNS):
        return TOOL_SERVICES_MATCH_PROVIDERS
    if _matches(text, SUPPORT_PATTERNS):
        return SUPPORT_INTENT
    if _matches(text, COMPARISON_PATTERNS):
        return TOOL_CATALOG_COMPARE_PRODUCTS
    if _matches(text, QUOTE_PATTERNS):
        return TOOL_QUOTES_CREATE_QUOTE_REQUEST
    if _matches(text, REQUIREMENTS_PATTERNS):
        return REQUIREMENTS_INTENT
    if _matches(text, PRODUCT_SEARCH_PATTERNS):
        return TOOL_CATALOG_SEARCH_PRODUCTS
    return CLARIFICATION_INTENT


def clean_product_search_query(message: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(message or "").strip())
    cleaned = cleaned.strip(" \t\r\n.!?,;:")
    for pattern in QUERY_CLEANERS:
        cleaned = re.sub(pattern, "", cleaned, flags=re.I).strip(" \t\r\n.!?,;:")
    return cleaned or re.sub(r"\s+", " ", str(message or "").strip()).strip(" \t\r\n.!?,;:")


def deterministic_conversation_source(intent: str, *, request_id: str = "") -> dict:
    return {
        "intent": intent,
        "source_type": "deterministic_conversation",
        "source_label": "Arolana conversation",
        "confidence": 1.0,
        "request_id": request_id,
        "route": intent,
        "cards": [],
        "actions": [],
    }
