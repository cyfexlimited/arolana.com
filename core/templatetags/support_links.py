import re
from urllib.parse import parse_qs, quote, urlparse

from django import template
from django.conf import settings

register = template.Library()

FALLBACK_WHATSAPP_NUMBER = "2349132924620"

FALLBACK_CART_SUPPORT_MESSAGE = (
    "Hello Arolana Support, I am contacting you from the cart page.\n\n"
    "I need help with my cart, checkout, delivery, payment, or order support "
    "before completing my purchase."
)


def _digits(value):
    return re.sub(r"\D+", "", str(value or ""))


def _extract_phone_from_url(value):
    value = str(value or "").strip()
    if not value:
        return ""

    parsed = urlparse(value)
    query = parse_qs(parsed.query or "")

    for key in ("phone", "number", "to"):
        if query.get(key):
            phone = _digits(query[key][0])
            if phone:
                return phone

    path_phone = _digits(parsed.path)
    if path_phone:
        return path_phone

    return _digits(value)


def _normalize_phone(value):
    phone = _extract_phone_from_url(value)

    if not phone:
        return ""

    if phone.startswith("00"):
        phone = phone[2:]

    if phone.startswith("0") and len(phone) >= 10:
        phone = "234" + phone.lstrip("0")

    if len(phone) == 10 and phone.startswith(("7", "8", "9")):
        phone = "234" + phone

    return phone


def _setting_value(*names):
    for name in names:
        value = getattr(settings, name, None)
        if value:
            return value
    return ""


def _site_settings_value(site_settings, *names):
    if not site_settings:
        return ""

    for name in names:
        value = getattr(site_settings, name, None)
        if value:
            return value

    return ""


def _cart_support_message(site_settings):
    message = (
        _site_settings_value(
            site_settings,
            "cart_whatsapp_message",
            "support_cart_whatsapp_message",
            "whatsapp_cart_message",
            "support_whatsapp_message",
        )
        or _setting_value(
            "AROLANA_CART_WHATSAPP_MESSAGE",
            "CART_WHATSAPP_MESSAGE",
            "SUPPORT_WHATSAPP_MESSAGE",
        )
        or FALLBACK_CART_SUPPORT_MESSAGE
    )

    message = str(message or "").strip()
    return message or FALLBACK_CART_SUPPORT_MESSAGE


@register.simple_tag(takes_context=True)
def cart_whatsapp_support_url(context):
    site_settings = context.get("site_settings")

    candidates = [
        _site_settings_value(
            site_settings,
            "support_whatsapp_number",
            "support_whatsapp",
            "support_whatsapp_url",
            "whatsapp_number",
            "whatsapp_phone",
            "whatsapp_url",
            "support_phone",
            "support_phone_number",
            "phone",
            "phone_number",
        ),
        context.get("support_whatsapp_number"),
        context.get("support_whatsapp"),
        context.get("support_whatsapp_url"),
        _setting_value(
            "AROLANA_SUPPORT_WHATSAPP_NUMBER",
            "AROLANA_SUPPORT_WHATSAPP",
            "SUPPORT_WHATSAPP_NUMBER",
            "SUPPORT_WHATSAPP",
            "SITE_WHATSAPP_NUMBER",
            "WHATSAPP_NUMBER",
            "SUPPORT_PHONE_NUMBER",
            "SUPPORT_PHONE",
        ),
        context.get("support_phone_tel"),
        context.get("support_phone_display"),
        FALLBACK_WHATSAPP_NUMBER,
    ]

    phone = ""

    for candidate in candidates:
        phone = _normalize_phone(candidate)
        if phone:
            break

    if not phone:
        phone = FALLBACK_WHATSAPP_NUMBER

    message = _cart_support_message(site_settings)
    return f"https://wa.me/{phone}?text={quote(message)}"