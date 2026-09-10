"""Safe management-facing state for mock Meta creative preparation."""
from .creative_preparation import CreativePreparationError, canonical_meta_payload, creative_preparation_service, payload_fingerprint
from .media_assets import source_fingerprint
from .models import AdvertisingCreativePreparation, AdvertisingMediaAsset, ExternalAdvertisingAccount


def _account(identity, account_id):
    try:
        return identity.external_accounts.get(pk=account_id, channel="meta", status="connected")
    except (ExternalAdvertisingAccount.DoesNotExist, TypeError, ValueError):
        return None


def _media(creative, account):
    source = str(getattr(creative.image, "name", "") or "") if creative.creative_type == "image" else str(creative.video_url or "")
    if not source: return None
    kind = "image" if creative.creative_type == "image" else "video"
    return AdvertisingMediaAsset.objects.filter(external_account=account, provider="meta", media_type=kind, source_fingerprint=source_fingerprint(source)).first()


def status(identity, creative, account_id=None):
    accounts = [{"id": a.pk, "display_name": a.display_name[:200] or "Meta account"} for a in identity.external_accounts.filter(channel="meta", status="connected").order_by("display_name", "pk")]
    account = _account(identity, account_id) if account_id else None
    blockers = []
    if not account: blockers.append("meta_account_required")
    if account and not str((account.metadata or {}).get("meta_page_id") or "").isdigit(): blockers.append("meta_page_required")
    media = _media(creative, account) if account else None
    if account and not media: blockers.append("media_required")
    elif media and media.status != "ready": blockers.append("media_not_ready")
    if creative.creative_type == "video": blockers.append("video_provider_media_not_ready")
    elif creative.creative_type in {"native", "carousel"}: blockers.append("unsupported_creative_type")
    current = None
    stale = False
    if account and media and not blockers:
        try:
            fingerprint = payload_fingerprint(canonical_meta_payload(campaign=creative.campaign, creative=creative, external_account=account, media_asset=media))
            current = AdvertisingCreativePreparation.objects.filter(creative=creative, external_account=account, provider="meta", payload_fingerprint=fingerprint).first()
            stale = not current and AdvertisingCreativePreparation.objects.filter(creative=creative, external_account=account, provider="meta", status="prepared").exists()
        except CreativePreparationError as exc: blockers.append(str(exc))
    if current and current.status == "prepared": state = "prepared"
    elif current and current.status == "failed": state = "failed"
    elif stale: state = "stale"
    elif blockers: state = "not_ready"
    else: state = "ready_to_prepare"
    return {"accounts": accounts, "provider": "meta", "status": state, "prepared": state == "prepared", "account_connected": bool(account), "page_selected": bool(account and not "meta_page_required" in blockers), "media_ready": bool(media and media.status == "ready"), "attempt_count": current.attempt_count if current else 0, "last_attempted_at": current.last_attempted_at if current else None, "failure_code": current.failure_code if current else "", "failure_message": current.failure_message if current else "", "blockers": blockers, "_account": account, "_media": media, "_current": current}


def prepare(identity, creative, account_id, *, retry=False):
    result = status(identity, creative, account_id)
    if retry:
        if result["status"] != "failed": raise CreativePreparationError("creative_preparation_retry_not_allowed")
    elif result["status"] not in {"ready_to_prepare", "prepared"}: raise CreativePreparationError(result["blockers"][0] if result["blockers"] else "creative_preparation_not_ready")
    if result["status"] == "prepared": return result
    creative_preparation_service.prepare_meta(campaign=creative.campaign, creative=creative, external_account=result["_account"], media_asset=result["_media"])
    return status(identity, creative, account_id)


def safe(result):
    return {key: value for key, value in result.items() if not key.startswith("_")}
