"""Read-only Meta Ads OAuth permission readiness and freshness.

Only the canonical Ads permissions are retained.  Provider responses, tokens,
headers, and page credentials never leave this module or enter account
metadata.
"""
import hashlib
import json
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import ExternalAdvertisingAccount, MetaPermissionReceipt
from .meta_runtime import freshness_seconds


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


def _max_age():
    return freshness_seconds("META_ADS_PERMISSION_MAX_AGE_SECONDS")


def context_fingerprint(account, credential):
    value = {
        "account": account.pk,
        "advertiser": account.advertiser_identity_id,
        "external_account": account.external_account_id,
        "credential_version": credential.credential_version,
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _result(granted, *, checked_at=None, status=None, reconnect_required=None, blockers=None):
    granted = normalize_granted_scopes(granted)
    missing = [scope for scope in REQUIRED_META_ADS_SCOPES if scope not in granted]
    ready = not missing
    default_blockers = [] if ready else [
        "meta_ads_management_permission_required"
        if "ads_management" in missing else "meta_permission_required"
    ]
    return {
        "ready": ready,
        "status": status or ("ready" if ready else "reconnect_required"),
        "required_permissions": list(REQUIRED_META_ADS_SCOPES),
        "granted_permissions": granted,
        "missing_permissions": missing,
        "reconnect_required": (not ready) if reconnect_required is None else reconnect_required,
        "blockers": default_blockers if blockers is None else blockers,
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


def _store(account, credential, result):
    """Persist only bounded readiness data, never Graph response data."""
    status = result["status"]
    status = status if status in {choice for choice, _label in MetaPermissionReceipt.STATUS_CHOICES} else MetaPermissionReceipt.STATUS_UNAVAILABLE
    with transaction.atomic():
        receipt, _created = MetaPermissionReceipt.objects.select_for_update().get_or_create(
            external_account=account,
            defaults={
                "advertiser_identity": account.advertiser_identity,
                "credential_version": credential.credential_version,
                "context_fingerprint": context_fingerprint(account, credential),
            },
        )
        receipt.advertiser_identity = account.advertiser_identity
        receipt.credential_version = credential.credential_version
        receipt.context_fingerprint = context_fingerprint(account, credential)
        receipt.status = status
        receipt.granted_permissions = result["granted_permissions"]
        receipt.missing_permissions = result["missing_permissions"]
        receipt.checked_at = timezone.now()
        receipt.invalidated_at = None
        receipt.save()
    return result


def invalidate(account, credential=None):
    """Invalidate a former permission snapshot after an account/token change."""
    receipt = MetaPermissionReceipt.objects.filter(external_account=account).first()
    if receipt:
        receipt.status = MetaPermissionReceipt.STATUS_NOT_VERIFIED
        receipt.granted_permissions = []
        receipt.missing_permissions = list(REQUIRED_META_ADS_SCOPES)
        receipt.invalidated_at = timezone.now()
        receipt.checked_at = None
        if credential:
            receipt.credential_version = credential.credential_version
            receipt.context_fingerprint = context_fingerprint(account, credential)
        receipt.save(update_fields=["status", "granted_permissions", "missing_permissions", "invalidated_at", "checked_at", "credential_version", "context_fingerprint", "updated_at"])


def snapshot(identity, account_id):
    """Return current stored readiness only; this function never calls Meta."""
    account, error = _account(identity, account_id)
    if error:
        return _result([], status="not_verified", reconnect_required=False, blockers=[error])
    credential = getattr(account, "credential", None)
    if not credential or credential.revoked_at:
        return _result([], status="not_verified", reconnect_required=True, blockers=["meta_auth_failed"])
    receipt = MetaPermissionReceipt.objects.filter(external_account=account).first()
    if not receipt or receipt.invalidated_at or receipt.credential_version != credential.credential_version or receipt.context_fingerprint != context_fingerprint(account, credential):
        return _result([], status="not_verified", reconnect_required=False, blockers=["meta_permission_verification_required"])
    if not receipt.checked_at or receipt.checked_at + timedelta(seconds=_max_age()) <= timezone.now():
        return _result([], status="not_verified", reconnect_required=False, blockers=["meta_permission_verification_stale"])
    return _result(
        receipt.granted_permissions,
        checked_at=receipt.checked_at,
        status=receipt.status,
        reconnect_required=receipt.status == MetaPermissionReceipt.STATUS_RECONNECT_REQUIRED,
        blockers=[] if receipt.status == MetaPermissionReceipt.STATUS_READY else (["meta_ads_management_permission_required"] if receipt.status == MetaPermissionReceipt.STATUS_RECONNECT_REQUIRED else ["meta_permission_check_failed"]),
    )


def check(identity, account_id):
    """Perform the explicit GET-only permission check and retain safe scopes."""
    account, error = _account(identity, account_id)
    if error:
        return _result([], status="not_verified", reconnect_required=False, blockers=[error])
    credential = getattr(account, "credential", None)
    if not credential or credential.revoked_at:
        return _result([], status="not_verified", reconnect_required=True, blockers=["meta_auth_failed"])
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
            return _store(account, credential, _result([], status="reconnect_required", reconnect_required=True, blockers=[failure]))
        return _store(account, credential, _result([], status="unavailable", reconnect_required=False, blockers=[failure]))
    # AdvertisingCredential.scopes already owns safe OAuth scope names.  Do
    # not create a second snapshot model or persist the provider response.
    safe_scopes = normalize_granted_scopes(granted)
    if credential.scopes != safe_scopes:
        credential.scopes = safe_scopes
        credential.save(update_fields=["scopes", "updated_at"])
    return _store(account, credential, _result(safe_scopes))
