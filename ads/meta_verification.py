"""Explicit M13 live Meta verification; provider reads only."""
import hashlib
import json
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from .models import ExternalAdvertisingAccount, MetaVerificationReceipt
from .meta_runtime import freshness_seconds
from .providers import ProviderAPIError, ProviderAuthorizationError, provider_for


def _account(identity, account_id):
    if not account_id:
        return None, "meta_account_required"
    try:
        account = identity.external_accounts.select_related("credential").get(pk=account_id)
    except (ExternalAdvertisingAccount.DoesNotExist, TypeError, ValueError):
        return None, "meta_account_not_accessible"
    if account.channel != ExternalAdvertisingAccount.CHANNEL_META:
        return None, "meta_account_not_accessible"
    if account.status != ExternalAdvertisingAccount.STATUS_CONNECTED:
        return None, "meta_connection_expired"
    return account, ""


def _result(status, blockers=()):
    return {"verified": status == "verified", "status": status, "blockers": list(blockers), "checked_at": timezone.now().isoformat()}


def context_fingerprint(creative, account):
    """Opaque identity/page binding for verification freshness; no page ID leaks."""
    page_id = str((account.metadata or {}).get("meta_page_id") or "").strip()
    value = {"creative": creative.pk, "campaign": creative.campaign_id, "account": account.pk, "page": page_id}
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def record_verified_receipt(creative, account):
    now = timezone.now()
    max_age = freshness_seconds("META_ADS_VERIFICATION_MAX_AGE_SECONDS")
    return MetaVerificationReceipt.objects.create(
        creative=creative,
        external_account=account,
        context_fingerprint=context_fingerprint(creative, account),
        verified_at=now,
        expires_at=now + timedelta(seconds=max_age),
    )


def _provider_failure(exc):
    reason = str(exc)
    if isinstance(exc, ProviderAuthorizationError):
        return "meta_permission_insufficient" if reason == "meta_authorization_failed" else "meta_connection_expired"
    return {
        "meta_account_mismatch": "meta_account_mismatch",
        "meta_page_required": "meta_page_required",
        "meta_page_not_accessible": "meta_page_not_accessible",
        "meta_response_invalid": "meta_response_invalid",
        "meta_provider_unavailable": "meta_provider_unavailable",
    }.get(reason, "meta_provider_unavailable")


def verify(identity, creative, account_id=None, *, persist_receipt=False):
    """Perform the sole explicit live check.  Provider work remains GET-only."""
    account, error = _account(identity, account_id)
    if error:
        return _result("not_verified", [error])
    if creative.campaign.advertiser_identity_id != identity.pk or account.advertiser_identity_id != identity.pk:
        return _result("not_verified", ["meta_account_not_accessible"])
    page_id = str((account.metadata or {}).get("meta_page_id") or "").strip()
    if not page_id:
        return _result("not_verified", ["meta_page_required"])
    credential = getattr(account, "credential", None)
    if not credential or credential.revoked_at:
        return _result("not_verified", ["meta_connection_expired"])
    try:
        provider_for("meta").verify_connected_account_and_page(credential, account)
    except (ProviderAuthorizationError, ProviderAPIError) as exc:
        blocker = _provider_failure(exc)
        return _result("unavailable" if blocker == "meta_provider_unavailable" else "not_verified", [blocker])
    if (account.metadata or {}).get("meta_page_verification_required") is True:
        account.metadata = {**(account.metadata or {}), "meta_page_verification_required": False}
        account.save(update_fields=["metadata", "updated_at"])
    if persist_receipt:
        record_verified_receipt(creative, account)
    return _result("verified")
