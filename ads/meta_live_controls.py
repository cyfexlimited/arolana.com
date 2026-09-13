"""M18 server-only controls for future Meta writes; no provider I/O lives here."""
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .meta_permissions import snapshot as permission_snapshot
from .meta_publish import _current_attempt, live_writes_enabled
from .models import MetaPublicationAuthorization, MetaPublicationAuditEvent


def _account_key(value):
    value = str(value or "").strip().lower().replace(" ", "")
    if value.startswith("act_"):
        value = value[4:]
    return value if value.isdigit() else ""


def account_allowlisted(account):
    raw = getattr(settings, "META_ADS_LIVE_WRITE_ACCOUNT_ALLOWLIST", []) or []
    raw = raw.split(",") if isinstance(raw, str) else raw
    allowed = {_account_key(item) for item in raw}
    return bool(_account_key(account.external_account_id) and _account_key(account.external_account_id) in allowed)


def _audit(identity, creative, attempt, event, *, actor=None, stage="", reason=""):
    return MetaPublicationAuditEvent.objects.create(
        advertiser_identity=identity, creative=creative, publication_attempt=attempt,
        actor=actor, event_type=event, stage=str(stage or "")[:40], reason_code=str(reason or "")[:80],
    )


def record_execution_event(identity, creative, attempt, event, *, actor=None, stage="", reason=""):
    return _audit(identity, creative, attempt, event, actor=actor, stage=stage, reason=reason)


def _authorization(attempt):
    return MetaPublicationAuthorization.objects.filter(publication_attempt=attempt).order_by("-authorized_at", "-pk").first()


def authorization_state(identity, creative, account_id):
    attempt, state, blockers = _current_attempt(identity, creative, account_id)
    if blockers:
        return None, blockers
    account = state["_account"]
    auth = _authorization(attempt)
    if not auth:
        return attempt, ["meta_live_admin_authorization_required"]
    if auth.status == MetaPublicationAuthorization.STATUS_REVOKED or auth.revoked_at:
        return attempt, ["meta_live_admin_authorization_revoked"]
    if auth.expires_at <= timezone.now():
        return attempt, ["meta_live_admin_authorization_expired"]
    page_id = str((account.metadata or {}).get("meta_page_id") or "")
    if any((auth.advertiser_identity_id != identity.pk, auth.external_account_id != account.pk,
            auth.campaign_id != creative.campaign_id, auth.creative_id != creative.pk,
            auth.plan_fingerprint != attempt.plan_fingerprint, auth.page_id != page_id)):
        return attempt, ["meta_live_admin_authorization_stale"]
    return attempt, []


def authorize(identity, creative, account_id, actor):
    if not getattr(actor, "is_staff", False):
        return None, ["staff_required"]
    attempt, state, blockers = _current_attempt(identity, creative, account_id)
    if blockers:
        return None, blockers
    permissions = permission_snapshot(identity, account_id)
    if not permissions["ready"]:
        return None, list(permissions.get("blockers") or ["meta_permission_receipt_required"])
    account = state["_account"]
    page_id = str((account.metadata or {}).get("meta_page_id") or "")
    if not page_id:
        return None, ["meta_page_required"]
    with transaction.atomic():
        MetaPublicationAuthorization.objects.filter(publication_attempt=attempt, status=MetaPublicationAuthorization.STATUS_AUTHORIZED).update(status=MetaPublicationAuthorization.STATUS_REVOKED, revoked_at=timezone.now())
        auth = MetaPublicationAuthorization.objects.create(
            advertiser_identity=identity, external_account=account, campaign=creative.campaign,
            creative=creative, publication_attempt=attempt, authorized_by=actor,
            plan_fingerprint=attempt.plan_fingerprint, page_id=page_id,
            expires_at=timezone.now() + timedelta(seconds=max(60, min(int(getattr(settings, "META_ADS_LIVE_AUTHORIZATION_MAX_AGE_SECONDS", 900)), 3600))),
        )
        _audit(identity, creative, attempt, MetaPublicationAuditEvent.EVENT_AUTHORIZED, actor=actor)
    return auth, []


def revoke(identity, creative, account_id, actor):
    if not getattr(actor, "is_staff", False):
        return None, ["staff_required"]
    attempt, blockers = authorization_state(identity, creative, account_id)
    if not attempt:
        return None, blockers
    auth = _authorization(attempt)
    if not auth:
        return None, ["meta_live_admin_authorization_required"]
    auth.status = MetaPublicationAuthorization.STATUS_REVOKED; auth.revoked_at = timezone.now()
    auth.save(update_fields=["status", "revoked_at", "updated_at"])
    _audit(identity, creative, attempt, MetaPublicationAuditEvent.EVENT_REVOKED, actor=actor)
    return auth, []


def preflight(identity, creative, account_id):
    attempt, state, plan_blockers = _current_attempt(identity, creative, account_id)
    account = state.get("_account") if state else None
    blockers = []
    if not live_writes_enabled(): blockers.append("meta_live_writes_disabled")
    if account and not account_allowlisted(account): blockers.append("meta_live_account_not_allowlisted")
    if plan_blockers: blockers.extend(plan_blockers)
    # Even if a changed Page has already made M12/M13 stale, surface the
    # independent Admin authorization invalidation without regenerating work.
    if plan_blockers:
        from .models import MetaPublicationAttempt
        candidate = MetaPublicationAttempt.objects.filter(creative=creative, advertiser_identity=identity).order_by("-updated_at", "-pk").first()
        if candidate:
            auth = _authorization(candidate)
            account_for_context = identity.external_accounts.filter(pk=account_id).first()
            if auth and account_for_context and auth.page_id != str((account_for_context.metadata or {}).get("meta_page_id") or ""):
                blockers.append("meta_live_admin_authorization_stale")
    permissions = permission_snapshot(identity, account_id)
    if not permissions["ready"]: blockers.extend(permissions.get("blockers") or ["meta_permission_receipt_required"])
    auth_attempt, auth_blockers = authorization_state(identity, creative, account_id)
    blockers.extend(auth_blockers)
    return {
        "ready": not blockers, "status": "ready" if not blockers else "blocked",
        "live_writes_enabled": live_writes_enabled(), "account_allowlisted": bool(account and account_allowlisted(account)),
        "admin_authorized": not auth_blockers, "permission_ready": permissions["ready"],
        "verification_ready": not any(item.startswith("meta_live_verification") for item in plan_blockers),
        "plan_current": not plan_blockers, "initial_status": "PAUSED", "blockers": list(dict.fromkeys(blockers)),
    }


def execution_gate(identity, creative, account_id, *, actor=None):
    # Called only after M15's absolute kill switch.
    attempt, state, blockers = _current_attempt(identity, creative, account_id)
    if blockers:
        return None, blockers
    if not account_allowlisted(state["_account"]):
        return attempt, ["meta_live_account_not_allowlisted"]
    permissions = permission_snapshot(identity, account_id)
    if not permissions["ready"]:
        return attempt, list(permissions.get("blockers") or ["meta_permission_receipt_required"])
    authorized_attempt, auth_blockers = authorization_state(identity, creative, account_id)
    return authorized_attempt, auth_blockers
