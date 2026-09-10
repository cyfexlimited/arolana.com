"""Explicit, request-scoped live Meta verification; provider reads only."""
from django.utils import timezone

from .models import ExternalAdvertisingAccount
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


def verify(identity, creative, account_id=None):
    """Perform the sole explicit live check; do not write locally or remotely."""
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
    return _result("verified")
