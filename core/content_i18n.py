from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from django.contrib.contenttypes.models import ContentType

from .models import ContentTranslation


SUPPORTED_LANGUAGE_CODES = {
    "en", "pcm", "yo", "ig", "ha", "fr", "ar", "es", "pt", "de", "it", "zh",
    "hi", "bn", "ru", "ja", "ko", "tr", "nl", "sw", "zu", "af", "am", "so",
    "tw", "ee", "ff", "wo", "ln", "rw", "sn", "xh", "st", "mg", "vi", "th",
    "id", "ms", "fil", "ur", "fa", "he", "el", "pl", "uk", "ro", "cs", "sv",
    "no", "da", "fi",
}

LANGUAGE_ALIASES = {
    "english": "en",
    "pidgin": "pcm",
    "pidgin english": "pcm",
    "yoruba": "yo",
    "igbo": "ig",
    "hausa": "ha",
    "french": "fr",
    "chinese": "zh",
    "filipino": "fil",
    "twi": "tw",
    "ewe": "ee",
    "fula": "ff",
}


@lru_cache(maxsize=1)
def _system_catalog():
    path = Path(__file__).with_name("system_translation_catalog.json")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}


def normalize_language_code(value) -> str:
    raw = str(value or "").strip().lower().replace("_", "-")
    raw = raw.split(",", 1)[0].split(";", 1)[0].strip()
    raw = LANGUAGE_ALIASES.get(raw, raw)
    base = raw.split("-", 1)[0]
    return base if base in SUPPORTED_LANGUAGE_CODES else "en"


def get_request_language(request) -> str:
    if request is None:
        return "en"
    explicit = getattr(request, "language_code", "")
    if explicit:
        return normalize_language_code(explicit)
    return normalize_language_code(
        request.headers.get("Accept-Language")
        or request.META.get("HTTP_ACCEPT_LANGUAGE")
        or request.GET.get("lang")
        or "en"
    )


def translated_field(instance, field_name: str, request=None, language_code=None, default=None):
    fallback = getattr(instance, field_name, default)
    language = normalize_language_code(language_code or get_request_language(request))
    if language == "en" or not getattr(instance, "pk", None):
        return fallback

    content_type = ContentType.objects.get_for_model(instance, for_concrete_model=False)
    cache = getattr(request, "_arolana_translation_cache", None) if request is not None else None
    cache_key = (content_type.pk, instance.pk, language, field_name)
    if cache is not None and cache_key in cache:
        translated = cache[cache_key]
    else:
        translated = (
            ContentTranslation.objects.filter(
                content_type=content_type,
                object_id=instance.pk,
                language_code=language,
                field_name=field_name,
                is_active=True,
            )
            .values_list("translated_text", flat=True)
            .first()
        )
        if cache is not None:
            cache[cache_key] = translated
    return translated if translated not in (None, "") else fallback


def translated_key(key: str, default="", request=None, language_code=None):
    language = normalize_language_code(language_code or get_request_language(request))
    if language == "en":
        return default
    translated = (
        ContentTranslation.objects.filter(
            translation_key=key,
            language_code=language,
            is_active=True,
        )
        .values_list("translated_text", flat=True)
        .first()
    )
    if translated not in (None, ""):
        return translated
    return _system_catalog().get(language, {}).get(key, default)


def translated_fields(instance, field_names, request=None, language_code=None):
    return {
        field_name: translated_field(
            instance,
            field_name,
            request=request,
            language_code=language_code,
        )
        for field_name in field_names
    }


def prime_translations(request, instances):
    language = get_request_language(request)
    if language == "en":
        return
    cache = getattr(request, "_arolana_translation_cache", None)
    if cache is None:
        cache = {}
        request._arolana_translation_cache = cache

    grouped = {}
    for instance in instances:
        if not instance or not getattr(instance, "pk", None):
            continue
        content_type = ContentType.objects.get_for_model(instance, for_concrete_model=False)
        grouped.setdefault(content_type.pk, set()).add(instance.pk)

    for content_type_id, object_ids in grouped.items():
        translations = ContentTranslation.objects.filter(
            content_type_id=content_type_id,
            object_id__in=object_ids,
            language_code=language,
            is_active=True,
        ).values_list("object_id", "field_name", "translated_text")
        for object_id, field_name, translated_text in translations:
            cache[(content_type_id, object_id, language, field_name)] = translated_text


def translation_key_for_condition(value):
    safe_value = re.sub(r"[^a-z0-9_]+", "_", str(value or "").lower()).strip("_")
    return f"product.condition.{safe_value}"
