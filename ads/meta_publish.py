"""M14 controlled Meta publication planning.

This module creates only internal dry-run records.  It has no HTTP client and
the future live adapter is unreachable unless a server setting is explicitly
enabled.  No client request can alter that setting.
"""
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from .ad_resource_management import status as ad_resource_status
from .creative_preparation import payload_fingerprint
from .meta_readiness import check as readiness_check
from .meta_verification import context_fingerprint
from .models import MetaPublicationAttempt, MetaVerificationReceipt


class MetaPublishError(Exception):
    pass


def live_writes_enabled():
    """Only an explicit server boolean enables the future branch."""
    return getattr(settings, "META_ADS_LIVE_WRITES_ENABLED", False) is True


def _receipt(creative, account):
    fingerprint = context_fingerprint(creative, account)
    now = timezone.now()
    receipt = MetaVerificationReceipt.objects.filter(
        creative=creative, external_account=account, context_fingerprint=fingerprint,
    ).order_by("-verified_at", "-pk").first()
    if receipt and receipt.expires_at > now:
        return receipt, ""
    any_receipt = MetaVerificationReceipt.objects.filter(creative=creative, external_account=account).exists()
    return None, "meta_live_verification_stale" if any_receipt else "meta_live_verification_required"


def _plan(creative, account, resource_state):
    execution = resource_state["_execution"]
    preparation = resource_state["_preparation"]
    resource = resource_state["_resource"]
    # Fingerprints are opaque internal references.  This deliberately omits
    # provider IDs, image hashes, page IDs, and raw provider payloads.
    value = {
        "provider": "meta",
        "campaign": creative.campaign_id,
        "creative": creative.pk,
        "account": account.pk,
        "verification_context": context_fingerprint(creative, account),
        "execution": execution.pk,
        "creative_preparation": preparation.payload_fingerprint,
        "ad_resource": resource.payload_fingerprint,
        "ad": {"status": "PAUSED"},
    }
    return value, payload_fingerprint(value)


def _safe_publication(attempt):
    return {
        "mode": attempt.mode,
        "status": attempt.status,
        "can_live_publish": False,
        "live_writes_enabled": live_writes_enabled(),
        "blockers": [],
        "checked_at": attempt.last_attempted_at.isoformat() if attempt.last_attempted_at else attempt.updated_at.isoformat(),
        "plan_summary": {"campaign": True, "adset": True, "creative": True, "ad": True, "initial_status": "PAUSED"},
    }


def dry_run(identity, creative, account_id):
    readiness = readiness_check(identity, creative, account_id)
    if not readiness["ready"]:
        return None, list(readiness["blockers"])
    state = ad_resource_status(identity, creative, account_id)
    account = state.get("_account")
    if not account:
        return None, ["meta_account_required"]
    receipt, receipt_error = _receipt(creative, account)
    if receipt_error:
        return None, [receipt_error]
    plan, fingerprint = _plan(creative, account, state)
    try:
        with transaction.atomic():
            # A new current context (including a different Meta account) makes
            # every previous plan for this creative historical.  We retain it
            # for audit instead of overwriting or deleting it.
            MetaPublicationAttempt.objects.filter(
                creative=creative, status=MetaPublicationAttempt.STATUS_READY,
            ).exclude(plan_fingerprint=fingerprint).update(status=MetaPublicationAttempt.STATUS_STALE)
            attempt, created = MetaPublicationAttempt.objects.get_or_create(
                creative=creative, external_account=account, plan_fingerprint=fingerprint,
                defaults={
                    "campaign": creative.campaign,
                    "advertiser_identity": identity,
                    "execution": state["_execution"],
                    "creative_preparation": state["_preparation"],
                    "ad_resource": state["_resource"],
                    "verification_receipt": receipt,
                    "mode": MetaPublicationAttempt.MODE_DRY_RUN,
                    "status": MetaPublicationAttempt.STATUS_READY,
                    "attempt_count": 1,
                    "last_attempted_at": timezone.now(),
                },
            )
    except IntegrityError:
        attempt = MetaPublicationAttempt.objects.get(creative=creative, external_account=account, plan_fingerprint=fingerprint)
        created = False
    if not created and attempt.status != MetaPublicationAttempt.STATUS_READY:
        attempt.status = MetaPublicationAttempt.STATUS_READY
        attempt.save(update_fields=["status", "updated_at"])
    return _safe_publication(attempt), []


class MetaLivePublishAdapter:
    """Future write seam.  M14 intentionally supplies no provider implementation."""
    def execute(self, *_args, **_kwargs):
        raise MetaPublishError("meta_live_execution_not_implemented")


def execute(identity, creative, account_id):
    # Deliberately first: a disabled setting entails zero provider or preflight work.
    if not live_writes_enabled():
        return None, ["meta_live_writes_disabled"]
    publication, blockers = dry_run(identity, creative, account_id)
    if blockers:
        return None, blockers
    # No adapter is invoked in M14; there is no live provider implementation.
    return None, ["meta_live_execution_not_implemented"]
