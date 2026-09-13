"""Persisted-state-only platform Admin view of Meta publication controls.

This module intentionally has no provider imports. It is an operational
projection over M12--M19 records: it never reconnects, verifies, refreshes a
permission receipt, regenerates a dry-run, or executes a publication.
"""
from django.utils import timezone

from .meta_live_controls import account_allowlisted
from .meta_permissions import snapshot as permission_snapshot
from .meta_publish import _state_for_current_plan, live_writes_enabled
from .meta_verification import context_fingerprint
from .models import (
    AdCreative, ExternalAdvertisingAccount, MetaPublicationAttempt,
    MetaPublicationAuthorization, MetaPublicationAuditEvent, MetaVerificationReceipt,
)


def context(creative_id, account_id):
    """Resolve a Meta context from server-side relations only."""
    try:
        creative = AdCreative.objects.select_related("campaign", "campaign__advertiser_identity").get(pk=creative_id)
        account = ExternalAdvertisingAccount.objects.get(
            pk=account_id, channel=ExternalAdvertisingAccount.CHANNEL_META,
            advertiser_identity=creative.campaign.advertiser_identity,
        )
    except (AdCreative.DoesNotExist, ExternalAdvertisingAccount.DoesNotExist, TypeError, ValueError):
        return None, "meta_publication_context_not_found"
    return (creative.campaign.advertiser_identity, creative, account), ""


def _verification_state(creative, account):
    receipt = MetaVerificationReceipt.objects.filter(creative=creative, external_account=account).order_by("-verified_at", "-pk").first()
    if not receipt:
        return "missing"
    if receipt.expires_at <= timezone.now() or receipt.context_fingerprint != context_fingerprint(creative, account):
        return "stale"
    return "fresh"


def _permission_state(identity, account):
    snapshot = permission_snapshot(identity, account.pk)
    blockers = list(snapshot.get("blockers") or [])
    if snapshot.get("ready"):
        state = "fresh"
    elif any(item.endswith("_stale") for item in blockers):
        state = "stale"
    else:
        state = "missing"
    return state, bool("ads_management" in (snapshot.get("granted_permissions") or []))


def _current_plan(identity, creative, account):
    candidate = MetaPublicationAttempt.objects.filter(
        creative=creative, external_account=account, advertiser_identity=identity,
    ).order_by("-updated_at", "-pk").first()
    if not candidate:
        return None, "missing", ["meta_publish_plan_required"]
    _state, fingerprint, blockers = _state_for_current_plan(identity, creative, account.pk)
    if blockers or candidate.status == MetaPublicationAttempt.STATUS_STALE or candidate.plan_fingerprint != fingerprint:
        return candidate, "stale", list(blockers or ["meta_publish_plan_stale"])
    return candidate, "current", []


def _authorization_state(attempt, identity, creative, account):
    if not attempt:
        return None, "missing"
    authorization = MetaPublicationAuthorization.objects.filter(publication_attempt=attempt).order_by("-authorized_at", "-pk").first()
    if not authorization:
        return None, "missing"
    if authorization.status == MetaPublicationAuthorization.STATUS_REVOKED or authorization.revoked_at:
        return authorization, "revoked"
    if authorization.expires_at <= timezone.now():
        return authorization, "expired"
    page_id = str((account.metadata or {}).get("meta_page_id") or "")
    if any((
        authorization.advertiser_identity_id != identity.pk,
        authorization.external_account_id != account.pk,
        authorization.campaign_id != creative.campaign_id,
        authorization.creative_id != creative.pk,
        authorization.plan_fingerprint != attempt.plan_fingerprint,
        authorization.page_id != page_id,
    )):
        return authorization, "stale"
    return authorization, "valid"


