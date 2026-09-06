import hashlib
import logging
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import (
    AdvertisingConnectionAuditLog,
    AdCampaign,
    AdChannelExecution,
    AdChannelReportingSnapshot,
    AdCreative,
    ExternalAdvertisingAccount,
)
from .ownership import ownership_resolver
from .providers import ProviderAPIError, ProviderAuthorizationError, audit_connection, provider_for


logger = logging.getLogger(__name__)


CHANNELS = ("internal", "meta", "google", "tiktok", "linkedin")

OBJECTIVE_MAPPING = {
    "meta": {
        AdCampaign.OBJECTIVE_SALES: "OUTCOME_SALES",
        AdCampaign.OBJECTIVE_PRODUCT_VISITS: "OUTCOME_TRAFFIC",
        AdCampaign.OBJECTIVE_VIDEO_VIEWS: "OUTCOME_ENGAGEMENT",
        AdCampaign.OBJECTIVE_LEADS: "OUTCOME_LEADS",
        AdCampaign.OBJECTIVE_QUOTE_REQUESTS: "OUTCOME_LEADS",
        AdCampaign.OBJECTIVE_MESSAGES: "OUTCOME_ENGAGEMENT",
        AdCampaign.OBJECTIVE_STORE_VISITS: None,
        AdCampaign.OBJECTIVE_BRAND_AWARENESS: "OUTCOME_AWARENESS",
        AdCampaign.OBJECTIVE_ENGAGEMENT: "OUTCOME_ENGAGEMENT",
    },
    "google": {
        AdCampaign.OBJECTIVE_SALES: "SALES",
        AdCampaign.OBJECTIVE_PRODUCT_VISITS: "WEBSITE_TRAFFIC",
        AdCampaign.OBJECTIVE_VIDEO_VIEWS: "DEMAND_GEN_VIDEO_VIEWS",
        AdCampaign.OBJECTIVE_LEADS: "LEADS",
        AdCampaign.OBJECTIVE_QUOTE_REQUESTS: "LEADS",
        AdCampaign.OBJECTIVE_MESSAGES: None,
        AdCampaign.OBJECTIVE_STORE_VISITS: "LOCAL_STORE_VISITS",
        AdCampaign.OBJECTIVE_BRAND_AWARENESS: "AWARENESS_AND_CONSIDERATION",
        AdCampaign.OBJECTIVE_ENGAGEMENT: "DEMAND_GEN_ENGAGEMENT",
    },
    "tiktok": {
        AdCampaign.OBJECTIVE_SALES: "PRODUCT_SALES",
        AdCampaign.OBJECTIVE_PRODUCT_VISITS: "TRAFFIC",
        AdCampaign.OBJECTIVE_VIDEO_VIEWS: "VIDEO_VIEWS",
        AdCampaign.OBJECTIVE_LEADS: "LEAD_GENERATION",
        AdCampaign.OBJECTIVE_QUOTE_REQUESTS: "LEAD_GENERATION",
        AdCampaign.OBJECTIVE_MESSAGES: "MESSAGES",
        AdCampaign.OBJECTIVE_STORE_VISITS: None,
        AdCampaign.OBJECTIVE_BRAND_AWARENESS: "REACH",
        AdCampaign.OBJECTIVE_ENGAGEMENT: "ENGAGEMENT",
    },
    "linkedin": {
        AdCampaign.OBJECTIVE_SALES: "WEBSITE_CONVERSIONS",
        AdCampaign.OBJECTIVE_PRODUCT_VISITS: "WEBSITE_VISITS",
        AdCampaign.OBJECTIVE_VIDEO_VIEWS: "VIDEO_VIEWS",
        AdCampaign.OBJECTIVE_LEADS: "LEAD_GENERATION",
        AdCampaign.OBJECTIVE_QUOTE_REQUESTS: "LEAD_GENERATION",
        AdCampaign.OBJECTIVE_MESSAGES: None,
        AdCampaign.OBJECTIVE_STORE_VISITS: None,
        AdCampaign.OBJECTIVE_BRAND_AWARENESS: "BRAND_AWARENESS",
        AdCampaign.OBJECTIVE_ENGAGEMENT: "ENGAGEMENT",
    },
}

CREATIVE_LIMITS = {
    "meta": {"headline": 255, "description": 500, "types": {"image", "video", "carousel", "native"}},
    "google": {"headline": 90, "description": 180, "types": {"image", "video", "carousel"}},
    "tiktok": {"headline": 100, "description": 500, "types": {"video", "image"}},
    "linkedin": {"headline": 200, "description": 600, "types": {"image", "video", "carousel", "native"}},
}


