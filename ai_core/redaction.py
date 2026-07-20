import re


REDACTION_LABEL = "[REDACTED]"

SENSITIVE_KEYS = {
    "address",
    "email",
    "phone",
    "billing_address",
    "shipping_address",
    "bank_account",
    "account_number",
    "iban",
    "swift_code",
    "routing_number",
    "sort_code",
    "token",
    "api_token",
    "token_hash",
    "password",
    "pin",
    "otp",
    "secret",
    "webhook_payload",
    "gateway_response",
    "checkout_data",
    "manual_proof",
    "kyc",
    "government_id",
    "ip_address",
    "user_agent",
    "private_note",
    "fraud",
}

PII_PATTERNS = [
    re.compile(r"\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b", re.I),
    re.compile(r"(?:\+?\d[\d\s().-]{7,}\d)"),
]


def key_is_sensitive(key):
    normalized = str(key or "").lower()
    return any(marker in normalized for marker in SENSITIVE_KEYS)


def redact_text(value):
    text = str(value or "")
    for pattern in PII_PATTERNS:
        text = pattern.sub(REDACTION_LABEL, text)
    return text


def redact_mapping(value):
    if isinstance(value, dict):
        clean = {}
        for key, item in value.items():
            if key_is_sensitive(key):
                clean[key] = REDACTION_LABEL
            else:
                clean[key] = redact_mapping(item)
        return clean
    if isinstance(value, list):
        return [redact_mapping(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value