def overview(identity, creative, account):
    """Return a bounded operational projection without provider I/O."""
    verification = _verification_state(creative, account)
    permissions, ads_management = _permission_state(identity, account)
    attempt, plan, plan_blockers = _current_plan(identity, creative, account)
    authorization_record, authorization = _authorization_state(attempt, identity, creative, account)
    attempt_status, resumable = "not_started", False
    if attempt:
        if attempt.status == MetaPublicationAttempt.STATUS_EXECUTING:
            attempt_status = "executing"
        elif attempt.status == MetaPublicationAttempt.STATUS_FAILED:
            attempt_status, resumable = "failed", plan == "current"
        elif attempt.status == MetaPublicationAttempt.STATUS_COMPLETED:
            attempt_status = "completed"
        elif plan != "current":
            attempt_status = "blocked"
        elif authorization == "valid":
            attempt_status = "authorized"
        else:
            attempt_status = "blocked"
    blockers = list(plan_blockers)
    if verification != "fresh":
        blockers.append("meta_verification_" + verification)
    if permissions != "fresh":
        blockers.append("meta_permissions_" + permissions)
    if not ads_management:
        blockers.append("meta_ads_management_missing")
    if authorization != "valid" and attempt_status != "completed":
        blockers.append("meta_live_admin_authorization_" + authorization)
    if not account_allowlisted(account):
        blockers.append("meta_live_account_not_allowlisted")
    if not live_writes_enabled():
        blockers.append("meta_live_writes_disabled")
    blockers = list(dict.fromkeys(blockers))[:20]
    return {
        "advertiser": {"display_name": str(identity.display_name or "Advertiser")[:200]},
        "campaign": {"name": str(creative.campaign.name or "Campaign")[:200]},
        "creative": {"name": str(creative.name or "Creative")[:200]},
        "external_account": {"display_name": str(account.display_name or "Meta account")[:200]},
        "selected_page": {"display_name": str((account.metadata or {}).get("meta_page_name") or "Selected Facebook Page")[:200]} if (account.metadata or {}).get("meta_page_id") else None,
        "readiness": "ready" if plan == "current" and verification == "fresh" and permissions == "fresh" else "blocked",
        "verification": verification,
        "permissions": permissions,
        "ads_management": "present" if ads_management else "missing",
        "account_allowlisted": account_allowlisted(account),
        "live_writes_enabled": live_writes_enabled(),
        "plan": plan,
        "authorization": authorization,
        "admin_authorized": authorization == "valid",
        "authorization_expires_at": authorization_record.expires_at.isoformat() if authorization_record else None,
        "attempt": {"status": attempt_status, "stage": str(attempt.stage or "pending")[:40] if attempt else "pending"},
        "resumable": resumable,
        "delivery_mode": "PAUSED",
        "operational_status": "completed" if attempt_status == "completed" else "authorized" if attempt_status == "authorized" else "blocked",
        "blockers": blockers,
        "checked_at": timezone.now().isoformat(),
    }


def audit_history(*, campaign_id=None, creative_id=None, attempt_id=None, event_type=None, page=1, page_size=25):
    """Read bounded, safe audit rows; IDs and raw provider fields stay private."""
    query = MetaPublicationAuditEvent.objects.select_related("creative__campaign", "actor").order_by("-created_at", "-pk")
    if campaign_id:
        query = query.filter(creative__campaign_id=campaign_id)
    if creative_id:
        query = query.filter(creative_id=creative_id)
    if attempt_id:
        query = query.filter(publication_attempt_id=attempt_id)
    allowed_events = {value for value, _label in MetaPublicationAuditEvent.EVENT_CHOICES}
    if event_type in allowed_events:
        query = query.filter(event_type=event_type)
    page = max(1, min(int(page or 1), 10000))
    page_size = max(1, min(int(page_size or 25), 50))
    start = (page - 1) * page_size
    rows = list(query[start:start + page_size + 1])
    has_more, rows = len(rows) > page_size, rows[:page_size]
    return {
        "events": [{
            "event_type": event.event_type,
            "status": "failed" if event.event_type == MetaPublicationAuditEvent.EVENT_FAILED else "completed" if event.event_type == MetaPublicationAuditEvent.EVENT_COMPLETED else "recorded",
            "stage": str(event.stage or "")[:40], "reason_code": str(event.reason_code or "")[:80],
            "actor": str(event.actor.get_username() if event.actor else "System")[:200],
            "campaign": {"name": str(event.creative.campaign.name or "Campaign")[:200]},
            "creative": {"name": str(event.creative.name or "Creative")[:200]},
            "created_at": event.created_at.isoformat(),
        } for event in rows],
        "page": page, "page_size": page_size, "has_more": has_more,
    }