@dataclass
class ExecutionValidationResult:
    valid: bool
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    objective: str = ""
    payload: dict = field(default_factory=dict)


class ExternalCampaignExecutionService:
    def provider_channels(self):
        return ("meta", "google", "tiktok", "linkedin")

    def idempotency_key(self, campaign, channel, external_account):
        material = f"{campaign.pk}:{channel}:{external_account.pk if external_account else 'none'}"
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:64]

    def objective_for(self, campaign, channel):
        objective = campaign.objective or AdCampaign.OBJECTIVE_PRODUCT_VISITS
        return OBJECTIVE_MAPPING.get(channel, {}).get(objective)

    def validate_campaign(self, campaign, channel, external_account=None, *, require_publish_ready=False):
        errors = []
        warnings = []
        if channel not in self.provider_channels():
            errors.append("unsupported_channel")
        elif require_publish_ready:
            try:
                adapter = provider_for(channel)
                if not adapter.configured():
                    errors.append("provider_not_configured")
            except Exception:
                errors.append("provider_not_configured")
        mapped_objective = self.objective_for(campaign, channel)
        if not mapped_objective:
            errors.append("unsupported_objective")
        if campaign.advertiser_identity_id is None:
            errors.append("missing_advertiser_identity")
        if require_publish_ready and not campaign.approved:
            errors.append("campaign_not_approved")
        if campaign.end_date and campaign.end_date <= campaign.start_date:
            errors.append("invalid_schedule")
        if campaign.start_date and campaign.end_date and campaign.end_date <= timezone.now():
            errors.append("campaign_ended")

        budget = self._campaign_budget(campaign, channel)
        if budget is None or budget <= 0:
            errors.append("invalid_budget")
        if not campaign.assets.exists():
            errors.append("missing_campaign_asset")
        for asset in campaign.assets.all():
            try:
                asset.full_clean()
            except ValidationError:
                errors.append("invalid_asset_ownership")
                break
            resolution = ownership_resolver.resolve_asset_owner(asset)
            if not resolution.is_resolved:
                errors.append("asset_owner_unresolved")
                break

        creatives = list(campaign.creatives.filter(is_active=True))
        if not creatives:
            errors.append("missing_creative")
        for creative in creatives:
            errors.extend(self._creative_errors(channel, creative))
        if not any((creative.clickthrough_url or "").strip() for creative in creatives):
            errors.append("missing_destination_url")

        if external_account:
            if external_account.advertiser_identity_id != campaign.advertiser_identity_id:
                errors.append("external_account_advertiser_mismatch")
            status = provider_for(channel).get_connection_status(external_account)
            if status == ExternalAdvertisingAccount.STATUS_EXPIRED:
                errors.append("credential_expired")
            elif status == ExternalAdvertisingAccount.STATUS_REAUTHORIZATION_REQUIRED:
                errors.append("reauthorization_required")
            elif status == ExternalAdvertisingAccount.STATUS_REVOKED:
                errors.append("account_revoked")
            elif status != ExternalAdvertisingAccount.STATUS_CONNECTED:
                errors.append("account_disconnected")
        elif require_publish_ready:
            errors.append("missing_external_account")

        return ExecutionValidationResult(
            valid=not errors,
            errors=sorted(set(errors)),
            warnings=warnings,
            objective=mapped_objective or "",
            payload=self.build_external_payload(campaign, channel, external_account),
        )

    def build_external_payload(self, campaign, channel, external_account=None):
        mapped_objective = self.objective_for(campaign, channel)
        budget = self._campaign_budget(campaign, channel)
        creatives = [self.transform_creative(channel, creative) for creative in campaign.creatives.filter(is_active=True)]
        base = {
            "provider": channel,
            "campaign": {
                "name": campaign.name,
                "arolana_campaign_id": campaign.campaign_id,
                "objective": mapped_objective,
                "status": "PAUSED",
                "start_time": campaign.start_date.isoformat() if campaign.start_date else None,
                "end_time": campaign.end_date.isoformat() if campaign.end_date else None,
            },
            "budget": {
                "amount": str(budget) if budget is not None else None,
                "mode": campaign.budget_type,
                "currency": external_account.metadata.get("currency", "NGN") if external_account else "NGN",
            },
            "account": {
                "external_account_id": external_account.external_account_id if external_account else "",
                "display_name": external_account.display_name if external_account else "",
            },
            "creatives": creatives,
        }
        if channel == "google":
            base["campaign"]["campaign_type"] = "DEMAND_GEN"
            base["campaign"]["networks"] = ["YOUTUBE", "DISCOVER", "GMAIL"]
        elif channel == "meta":
            base["campaign"]["surfaces"] = ["facebook", "instagram"]
        elif channel == "tiktok":
            base["ad_group"] = {"promotion_type": "WEBSITE", "placement_type": "PLACEMENT_TYPE_AUTOMATIC"}
        elif channel == "linkedin":
            base["campaign_group"] = {"required": True}
        return base

    def transform_creative(self, channel, creative):
        return {
            "name": creative.name,
            "type": creative.creative_type,
            "headline": creative.headline,
            "description": creative.description,
            "cta_text": creative.cta_text,
            "destination_url": creative.clickthrough_url,
            "has_image": bool(creative.image),
            "has_mobile_image": bool(creative.image_mobile),
            "has_video": bool(creative.video_url),
        }

    def preview(self, campaign, channel, external_account=None):
        return self.validate_campaign(campaign, channel, external_account)

    @transaction.atomic
    def create_execution(self, campaign, channel, external_account, *, dry_run=False, user=None):
        result = self.validate_campaign(campaign, channel, external_account, require_publish_ready=not dry_run)
        key = self.idempotency_key(campaign, channel, external_account)
        execution, _created = AdChannelExecution.objects.get_or_create(
            campaign=campaign,
            channel=channel,
            defaults={
                "advertiser_identity": campaign.advertiser_identity,
                "external_account": external_account,
                "status": AdChannelExecution.STATUS_DRAFT if dry_run else AdChannelExecution.STATUS_PENDING,
                "idempotency_key": key,
                "budget_allocation": self._campaign_budget(campaign, channel),
                "currency": external_account.metadata.get("currency", "NGN") if external_account else "NGN",
                "metadata": {"last_preview": result.payload, "warnings": result.warnings, "errors": result.errors},
            },
        )
        if not _created and execution.external_campaign_id:
            return execution, result
        execution.idempotency_key = execution.idempotency_key or key
        execution.external_account = external_account
        execution.budget_allocation = self._campaign_budget(campaign, channel)
        execution.currency = external_account.metadata.get("currency", "NGN") if external_account else "NGN"
        execution.metadata = {**execution.metadata, "last_preview": result.payload, "warnings": result.warnings, "errors": result.errors}
        if dry_run:
            execution.status = AdChannelExecution.STATUS_DRAFT
            execution.save()
            return execution, result
        if not getattr(settings, "ADS_EXTERNAL_CAMPAIGN_PUBLISHING_ENABLED", False):
            execution.status = AdChannelExecution.STATUS_DRAFT
            execution.last_error = "external_campaign_publishing_disabled"
            execution.save()
            return execution, ExecutionValidationResult(False, ["external_campaign_publishing_disabled"], result.warnings, result.objective, result.payload)
        if not getattr(settings, "ADS_EXTERNAL_CHANNEL_SYNC_ENABLED", False):
            execution.status = AdChannelExecution.STATUS_DRAFT
            execution.last_error = "external_channel_sync_disabled"
            execution.save()
            return execution, ExecutionValidationResult(False, ["external_channel_sync_disabled"], result.warnings, result.objective, result.payload)
        if not result.valid:
            execution.status = AdChannelExecution.STATUS_FAILED
            execution.last_error = ",".join(result.errors)
            execution.save()
            return execution, result
        audit_connection(
            channel,
            AdvertisingConnectionAuditLog.EVENT_TEST_PUBLICATION_REQUESTED,
            user=user,
            advertiser_identity=campaign.advertiser_identity,
            external_account=external_account,
            status="requested",
            metadata={"campaign_id": campaign.pk, "idempotency_key": key},
        )
        safety_errors = self.live_mutation_safety_errors(campaign, channel, external_account, user=user)
        if safety_errors:
            execution.status = AdChannelExecution.STATUS_DRAFT
            execution.last_error = ",".join(safety_errors)
            execution.save()
            return execution, ExecutionValidationResult(False, safety_errors, result.warnings, result.objective, result.payload)
        try:
            audit_connection(
                channel,
                AdvertisingConnectionAuditLog.EVENT_TEST_PUBLICATION_APPROVED,
                user=user,
                advertiser_identity=campaign.advertiser_identity,
                external_account=external_account,
                status="approved",
                metadata={"campaign_id": campaign.pk, "idempotency_key": key},
            )
            audit_connection(
                channel,
                AdvertisingConnectionAuditLog.EVENT_EXTERNAL_CREATE_ATTEMPTED,
                user=user,
                advertiser_identity=campaign.advertiser_identity,
                external_account=external_account,
                status="attempted",
                metadata={"campaign_id": campaign.pk, "idempotency_key": key},
            )
            provider_result = provider_for(channel).create_campaign(execution, result.payload, idempotency_key=key)
        except (ProviderAPIError, ProviderAuthorizationError, NotImplementedError) as exc:
            diagnostic = {
                "stage": str(getattr(exc, "stage", "") or "other")[:80],
                "http_status": getattr(exc, "http_status", None),
                "failure_reason": str(exc)[:120],
            }
            safe_details = getattr(exc, "safe_details", {}) or {}
            for key in (
                "google_ads_request_id",
                "google_error_status",
                "google_ads_error_code",
                "google_field_path",
                "google_message",
            ):
                if safe_details.get(key):
                    diagnostic[key] = str(safe_details[key])[:500]
            logger.warning(
                "External Google campaign create failed stage=%s http_status=%s "
                "google_ads_request_id=%s google_error_status=%s "
                "google_ads_error_code=%s google_field_path=%s google_message=%s "
                "failure_reason=%s",
                diagnostic["stage"],
                diagnostic.get("http_status") or "none",
                diagnostic.get("google_ads_request_id") or "none",
                diagnostic.get("google_error_status") or "none",
                diagnostic.get("google_ads_error_code") or "none",
                diagnostic.get("google_field_path") or "none",
                diagnostic.get("google_message") or "none",
                diagnostic["failure_reason"],
            )
            execution.status = AdChannelExecution.STATUS_FAILED
            execution.last_error = str(exc)
            execution.save()
            audit_connection(
                channel,
                AdvertisingConnectionAuditLog.EVENT_EXTERNAL_CREATE_FAILED,
                user=user,
                advertiser_identity=campaign.advertiser_identity,
                external_account=external_account,
                status="failed",
                message=str(exc),
                metadata=diagnostic,
            )
            return execution, ExecutionValidationResult(False, [str(exc)], result.warnings, result.objective, result.payload)
        execution.external_campaign_id = str(provider_result.get("external_campaign_id", ""))
        execution.external_ad_group_id = str(provider_result.get("external_ad_group_id", ""))
        execution.external_status = str(provider_result.get("external_status", ""))
        execution.status = AdChannelExecution.STATUS_PAUSED if execution.external_status == "PAUSED" else AdChannelExecution.STATUS_ACTIVE
        execution.last_synced_at = timezone.now()
        execution.metadata = {**execution.metadata, "provider_result": self.safe_metadata(provider_result)}
        execution.save()
        audit_connection(
            channel,
            AdvertisingConnectionAuditLog.EVENT_EXTERNAL_CREATE_SUCCEEDED,
            user=user,
            advertiser_identity=campaign.advertiser_identity,
            external_account=external_account,
            status=execution.status,
            metadata={"external_campaign_id": execution.external_campaign_id},
        )
        return execution, result

    def live_mutation_safety_errors(self, campaign, channel, external_account, *, user=None):
        errors = []

        if not user or not getattr(user, "is_authenticated", False) or not getattr(user, "is_staff", False):
            errors.append("staff_required")

        if channel not in {"google", "meta"}:
            errors.append("provider_write_not_enabled")

        if not getattr(settings, "ADS_EXTERNAL_CAMPAIGN_TEST_MODE_ENABLED", False):
            errors.append("external_campaign_test_mode_disabled")

        if not external_account:
            errors.append("missing_external_account")
            return sorted(set(errors))

        external_id = str(external_account.external_account_id)

        if channel == "google":
            allowlist = set(getattr(settings, "ADS_GOOGLE_TEST_ACCOUNT_ALLOWLIST", []) or [])
            if external_id not in allowlist:
                errors.append("external_account_not_allowlisted")

        elif channel == "meta":
            if not getattr(settings, "ADS_META_ALLOW_TEST_WRITES", False):
                errors.append("meta_test_writes_disabled")

            allowlist = set(getattr(settings, "ADS_META_TEST_ACCOUNT_ALLOWLIST", []) or [])
            if external_id not in allowlist:
                errors.append("external_account_not_allowlisted")

        return sorted(set(errors))

    def sync_status(self, execution):
        if execution.channel == AdChannelExecution.CHANNEL_INTERNAL:
            execution.last_synced_at = timezone.now()
            execution.save(update_fields=["last_synced_at", "updated_at"])
            return execution
        if not execution.external_account_id:
            execution.status = AdChannelExecution.STATUS_DISCONNECTED
            execution.last_error = "missing_external_account"
            execution.save()
            return execution
        try:
            status = provider_for(execution.channel).sync_status(execution)
        except (ProviderAPIError, ProviderAuthorizationError, NotImplementedError) as exc:
            execution.status = AdChannelExecution.STATUS_FAILED
            execution.last_error = str(exc)
            execution.save()
            return execution
        execution.external_status = str(status.get("external_status", ""))
        execution.status = status.get("status", execution.status)
        execution.last_synced_at = timezone.now()
        execution.metadata = {**execution.metadata, "last_status": self.safe_metadata(status)}
        execution.save()
        return execution

    def normalize_reporting(self, execution, provider_payload, reporting_start, reporting_end):
        metrics = provider_payload.get("metrics", provider_payload)
        snapshot, _created = AdChannelReportingSnapshot.objects.update_or_create(
            execution=execution,
            reporting_start=reporting_start,
            reporting_end=reporting_end,
            defaults={
                "provider": execution.channel,
                "impressions": int(metrics.get("impressions") or 0),
                "clicks": int(metrics.get("clicks") or 0),
                "spend": self._decimal_or_none(metrics.get("spend")),
                "video_views": int(metrics.get("video_views") or metrics.get("videoViews") or 0),
                "provider_conversions": int(metrics.get("conversions") or 0),
                "currency": metrics.get("currency") or execution.currency,
                "metadata": self.safe_metadata(provider_payload.get("metadata", {})),
            },
        )
        return snapshot

    def safe_metadata(self, value):
        safe = {}
        for key, item in (value or {}).items():
            lowered = str(key).lower()
            if any(secret in lowered for secret in ("token", "secret", "authorization", "code")):
                continue
            if isinstance(item, (str, int, float, bool)) or item is None:
                safe[str(key)[:80]] = str(item)[:500] if isinstance(item, str) else item
        return safe

    def _creative_errors(self, channel, creative):
        limits = CREATIVE_LIMITS.get(channel, {})
        errors = []
        if creative.creative_type not in limits.get("types", set()):
            errors.append("unsupported_creative_type")
        if len(creative.headline or "") > limits.get("headline", 9999):
            errors.append("headline_too_long")
        if len(creative.description or "") > limits.get("description", 9999):
            errors.append("description_too_long")
        if channel == "tiktok" and creative.creative_type == "video" and not creative.video_url:
            errors.append("missing_video_creative")
        return errors

    def _campaign_budget(self, campaign, channel):
        allocation = (getattr(campaign, "channel_budget_allocations", {}) or {}).get(channel)
        try:
            return Decimal(str(allocation if allocation is not None else campaign.total_budget))
        except (InvalidOperation, TypeError):
            return None

    def _decimal_or_none(self, value):
        if value in (None, ""):
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError):
            return None

    def execution_cards(self, campaign):
        by_channel = {execution.channel: execution for execution in campaign.channel_executions.all()}
        cards = []
        for channel in CHANNELS:
            execution = by_channel.get(channel)
            if channel == "internal":
                cards.append({
                    "channel": "internal",
                    "label": "Arolana",
                    "connection_status": "internal",
                    "execution_status": execution.status if execution else campaign.status,
                    "external_campaign_id": "",
                    "budget_allocation": campaign.total_budget,
                    "currency": "NGN",
                    "spend": campaign.spent,
                    "impressions": campaign.impressions,
                    "clicks": campaign.clicks,
                    "last_sync": execution.last_synced_at if execution else None,
                    "error": "",
                })
                continue
            account = (
                campaign.advertiser_identity.external_accounts
                .filter(channel=channel)
                .exclude(status__in=[ExternalAdvertisingAccount.STATUS_REVOKED, ExternalAdvertisingAccount.STATUS_DISCONNECTED])
                .first()
            ) if campaign.advertiser_identity_id else None
            latest = execution.reporting_snapshots.order_by("-reporting_end").first() if execution else None
            cards.append({
                "channel": channel,
                "label": {"meta": "Meta", "google": "Google / YouTube", "tiktok": "TikTok", "linkedin": "LinkedIn"}[channel],
                "connection_status": provider_for(channel).get_connection_status(account) if account else "not_connected",
                "execution_status": execution.status if execution else "draft",
                "external_campaign_id": execution.external_campaign_id if execution else "",
                "budget_allocation": execution.budget_allocation if execution else self._campaign_budget(campaign, channel),
                "currency": (execution.currency if execution else "") or (account.metadata.get("currency", "") if account else ""),
                "spend": latest.spend if latest else None,
                "impressions": latest.impressions if latest else 0,
                "clicks": latest.clicks if latest else 0,
                "last_sync": execution.last_synced_at if execution else None,
                "error": execution.last_error if execution else "",
            })
        return cards


external_campaign_execution_service = ExternalCampaignExecutionService()
