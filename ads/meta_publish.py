"""M14 controlled Meta publication planning.

This module creates only internal dry-run records.  It has no HTTP client and
the future live adapter is unreachable unless a server setting is explicitly
enabled.  No client request can alter that setting.
"""
from django.conf import settings
import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.db import IntegrityError, transaction
from django.utils import timezone

from .ad_resource_management import AdResourceError, status as ad_resource_status
from .creative_preparation import CreativePreparationError, canonical_meta_payload, payload_fingerprint
from .media_assets import sanitize_failure
from .meta_readiness import check as readiness_check
from .meta_permissions import snapshot as meta_permission_snapshot
from .meta_verification import context_fingerprint
from .meta_runtime import freshness_blockers
from .models import MetaPublicationAttempt, MetaVerificationReceipt
from .providers import ProviderAPIError, ProviderAuthorizationError, provider_for


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
    """Small explicit seam over the fixed-route Meta write adapter.

    It intentionally exposes no generic request method and no delivery
    enabling operation.  Tests patch these methods rather than HTTP.
    """

    def __init__(self):
        self._provider = provider_for("meta")
        self._writer = self._provider.LiveWriteAdapter(self._provider)

    def create_campaign(self, account, payload):
        return self._writer.create_campaign(account, payload)

    def create_adset(self, account, payload):
        return self._writer.create_adset(account, payload)

    def create_adcreative(self, account, payload):
        return self._writer.create_adcreative(account, payload)

    def create_ad(self, account, payload):
        return self._writer.create_ad(account, payload)


def _state_for_current_plan(identity, creative, account_id):
    """Read the M12/M13/M14 state without creating or refreshing anything."""
    if freshness_blockers():
        return None, None, freshness_blockers()
    readiness = readiness_check(identity, creative, account_id)
    if not readiness["ready"]:
        return None, None, list(readiness["blockers"])
    state = ad_resource_status(identity, creative, account_id)
    account = state.get("_account")
    if not account:
        return None, None, ["meta_account_required"]
    receipt, receipt_error = _receipt(creative, account)
    if receipt_error:
        return None, None, [receipt_error]
    if state.get("status") != "prepared":
        return None, None, ["ad_resource_stale"]
    _plan_value, fingerprint = _plan(creative, account, state)
    return state, fingerprint, []


def _current_attempt(identity, creative, account_id):
    state, fingerprint, blockers = _state_for_current_plan(identity, creative, account_id)
    if blockers:
        return None, None, blockers
    account = state["_account"]
    attempt = MetaPublicationAttempt.objects.filter(
        creative=creative, external_account=account, advertiser_identity=identity,
        plan_fingerprint=fingerprint,
    ).select_related("verification_receipt").first()
    if not attempt:
        return None, None, ["meta_publish_plan_required"]
    receipt = attempt.verification_receipt
    if receipt.expires_at <= timezone.now() or receipt.context_fingerprint != context_fingerprint(creative, account):
        return None, None, ["meta_live_verification_stale"]
    if attempt.status == MetaPublicationAttempt.STATUS_STALE:
        return None, None, ["meta_publish_plan_stale"]
    return attempt, state, []


def _campaign_payload(campaign, account):
    payload = provider_for("meta").build_external_payload(campaign, account)
    campaign_payload = payload.get("campaign") if isinstance(payload, dict) else None
    objective = str((campaign_payload or {}).get("objective") or "").strip()
    name = str((campaign_payload or {}).get("name") or "").strip()
    if not name or not objective:
        raise ProviderAPIError("meta_campaign_create_failed", stage="campaign_create")
    return {"name": name[:200], "objective": objective, "status": "PAUSED", "special_ad_categories": "[]"}


