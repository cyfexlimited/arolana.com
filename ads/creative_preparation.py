"""Mock-only canonical provider creative preparation; no HTTP dependencies."""
import hashlib
import json
import re

from django.core.validators import URLValidator
from django.db import IntegrityError, transaction
from django.utils import timezone

from .media_assets import sanitize_failure
from .models import AdvertisingCreativePreparation, AdvertisingMediaAsset, ExternalAdvertisingAccount


class CreativePreparationError(Exception):
    pass


CTA_MAP = {"contact us": "CONTACT_US", "get quote": "GET_QUOTE", "learn more": "LEARN_MORE", "shop now": "SHOP_NOW", "sign up": "SIGN_UP", "watch more": "WATCH_MORE"}
_url_validator = URLValidator(schemes=["http", "https"])


def _url(value):
    value = str(value or "").strip()
    try:
        _url_validator(value)
    except Exception as exc:
        raise CreativePreparationError("meta_creative_destination_url_invalid") from exc
    if not value or not re.match(r"^https?://", value, re.I):
        raise CreativePreparationError("meta_creative_destination_url_invalid")
    return value


def canonical_meta_payload(*, campaign, creative, external_account, media_asset):
    if creative.campaign_id != campaign.pk:
        raise CreativePreparationError("meta_creative_campaign_mismatch")
    if campaign.advertiser_identity_id != external_account.advertiser_identity_id:
        raise CreativePreparationError("meta_creative_external_account_advertiser_mismatch")
    if external_account.channel != ExternalAdvertisingAccount.CHANNEL_META or external_account.status != ExternalAdvertisingAccount.STATUS_CONNECTED:
        raise CreativePreparationError("meta_creative_external_account_invalid")
    page_id = str((external_account.metadata or {}).get("meta_page_id") or "").strip()
    if not re.fullmatch(r"\d+", page_id):
        raise CreativePreparationError("meta_creative_page_identity_required")
    if media_asset.external_account_id != external_account.pk or media_asset.provider != "meta":
        raise CreativePreparationError("meta_media_external_account_mismatch")
    if creative.creative_type == "video":
        raise CreativePreparationError("meta_video_creative_upload_not_implemented")
    if creative.creative_type != "image":
        raise CreativePreparationError("meta_creative_type_unsupported")
    if media_asset.media_type != "image":
        raise CreativePreparationError("meta_media_type_unsupported")
    if media_asset.status != AdvertisingMediaAsset.STATUS_READY:
        raise CreativePreparationError("meta_creative_media_not_ready")
    image_hash = str(media_asset.provider_media_id or "").strip()
    if not re.fullmatch(r"[a-fA-F0-9]{16,128}", image_hash):
        raise CreativePreparationError("meta_creative_image_hash_required")
    headline = str(creative.headline or "").strip()
    description = str(creative.description or "").strip()
    if not headline:
        raise CreativePreparationError("meta_creative_headline_required")
    if not description:
        raise CreativePreparationError("meta_creative_description_required")
    cta = CTA_MAP.get(str(creative.cta_text or "").strip().lower())
    if not cta:
        raise CreativePreparationError("meta_creative_cta_unsupported")
    link = _url(creative.clickthrough_url)
    return {"name": str(creative.name or "").strip()[:200], "object_story_spec": {"page_id": page_id, "link_data": {"link": link, "image_hash": image_hash, "name": headline, "message": description, "call_to_action": {"type": cta, "value": {"link": link}}}}}


def payload_fingerprint(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class CreativePreparationService:
    def prepare_meta(self, *, campaign, creative, external_account, media_asset):
        payload = canonical_meta_payload(campaign=campaign, creative=creative, external_account=external_account, media_asset=media_asset)
        fingerprint = payload_fingerprint(payload)
        try:
            with transaction.atomic():
                record, _ = AdvertisingCreativePreparation.objects.get_or_create(creative=creative, external_account=external_account, provider="meta", payload_fingerprint=fingerprint)
        except IntegrityError:
            record = AdvertisingCreativePreparation.objects.get(creative=creative, external_account=external_account, provider="meta", payload_fingerprint=fingerprint)
        if record.status == record.STATUS_PREPARED and record.mock_resource_id:
            return record, payload
        record.status = record.STATUS_PREPARED
        record.attempt_count += 1
        record.last_attempted_at = timezone.now()
        record.failure_code = record.failure_message = ""
        record.mock_resource_id = "mock_meta_creative_" + hashlib.sha256(f"{external_account.pk}:{fingerprint}".encode()).hexdigest()[:32]
        record.save(update_fields=["status", "attempt_count", "last_attempted_at", "failure_code", "failure_message", "mock_resource_id", "updated_at"])
        return record, payload

    def mark_failed(self, record, code, message=""):
        record.failure_code, record.failure_message = sanitize_failure(code, message)
        record.status = record.STATUS_FAILED
        record.save(update_fields=["status", "failure_code", "failure_message", "updated_at"])
        return record


creative_preparation_service = CreativePreparationService()
