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
CONVERSATIONAL_WELLBEING = "conversational_wellbeing"
PLATFORM_INFORMATION = "platform_information"
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
WELLBEING_REPLY = "I’m doing well, thank you. How can I help you today?"
PLATFORM_INFORMATION_REPLY = (
    "Arolana is a multi-category marketplace for products and professional services. "
    "You can discover and compare products from approved sellers, buy products, "
    "request quotes, arrange delivery, track orders, and connect with installers, "
    "technicians, engineers and other service providers. Sellers and service "
    "providers can also register to offer products or services on Arolana. "
    "When you are ready, tell me what you want to buy or the service you need, "
    "and I’ll guide you."
)
CLARIFICATION_REPLY = (
    "What would you like help with—finding a product, tracking an order, "
    "locating an installer or contacting support?"
)
REQUIREMENTS_REPLY = (
    "I can help narrow that down. Is this for a small meeting room, "
    "boardroom, classroom, church or another space? Also share the number "
    "of participants, preferred platform and budget."
)


_NOISE_PATTERN = re.compile(r"[^a-z0-9\s'-]+")

CONVERSATIONAL_PATTERNS = (
    (CONVERSATIONAL_WELLBEING, (
        r"^how are you(?: today)?$",
        r"^how are you doing(?: today)?$",
        r"^(?:hello|hi|hey)\s+(?:and\s+)?how (?:are you|you doing)(?: today)?$",
    )),
    (CONVERSATIONAL_GREETING, (
        r"^(hello|hi|hey|hello there|hi there)$",
        r"^good (morning|afternoon|evening)$",
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

PLATFORM_INFORMATION_PATTERNS = (
    r"\bwhat (?:is|s)?\s*(?:arolana|this platform|your platform|this website|this site)\b",
    r"\bwhat (?:is|s)?\s*(?:arolana|this platform|your platform|this website|this site)\s+"
    r"(?:all\s+)?about\b",
    r"\b(?:arolana|this platform|your platform|this website|this site)\s+"
    r"(?:is\s+)?(?:all\s+)?about\b",
    r"\btell me about (?:arolana|this platform|your platform|this website|this site)\b",
    r"\bexplain (?:arolana|this platform|your platform|this website|this site)\b",
    r"\bhow does (?:arolana|this platform|your platform|this website|this site)\s+work\b",
    r"\bwhat can i do here\b",
    r"\bi want to (?:know|understand|learn) (?:about\s+)?"
    r"(?:arolana|this platform|your platform|this website|this site)\b",
    r"\bbefore i (?:start|begin) (?:shopping|shop|buying)\b",
    r"\bis (?:arolana|this platform|your platform|this website|this site)\s+"
    r"(?:a\s+)?marketplace\b",
    r"\bwhat services (?:does|do) (?:arolana|you|this platform|your platform)\s+offer\b",
    r"\bhow does shopping work here\b",
    r"\btell me about (?:the\s+)?platform before i (?:shop|start shopping|buy)\b",
    r"\bi want to understand (?:the\s+)?(?:website|site|platform) first\b",
)

PRODUCT_SEARCH_PATTERNS = (
    r"\bi (?:need|want|am looking for|m looking for)\s+"
    r"(?!to\s+(?:know|understand|learn|ask|see how)\b)"
    r"(?:a|an|some|the)?\s*[a-z0-9-]+",
    r"\bdo you have\b",
    r"\bdo you sell\b",
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

    # Broad conferencing requests need room and participant qualification
    # before searching the catalogue.
    r"\b(?:i need|i want|i am looking for|i'm looking for|looking for)\b.*"
    r"\b(?:video conferencing|video conference|conferencing)\b",

    r"\b(?:video conferencing|video conference|conferencing)\s+"
    r"(?:device|system|solution|equipment|setup)\b",
)

ORDER_PATTERNS = (r"\btrack (?:my |an? )?order\b", r"\bwhere is my order\b")
INSTALLER_PATTERNS = (
    r"\bi need (?:an? )?(?:installer|engineer|technician)\b",
    r"\bi(?:'m| am|m)? looking for (?:an? )?(?:installer|engineer|technician|service provider)\b",
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

CONTEXTUAL_FOLLOWUP_PATTERNS = (
    r"^(?:please\s+)?(?:do\s+)?help(?:\s+me)?(?:\s+please)?$",
    r"^(?:please\s+)?assist(?:\s+me)?(?:\s+please)?$",
    r"^can you help(?:\s+me)?$",
)

PROPERTY_PATTERNS = (
    r"\b(?:house|apartment|property|land|real estate|warehouse|office space)\b",
)

VEHICLE_PATTERNS = (
    r"\b(?:car|vehicle|bus|van|truck|suv|toyota|camry|corolla|honda|benz|mercedes)\b",
)

SOFTWARE_PATTERNS = (
    r"\b(?:software|application|mobile app|web app|licence|license)\b",
)

PROPERTY_INTENT = "property_inquiry"
VEHICLE_INTENT = "car_inquiry"
SOFTWARE_INTENT = "software_inquiry"

QUERY_CLEANERS = (
    r"^(?:do you have|have you got|is there|is the|are there)\s+",
    r"^(?:how much is|how much are|how much for)\s+",
    r"^(?:show me|find me|search for|i need|i want|looking for)\s+",
    r"^(?:do you sell)\s+",
    r"\s+(?:available|in stock|on arolana)$",
    r"\s+(?:price|cost)$",
)


def normalize_message(value: str) -> str:
    text = str(value or "").replace("’", "'").lower()
    text = _NOISE_PATTERN.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    replacements = {
        "al abotut": "all about",
        "abotut": "about",
        "aboutut": "about",
        "stttart": "start",
        "sttart": "start",
        "shoping": "shopping",
        "platfrom": "platform",
        "arolanna": "arolana",
        "ttoday": "today",
    }
    for wrong, right in replacements.items():
        text = re.sub(rf"\b{re.escape(wrong)}\b", right, text)
    return text


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
        CONVERSATIONAL_WELLBEING: WELLBEING_REPLY,
    }.get(intent, "")


def is_platform_information_question(message: str) -> bool:
    text = normalize_message(message)
    return _matches(text, PLATFORM_INFORMATION_PATTERNS)


def platform_information_reply() -> str:
    return PLATFORM_INFORMATION_REPLY


def resolve_customer_intent(message: str) -> str:
    text = normalize_message(message)

    # These phrases require the existing conversation state. Returning an
    # empty intent allows the context-aware marketplace/service router to
    # decide whether this continues a provider, product or support workflow.
    if _matches(text, CONTEXTUAL_FOLLOWUP_PATTERNS):
        return ""

    conversational = detect_conversational_intent(text)
    if conversational:
        return conversational

    if is_platform_information_question(text):
        return PLATFORM_INFORMATION

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

    # Non-catalogue marketplace domains must be detected before the broad
    # product-search patterns such as "I need" and "I want".
    if _matches(text, PROPERTY_PATTERNS):
        return PROPERTY_INTENT

    if _matches(text, VEHICLE_PATTERNS):
        return VEHICLE_INTENT

    if _matches(text, SOFTWARE_PATTERNS):
        return SOFTWARE_INTENT

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