def _adset_payload(campaign, external_campaign_id):
    objective_settings = {
        campaign.OBJECTIVE_PRODUCT_VISITS: ("LINK_CLICKS", "WEBSITE"),
        campaign.OBJECTIVE_VIDEO_VIEWS: ("THRUPLAY", None),
        campaign.OBJECTIVE_BRAND_AWARENESS: ("REACH", None),
        campaign.OBJECTIVE_ENGAGEMENT: ("POST_ENGAGEMENT", None),
    }
    objective = objective_settings.get(campaign.objective)
    if not objective:
        raise ProviderAPIError("meta_adset_create_failed", stage="adset_create")
    countries = []
    for value in campaign.geo_targeting if isinstance(campaign.geo_targeting, list) else []:
        country = str(value or "").strip().upper()
        if len(country) == 2 and country.isalpha() and country not in countries:
            countries.append(country)
    if not countries:
        raise ProviderAPIError("meta_adset_create_failed", stage="adset_create")
    if campaign.budget_type == "daily":
        field, amount = "daily_budget", campaign.daily_budget
    elif campaign.budget_type in {"total", "lifetime"}:
        field, amount = "lifetime_budget", campaign.total_budget
    else:
        raise ProviderAPIError("meta_adset_create_failed", stage="adset_create")
    try:
        minor_units = int((Decimal(str(amount)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, TypeError, ValueError):
        minor_units = 0
    if minor_units <= 0 or (field == "lifetime_budget" and not campaign.end_date):
        raise ProviderAPIError("meta_adset_create_failed", stage="adset_create")
    payload = {
        "name": f"{str(campaign.name or '').strip()[:180]} Ad Set",
        "campaign_id": external_campaign_id,
        field: str(minor_units),
        "billing_event": "IMPRESSIONS",
        "optimization_goal": objective[0],
        "status": "PAUSED",
        "targeting": json.dumps({"geo_locations": {"countries": countries}, "publisher_platforms": ["facebook", "instagram"]}, separators=(",", ":")),
    }
    if objective[1]:
        payload["destination_type"] = objective[1]
    if campaign.start_date:
        payload["start_time"] = campaign.start_date.isoformat()
    if campaign.end_date:
        payload["end_time"] = campaign.end_date.isoformat()
    return payload


def _creative_payload(campaign, creative, account, media):
    canonical = canonical_meta_payload(
        campaign=campaign, creative=creative, external_account=account, media_asset=media,
    )
    return {"name": canonical["name"], "object_story_spec": json.dumps(canonical["object_story_spec"], separators=(",", ":"))}


def _ad_payload(campaign, external_adset_id, external_creative_id):
    if not external_adset_id or not external_creative_id:
        raise ProviderAPIError("meta_ad_create_failed", stage="ad_create")
    return {"name": str(campaign.name or "").strip()[:200], "adset_id": external_adset_id, "creative": json.dumps({"creative_id": external_creative_id}, separators=(",", ":")), "status": "PAUSED"}


def _save_attempt(attempt, *, stage=None, status=None, error=None, fields=(), actor=None):
    if stage is not None:
        attempt.stage = stage
    if status is not None:
        attempt.status = status
    if error is not None:
        attempt.failure_code, attempt.failure_message = sanitize_failure(error, "")
    attempt.last_attempted_at = timezone.now()
    update_fields = {"stage", "status", "failure_code", "failure_message", "last_attempted_at", "updated_at", *fields}
    attempt.save(update_fields=sorted(update_fields))
    if stage is not None:
        from .meta_live_controls import record_execution_event
        record_execution_event(
            attempt.advertiser_identity,
            attempt.creative,
            attempt,
            "execution_stage_changed",
            actor=actor,
            stage=stage,
            reason=attempt.failure_code if stage == MetaPublicationAttempt.STAGE_FAILED else "",
        )


def _provider_failure(exc, fallback):
    code = str(exc)
    if isinstance(exc, ProviderAuthorizationError):
        return "meta_permission_insufficient" if code in {"meta_auth_failed", "meta_authorization_failed"} else "meta_auth_failed"
    allowed = {"meta_rate_limited", "meta_provider_unavailable", "meta_invalid_request", "meta_response_invalid", "meta_live_writes_disabled"}
    return code if code in allowed else fallback


def execute(identity, creative, account_id, *, actor=None):
    # Deliberately first: a disabled setting entails zero provider or preflight work.
    if not live_writes_enabled():
        return None, ["meta_live_writes_disabled"]
    # M18 has no provider I/O: allowlist and Admin approval are persisted,
    # server-owned controls evaluated only after the emergency kill switch.
    from .meta_live_controls import execution_gate
    _authorized_attempt, controls = execution_gate(identity, creative, account_id, actor=actor)
    if controls:
        if _authorized_attempt:
            from .meta_live_controls import record_execution_event
            record_execution_event(identity, creative, _authorized_attempt, "execute_blocked", actor=actor, reason=controls[0])
        return None, controls
    attempt, state, blockers = _current_attempt(identity, creative, account_id)
    if blockers:
        return None, blockers
    # M17 requires a fresh M16 receipt after the kill switch.  Execute never
    # silently performs OAuth or a provider GET; Staff must explicitly check
    # permissions first.
    permissions = meta_permission_snapshot(identity, account_id)
    if not permissions["ready"]:
        return None, list(permissions.get("blockers") or ["meta_reconnect_required"])
    # Serialize same-plan execution.  The locked row also carries every
    # completed provider ID, so a retry always starts at the first missing
    # dependency rather than issuing a duplicate creation request.
    with transaction.atomic():
        attempt = MetaPublicationAttempt.objects.select_for_update().get(pk=attempt.pk)
        if attempt.status == MetaPublicationAttempt.STATUS_EXECUTING:
            return None, ["meta_execution_in_progress"]
        if attempt.status == MetaPublicationAttempt.STATUS_COMPLETED:
            return _live_publication(attempt), []
        # Recheck immediately before the first possible POST.  This does not
        # refresh a receipt or regenerate a plan; it only rejects a context
        # change that raced with the initial read.
        current_attempt, fresh_state, fresh_blockers = _current_attempt(identity, creative, account_id)
        if fresh_blockers:
            return None, fresh_blockers
        if current_attempt.pk != attempt.pk:
            return None, ["meta_publish_plan_stale"]
        from .meta_live_controls import record_execution_event
        attempt.status = MetaPublicationAttempt.STATUS_EXECUTING
        attempt.save(update_fields=["status", "updated_at"])
        record_execution_event(identity, creative, attempt, "execution_started", actor=actor, stage=attempt.stage)
    # The claim is committed before any provider call.
    result, result_blockers = _execute_attempt(attempt, fresh_state, creative, actor=actor)
    record_execution_event(identity, creative, attempt, "execution_completed" if not result_blockers else "execution_failed", actor=actor, stage=attempt.stage, reason=(result_blockers or [""])[0])
    return result, result_blockers


def _execute_attempt(attempt, state, creative, *, actor=None):
    if attempt.status == MetaPublicationAttempt.STATUS_COMPLETED:
        return _live_publication(attempt), []
    if attempt.status not in {MetaPublicationAttempt.STATUS_EXECUTING, MetaPublicationAttempt.STATUS_READY, MetaPublicationAttempt.STATUS_FAILED}:
        return None, ["meta_publish_plan_stale"]
    attempt.attempt_count += 1
    attempt.failure_code = attempt.failure_message = ""
    attempt.save(update_fields=["attempt_count", "failure_code", "failure_message", "updated_at"])
    adapter = MetaLivePublishAdapter()
    account = state["_account"]
    try:
        if not attempt.external_campaign_id:
            _save_attempt(attempt, stage=MetaPublicationAttempt.STAGE_CREATING_CAMPAIGN, actor=actor)
            attempt.external_campaign_id = adapter.create_campaign(account, _campaign_payload(creative.campaign, account))
            _save_attempt(attempt, stage=MetaPublicationAttempt.STAGE_CAMPAIGN_CREATED, fields={"external_campaign_id"}, actor=actor)
        if not attempt.external_adset_id:
            _save_attempt(attempt, stage=MetaPublicationAttempt.STAGE_CREATING_ADSET, actor=actor)
            attempt.external_adset_id = adapter.create_adset(account, _adset_payload(creative.campaign, attempt.external_campaign_id))
            _save_attempt(attempt, stage=MetaPublicationAttempt.STAGE_ADSET_CREATED, fields={"external_adset_id"}, actor=actor)
        if not attempt.external_creative_id:
            _save_attempt(attempt, stage=MetaPublicationAttempt.STAGE_CREATING_CREATIVE, actor=actor)
            attempt.external_creative_id = adapter.create_adcreative(account, _creative_payload(creative.campaign, creative, account, state["_media"]))
            _save_attempt(attempt, stage=MetaPublicationAttempt.STAGE_CREATIVE_CREATED, fields={"external_creative_id"}, actor=actor)
        if not attempt.external_ad_id:
            _save_attempt(attempt, stage=MetaPublicationAttempt.STAGE_CREATING_AD, actor=actor)
            attempt.external_ad_id = adapter.create_ad(account, _ad_payload(creative.campaign, attempt.external_adset_id, attempt.external_creative_id))
            _save_attempt(attempt, stage=MetaPublicationAttempt.STAGE_COMPLETED, status=MetaPublicationAttempt.STATUS_COMPLETED, fields={"external_ad_id"}, actor=actor)
    except (ProviderAPIError, ProviderAuthorizationError, CreativePreparationError, AdResourceError) as exc:
        fallback = {
            MetaPublicationAttempt.STAGE_CREATING_CAMPAIGN: "meta_campaign_create_failed",
            MetaPublicationAttempt.STAGE_CREATING_ADSET: "meta_adset_create_failed",
            MetaPublicationAttempt.STAGE_CREATING_CREATIVE: "meta_creative_create_failed",
            MetaPublicationAttempt.STAGE_CREATING_AD: "meta_ad_create_failed",
        }.get(attempt.stage, "meta_provider_unavailable")
        _save_attempt(attempt, stage=MetaPublicationAttempt.STAGE_FAILED, status=MetaPublicationAttempt.STATUS_FAILED, error=_provider_failure(exc, fallback), actor=actor)
        return None, [attempt.failure_code]
    return _live_publication(attempt), []


def _live_publication(attempt):
    return {
        "mode": attempt.mode,
        "status": attempt.status,
        "live": True,
        "initial_status": "PAUSED",
        "stages": {
            "campaign": "created" if attempt.external_campaign_id else "pending",
            "adset": "created" if attempt.external_adset_id else "pending",
            "creative": "created" if attempt.external_creative_id else "pending",
            "ad": "created" if attempt.external_ad_id else "pending",
        },
    }
