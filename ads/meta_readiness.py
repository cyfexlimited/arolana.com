"""Read-only Meta publish-readiness preflight.

This module compares current internal records with the M8--M10 fingerprints.
It deliberately has no provider client and never invokes a preparation service.
"""
from django.utils import timezone

from .ad_resource_management import _media, status as ad_resource_status
from .creative_preparation import CreativePreparationError, canonical_meta_payload, payload_fingerprint
from .models import (
    AdChannelExecution,
    AdvertisingCreativePreparation,
    AdvertisingMediaAsset,
    ExternalAdvertisingAccount,
)


def _selected_account(identity, account_id):
    if not account_id:
        return None, "meta_account_required"
    try:
        account = identity.external_accounts.get(pk=account_id)
    except (ExternalAdvertisingAccount.DoesNotExist, TypeError, ValueError):
        return None, "meta_account_invalid"
    if account.channel != ExternalAdvertisingAccount.CHANNEL_META or account.status != ExternalAdvertisingAccount.STATUS_CONNECTED:
        return None, "meta_account_invalid"
    return account, ""


def _page_is_selected(account):
    return str((account.metadata or {}).get("meta_page_id") or "").strip().isdigit()


def _historical_preparation(creative, account):
    return AdvertisingCreativePreparation.objects.filter(
        creative=creative, external_account=account, provider="meta", status=AdvertisingCreativePreparation.STATUS_PREPARED,
    ).exists()


def check(identity, creative, account_id=None):
    """Return only safe, deterministic readiness state without writing records."""
    blockers = []
    account, account_error = _selected_account(identity, account_id)
    if account_error:
        blockers.append(account_error)
    elif creative.campaign.advertiser_identity_id != identity.pk or account.advertiser_identity_id != identity.pk:
        blockers.append("provider_context_mismatch")
    elif not _page_is_selected(account):
        blockers.append("meta_page_required")
    elif (account.metadata or {}).get("meta_page_verification_required") is True:
        blockers.append("meta_page_verification_required")
    elif creative.campaign.status not in {"pending", "scheduled"}:
        blockers.append("campaign_not_eligible")

    execution = media = preparation = None
    if not blockers:
        execution = AdChannelExecution.objects.filter(
            campaign=creative.campaign,
            advertiser_identity=identity,
            channel=ExternalAdvertisingAccount.CHANNEL_META,
            external_account=account,
        ).first()
        if not execution or not str(execution.external_campaign_id or "").startswith("mock_meta_campaign_"):
            blockers.append("parent_campaign_not_ready")
        elif not str(execution.external_ad_group_id or "").startswith("mock_meta_adset_"):
            blockers.append("parent_adset_not_ready")

        media = _media(creative, account)
        if not media:
            other_media = AdvertisingMediaAsset.objects.filter(
                external_account__advertiser_identity=identity,
                provider="meta", media_type="image", status=AdvertisingMediaAsset.STATUS_READY,
            ).exclude(external_account=account).exists()
            blockers.append("provider_context_mismatch" if other_media else "media_not_ready")
        elif media.provider != "meta" or media.external_account_id != account.pk:
            blockers.append("provider_context_mismatch")
        elif media.status != AdvertisingMediaAsset.STATUS_READY:
            blockers.append("media_not_ready")

        if creative.creative_type != "image":
            blockers.append("unsupported_creative_type")

    if not blockers:
        try:
            creative_fingerprint = payload_fingerprint(canonical_meta_payload(
                campaign=creative.campaign, creative=creative, external_account=account, media_asset=media,
            ))
        except CreativePreparationError as exc:
            code = str(exc)
            blockers.append("meta_page_required" if "page" in code else "media_not_ready" if "media" in code else "creative_not_prepared")
        else:
            preparation = AdvertisingCreativePreparation.objects.filter(
                creative=creative, external_account=account, provider="meta", payload_fingerprint=creative_fingerprint,
            ).first()
            if not preparation:
                blockers.append("creative_preparation_stale" if _historical_preparation(creative, account) else "creative_not_prepared")
            elif preparation.status != AdvertisingCreativePreparation.STATUS_PREPARED:
                blockers.append("creative_not_prepared")

    if not blockers:
        # M10 owns the canonical Ad-resource fingerprint. Reuse its read-only
        # status calculation so the preflight cannot drift from M10's contract.
        resource_state = ad_resource_status(identity, creative, account.pk)
        if resource_state["status"] != "prepared":
            existing = resource_state.get("blockers") or []
            if resource_state["status"] == "stale":
                blockers.append("ad_resource_stale")
            elif "creative_preparation_stale" in existing:
                blockers.append("creative_preparation_stale")
            elif "unsupported_creative_type" in existing:
                blockers.append("unsupported_creative_type")
            elif "parent_adset_not_ready" in existing:
                blockers.append("parent_adset_not_ready")
            else:
                blockers.append("ad_resource_not_prepared")

    return {
        "ready": not blockers,
        "status": "ready" if not blockers else "not_ready",
        "blockers": blockers,
        "checked_at": timezone.now().isoformat(),
    }
