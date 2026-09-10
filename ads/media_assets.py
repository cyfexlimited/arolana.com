"""Account-scoped provider media preparation without provider-side writes.

This module deliberately has no HTTP client dependency. Meta image preparation is
an explicit deterministic mock foundation until a separately authorized upload
phase exists.
"""

import hashlib
import re

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import AdvertisingMediaAsset, ExternalAdvertisingAccount


class MediaAssetError(Exception):
    """Safe, stable error for media resolution and state operations."""


_SENSITIVE_FAILURE = re.compile(r"access[_ -]?token|refresh[_ -]?token|bearer|secret", re.I)
_SAFE_FAILURE_CODE = re.compile(r"[^a-z0-9_:-]+")


def source_fingerprint(source_identity):
    """Return an opaque stable source identity; never persist the source path."""
    value = str(source_identity or "").strip()
    if not value or len(value) > 1024:
        raise MediaAssetError("invalid_media_source")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sanitize_failure(code, message=""):
    safe_code = _SAFE_FAILURE_CODE.sub("_", str(code or "provider_media_error").lower()).strip("_")[:80]
    safe_code = safe_code or "provider_media_error"
    raw_message = " ".join(str(message or "").split())
    if not raw_message:
        return safe_code, ""
    if _SENSITIVE_FAILURE.search(raw_message):
        return safe_code, "provider_media_error"
    return safe_code, raw_message[:240]


class AdvertisingMediaAssetService:
    def get_or_create(self, *, external_account, provider, media_type, source_identity):
        provider = str(provider or "").strip().lower()
        media_type = str(media_type or "").strip().lower()
        if provider != external_account.channel:
            raise MediaAssetError("media_provider_account_mismatch")
        if media_type not in {AdvertisingMediaAsset.MEDIA_IMAGE, AdvertisingMediaAsset.MEDIA_VIDEO}:
            raise MediaAssetError("unsupported_media_type")
        if external_account.status != ExternalAdvertisingAccount.STATUS_CONNECTED:
            raise MediaAssetError("external_account_not_connected")
        fingerprint = source_fingerprint(source_identity)
        defaults = {"provider": provider, "media_type": media_type}
        try:
            with transaction.atomic():
                media, _created = AdvertisingMediaAsset.objects.get_or_create(
                    external_account=external_account,
                    provider=provider,
                    media_type=media_type,
                    source_fingerprint=fingerprint,
                    defaults=defaults,
                )
        except IntegrityError:
            media = AdvertisingMediaAsset.objects.get(
                external_account=external_account,
                provider=provider,
                media_type=media_type,
                source_fingerprint=fingerprint,
            )
        return media

    def resolve_for_creative(self, *, execution, creative):
        account = getattr(execution, "external_account", None)
        if not account:
            raise MediaAssetError("missing_external_account")
        if creative.campaign_id != execution.campaign_id:
            raise MediaAssetError("media_creative_campaign_mismatch")
        if creative.campaign.advertiser_identity_id != account.advertiser_identity_id:
            raise MediaAssetError("media_external_account_advertiser_mismatch")
        if execution.advertiser_identity_id != account.advertiser_identity_id:
            raise MediaAssetError("media_execution_advertiser_mismatch")
        if creative.creative_type == "image":
            source = str(getattr(creative.image, "name", "") or "").strip()
            media_type = AdvertisingMediaAsset.MEDIA_IMAGE
        elif creative.creative_type == "video":
            source = str(creative.video_url or "").strip()
            media_type = AdvertisingMediaAsset.MEDIA_VIDEO
        else:
            raise MediaAssetError("media_creative_type_unsupported")
        if not source:
            raise MediaAssetError("media_source_required")
        return self.get_or_create(
            external_account=account,
            provider=execution.channel,
            media_type=media_type,
            source_identity=source,
        )

    def mark_processing(self, media):
        if media.status == AdvertisingMediaAsset.STATUS_READY:
            return media
        media.status = AdvertisingMediaAsset.STATUS_PROCESSING
        media.attempt_count += 1
        media.last_attempted_at = timezone.now()
        media.failure_code = ""
        media.failure_message = ""
        media.save(update_fields=[
            "status", "attempt_count", "last_attempted_at", "failure_code", "failure_message", "updated_at",
        ])
        return media

    def mark_ready(self, media, provider_media_id):
        identifier = str(provider_media_id or "").strip()
        if (
            not identifier
            or len(identifier) > 200
            or _SENSITIVE_FAILURE.search(identifier)
        ):
            raise MediaAssetError("invalid_provider_media_id")
        media.status = AdvertisingMediaAsset.STATUS_READY
        media.provider_media_id = identifier
        media.failure_code = ""
        media.failure_message = ""
        media.save(update_fields=["status", "provider_media_id", "failure_code", "failure_message", "updated_at"])
        return media

    def mark_failed(self, media, *, code, message=""):
        media.failure_code, media.failure_message = sanitize_failure(code, message)
        media.status = AdvertisingMediaAsset.STATUS_FAILED
        media.save(update_fields=["status", "failure_code", "failure_message", "updated_at"])
        return media

    def mock_upload_meta_image(self, media):
        """Deterministic test-only image preparation; performs no provider request."""
        if media.provider != ExternalAdvertisingAccount.CHANNEL_META:
            raise MediaAssetError("media_provider_account_mismatch")
        if media.media_type != AdvertisingMediaAsset.MEDIA_IMAGE:
            raise MediaAssetError("meta_media_type_unsupported")
        if media.status == AdvertisingMediaAsset.STATUS_READY and media.provider_media_id:
            return media
        self.mark_processing(media)
        fake_hash = hashlib.sha256(
            f"meta-image:{media.external_account_id}:{media.source_fingerprint}".encode("utf-8")
        ).hexdigest()
        return self.mark_ready(media, fake_hash)


advertising_media_asset_service = AdvertisingMediaAssetService()
