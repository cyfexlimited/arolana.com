"""Mock-only, account-scoped Meta Ad resource preparation.

This module deliberately has no provider client or HTTP dependency.  It models
the future Meta Ad boundary while keeping the result internal and paused.
"""
import hashlib
import json

from django.db import IntegrityError, transaction
from django.utils import timezone

from .creative_preparation import CreativePreparationError, canonical_meta_payload, payload_fingerprint
from .media_assets import sanitize_failure, source_fingerprint
from .models import (
    AdChannelExecution,
    AdvertisingAdResource,
    AdvertisingCreativePreparation,
    AdvertisingMediaAsset,
    ExternalAdvertisingAccount,
)


class AdResourceError(Exception):
    """Stable, safe failure code for mock Ad resource operations."""


def _account(identity, account_id):
    try:
        return identity.external_accounts.get(pk=account_id, channel="meta", status="connected")
    except (ExternalAdvertisingAccount.DoesNotExist, TypeError, ValueError):
        return None


def _media(creative, account):
    source = str(getattr(creative.image, "name", "") or "") if creative.creative_type == "image" else str(creative.video_url or "")
    if not source:
        return None
    kind = "image" if creative.creative_type == "image" else "video"
    return AdvertisingMediaAsset.objects.filter(
        external_account=account, provider="meta", media_type=kind,
        source_fingerprint=source_fingerprint(source),
    ).first()


