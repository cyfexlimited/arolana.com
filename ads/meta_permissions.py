"""Read-only Meta Ads OAuth permission readiness.

Only the canonical Ads permissions are retained.  Provider responses, tokens,
headers, and page credentials never leave this module or enter account
metadata.
"""
from django.utils import timezone

from .models import ExternalAdvertisingAccount


REQUIRED_META_ADS_SCOPES = (
    "ads_read",
    "ads_management",
    "business_management",
    "pages_show_list",
)


def normalize_granted_scopes(value):
    values = value.replace(",", " ").split() if isinstance(value, str) else value
    if not isinstance(values, (list, tuple, set)):
        values = []
    available = {str(item or "").strip().lower() for item in values}
    return [scope for scope in REQUIRED_META_ADS_SCOPES if scope in available]


def _result(granted, *, checked_at=None):
    granted = normalize_granted_scopes(granted)
    missing = [scope for scope in REQUIRED_META_ADS_SCOPES if scope not in granted]
    ready = not missing
    blockers = [] if ready else [
        "meta_ads_management_permission_required"
        if "ads_management" in missing else "meta_permission_required"
    ]
    return {
        "ready": ready,
        "status": "ready" if ready else "reconnect_required",
        "required_permissions": list(REQUIRED_META_ADS_SCOPES),
        "granted_permissions": granted,
        "missing_permissions": missing,
        "reconnect_required": not ready,
        "blockers": blockers,
        "checked_at": (checked_at or timezone.now()).isoformat(),
    }


def _account(identity, account_id):
    try:
        account = identity.external_accounts.select_related("credential").get(
            pk=account_id,
            channel=ExternalAdvertisingAccount.CHANNEL_META,
            status=ExternalAdvertisingAccount.STATUS_CONNECTED,
        )
    except (ExternalAdvertisingAccount.DoesNotExist, TypeError, ValueError):
        return None, "meta_account_not_accessible"
    if account.advertiser_identity_id != identity.pk:
        return None, "meta_account_not_accessible"
    return account, ""


def _failure(exc):
    from .providers import ProviderAuthorizationError
    if isinstance(exc, ProviderAuthorizationError):
        return "meta_auth_failed"
    return {
        "meta_rate_limited": "meta_rate_limited",
        "meta_permission_response_invalid": "meta_permission_response_invalid",
        "meta_provider_unavailable": "meta_provider_unavailable",
    }.get(str(exc), "meta_permission_check_failed")


def check(identity, account_id):
    """Perform the explicit GET-only permission check and retain safe scopes."""
    account, error = _account(identity, account_id)
    if error:
        return {**_result([]), "status": "not_ready", "blockers": [error]}
    credential = getattr(account, "credential", None)
    if not credential or credential.revoked_at:
        return {**_result([]), "status": "not_ready", "blockers": ["meta_auth_failed"]}
    try:
        from .providers import ProviderAPIError, ProviderAuthorizationError, provider_for
        granted = provider_for("meta").check_ads_permissions(credential, account)
    except (ProviderAPIError, ProviderAuthorizationError) as exc:
        failure = _failure(exc)
        # An invalid/revoked credential is actionable: offer the same explicit
        # reconnect path as a missing permission.  Transient and malformed
        # provider failures remain unavailable rather than encouraging a
        # needless reauthorization.
        if failure == "meta_auth_failed":
            return {
                **_result([]),
                "status": "reconnect_required",
                "reconnect_required": True,
                "blockers": [failure],
            }
        return {**_result([]), "status": "unavailable", "blockers": [failure]}
    # AdvertisingCredential.scopes already owns safe OAuth scope names.  Do
    # not create a second snapshot model or persist the provider response.
    safe_scopes = normalize_granted_scopes(granted)
    if credential.scopes != safe_scopes:
        credential.scopes = safe_scopes
        credential.save(update_fields=["scopes", "updated_at"])
    return _result(safe_scopes)
