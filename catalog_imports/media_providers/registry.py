import os

from django.conf import settings

from .base import MediaProviderConfigurationError


_PROVIDERS = {}


def register_provider(key, provider):
    _PROVIDERS[str(key).strip().lower()] = provider


def configured_provider_key():
    value = str(getattr(settings, "CATALOG_IMPORT_MEDIA_PROVIDER", "") or "").strip()
    if not value:
        value = str(os.environ.get("CATALOG_IMPORT_MEDIA_PROVIDER", "") or "").strip()
    if not value:
        try:
            from decouple import config
            value = str(config("CATALOG_IMPORT_MEDIA_PROVIDER", default="openai") or "").strip()
        except Exception:
            value = "openai"
    return value.lower() or "openai"


def get_provider(key=None):
    provider_key = str(key or configured_provider_key()).strip().lower()
    if provider_key not in _PROVIDERS:
        # Lazy import keeps optional provider dependencies out of app startup.
        if provider_key == "openai":
            from .openai_images import OpenAIImageProvider
            _PROVIDERS[provider_key] = OpenAIImageProvider()
    provider = _PROVIDERS.get(provider_key)
    if provider is None:
        raise MediaProviderConfigurationError(
            f"Unknown catalog import media provider: {provider_key}."
        )
    return provider