def _campaign_context_fingerprint(campaign):
    value = {
        "objective": campaign.objective,
        "budget_type": campaign.budget_type,
        "daily_budget": str(campaign.daily_budget or ""),
        "total_budget": str(campaign.total_budget or ""),
        "max_bid": str(campaign.max_bid or ""),
        "start_date": campaign.start_date.isoformat() if campaign.start_date else "",
        "end_date": campaign.end_date.isoformat() if campaign.end_date else "",
        "targeting": campaign.targeting,
        "geo_targeting": campaign.geo_targeting,
        "device_targeting": campaign.device_targeting,
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def canonical_meta_ad_payload(*, campaign, execution, creative_preparation):
    """Canonical internal payload only; never return this through management APIs."""
    parent_id = str(execution.external_ad_group_id or "").strip()
    if not parent_id.startswith("mock_meta_adset_"):
        raise AdResourceError("parent_adset_not_ready")
    if creative_preparation.status != AdvertisingCreativePreparation.STATUS_PREPARED:
        raise AdResourceError("creative_not_prepared")
    return {
        "name": str(campaign.name or "")[:200],
        "parent_adset_reference": hashlib.sha256(f"meta-adset:{execution.pk}:{parent_id}".encode()).hexdigest(),
        "prepared_creative_reference": creative_preparation.payload_fingerprint,
        "campaign_context_reference": _campaign_context_fingerprint(campaign),
        "status": "PAUSED",
    }


class AdvertisingAdResourceService:
    def prepare_meta(self, *, campaign, creative, execution, creative_preparation, external_account, media_asset):
        if campaign.status not in {"pending", "scheduled"}:
            raise AdResourceError("unsupported_campaign_state")
        if creative.campaign_id != campaign.pk:
            raise AdResourceError("creative_campaign_mismatch")
        if external_account.channel != "meta" or external_account.status != ExternalAdvertisingAccount.STATUS_CONNECTED:
            raise AdResourceError("meta_account_required")
        if campaign.advertiser_identity_id != external_account.advertiser_identity_id:
            raise AdResourceError("campaign_account_mismatch")
        if (
            execution.campaign_id != campaign.pk or execution.external_account_id != external_account.pk
            or execution.channel != "meta" or execution.advertiser_identity_id != campaign.advertiser_identity_id
        ):
            raise AdResourceError("parent_adset_not_ready")
        if (
            creative_preparation.creative_id != creative.pk or creative_preparation.external_account_id != external_account.pk
            or creative_preparation.provider != "meta" or creative_preparation.status != AdvertisingCreativePreparation.STATUS_PREPARED
        ):
            raise AdResourceError("creative_not_prepared")
        try:
            current_creative_fingerprint = payload_fingerprint(canonical_meta_payload(
                campaign=campaign, creative=creative, external_account=external_account, media_asset=media_asset,
            ))
        except CreativePreparationError as exc:
            raise AdResourceError(str(exc)) from exc
        if current_creative_fingerprint != creative_preparation.payload_fingerprint:
            raise AdResourceError("creative_preparation_stale")
        payload = canonical_meta_ad_payload(
            campaign=campaign, execution=execution, creative_preparation=creative_preparation,
        )
        fingerprint = payload_fingerprint(payload)
        try:
            with transaction.atomic():
                record, _created = AdvertisingAdResource.objects.get_or_create(
                    execution=execution,
                    creative_preparation=creative_preparation,
                    payload_fingerprint=fingerprint,
                    defaults={
                        "campaign": campaign,
                        "creative": creative,
                        "external_account": external_account,
                        "provider": "meta",
                    },
                )
        except IntegrityError:
            record = AdvertisingAdResource.objects.get(
                execution=execution, creative_preparation=creative_preparation, payload_fingerprint=fingerprint,
            )
        if record.status == AdvertisingAdResource.STATUS_PREPARED and record.mock_resource_id:
            return record, payload
        record.status = AdvertisingAdResource.STATUS_PREPARED
        record.attempt_count += 1
        record.last_attempted_at = timezone.now()
        record.failure_code = record.failure_message = ""
        record.mock_resource_id = "mock_meta_ad_" + hashlib.sha256(
            f"{external_account.pk}:{fingerprint}".encode()
        ).hexdigest()[:32]
        record.save(update_fields=[
            "status", "attempt_count", "last_attempted_at", "failure_code", "failure_message",
            "mock_resource_id", "updated_at",
        ])
        return record, payload

    def mark_failed(self, record, code, message=""):
        record.failure_code, record.failure_message = sanitize_failure(code, message)
        record.status = AdvertisingAdResource.STATUS_FAILED
        record.save(update_fields=["status", "failure_code", "failure_message", "updated_at"])
        return record


advertising_ad_resource_service = AdvertisingAdResourceService()


def status(identity, creative, account_id=None):
    accounts = [
        {"id": account.pk, "display_name": account.display_name[:200] or "Meta account"}
        for account in identity.external_accounts.filter(channel="meta", status="connected").order_by("display_name", "pk")
    ]
    account = _account(identity, account_id) if account_id else None
    blockers = []
    execution = None
    media = None
    preparation = None
    ad_payload = None
    fingerprint = ""
    if not account:
        blockers.append("meta_account_required")
    elif not str((account.metadata or {}).get("meta_page_id") or "").isdigit():
        blockers.append("meta_page_required")
    elif creative.campaign.advertiser_identity_id != identity.pk:
        blockers.append("campaign_account_mismatch")
    elif creative.campaign.status not in {"pending", "scheduled"}:
        blockers.append("unsupported_campaign_state")
    else:
        execution = AdChannelExecution.objects.filter(
            campaign=creative.campaign, advertiser_identity=identity, channel="meta", external_account=account,
        ).first()
        if not execution or not str(execution.external_ad_group_id or "").startswith("mock_meta_adset_"):
            blockers.append("parent_adset_not_ready")
        media = _media(creative, account)
        if not media:
            blockers.append("media_not_ready")
        elif media.status != AdvertisingMediaAsset.STATUS_READY:
            blockers.append("media_not_ready")
        if creative.creative_type != "image":
            blockers.append("unsupported_creative_type")
        if not blockers:
            try:
                creative_payload = canonical_meta_payload(
                    campaign=creative.campaign, creative=creative, external_account=account, media_asset=media,
                )
                creative_fingerprint = payload_fingerprint(creative_payload)
                preparation = AdvertisingCreativePreparation.objects.filter(
                    creative=creative, external_account=account, provider="meta", payload_fingerprint=creative_fingerprint,
                ).first()
                if not preparation:
                    old = AdvertisingCreativePreparation.objects.filter(
                        creative=creative, external_account=account, provider="meta", status="prepared"
                    ).exists()
                    blockers.append("creative_preparation_stale" if old else "creative_not_prepared")
                elif preparation.status != AdvertisingCreativePreparation.STATUS_PREPARED:
                    blockers.append("creative_not_prepared")
                else:
                    ad_payload = canonical_meta_ad_payload(
                        campaign=creative.campaign, execution=execution, creative_preparation=preparation,
                    )
                    fingerprint = payload_fingerprint(ad_payload)
            except CreativePreparationError as exc:
                blockers.append(str(exc))
            except AdResourceError as exc:
                blockers.append(str(exc))
    resource = None
    if fingerprint:
        resource = AdvertisingAdResource.objects.filter(
            execution=execution, creative_preparation=preparation, payload_fingerprint=fingerprint,
        ).first()
    historical = bool(execution and AdvertisingAdResource.objects.filter(execution=execution, status="prepared").exists())
    if resource and resource.status == AdvertisingAdResource.STATUS_PREPARED:
        state = "prepared"
    elif resource and resource.status == AdvertisingAdResource.STATUS_FAILED:
        state = "failed"
    elif historical and (blockers or not resource):
        state = "stale"
    elif blockers:
        state = "not_ready"
    else:
        state = "ready_to_prepare"
    return {
        "accounts": accounts, "provider": "meta", "status": state,
        "prepared": state == "prepared", "account_connected": bool(account),
        "page_selected": bool(account and str((account.metadata or {}).get("meta_page_id") or "").isdigit()),
        "media_ready": bool(media and media.status == AdvertisingMediaAsset.STATUS_READY),
        "attempt_count": resource.attempt_count if resource else 0,
        "last_attempted_at": resource.last_attempted_at if resource else None,
        "failure_code": resource.failure_code if resource else "",
        "failure_message": resource.failure_message if resource else "",
        "blockers": blockers,
        "_account": account, "_execution": execution, "_preparation": preparation, "_media": media,
        "_resource": resource, "_payload": ad_payload,
    }


def prepare(identity, creative, account_id, *, retry=False):
    result = status(identity, creative, account_id)
    if retry:
        if result["status"] != "failed":
            raise AdResourceError("ad_resource_retry_not_allowed")
    elif result["status"] not in {"ready_to_prepare", "prepared"}:
        raise AdResourceError(result["blockers"][0] if result["blockers"] else "ad_resource_not_ready")
    if result["status"] == "prepared":
        return result
    advertising_ad_resource_service.prepare_meta(
        campaign=creative.campaign, creative=creative, execution=result["_execution"],
        creative_preparation=result["_preparation"], external_account=result["_account"], media_asset=result["_media"],
    )
    return status(identity, creative, account_id)


def safe(result):
    return {key: value for key, value in result.items() if not key.startswith("_")}
