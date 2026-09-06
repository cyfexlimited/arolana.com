import json
import logging
from decimal import Decimal
from datetime import datetime
from urllib.parse import urlencode

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import IntegrityError, transaction
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.http import require_GET
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST

from .adapters import v2_recommendation_adapter
from .decisioning import decisioning_service
from .execution import external_campaign_execution_service
from .models import (
    AdCampaign,
    AdChannelExecution,
    AdvertisingCredential,
    AdEvent,
    AdvertisingConnectionAuditLog,
    AdvertisingOAuthState,
    CampaignAsset,
    ExternalAdvertisingAccount,
)
from .management import (
    AdvertiserAccessError,
    AdvertiserValidationError,
    connected_account_shells,
    create_campaign,
    create_creative,
    creative_queryset,
    current_advertiser_identity,
    identity_payload,
    owned_asset_options,
    overview_metrics,
    campaign_queryset,
    serialize_campaign,
    update_campaign,
)
from .providers import (
    ProviderAPIError,
    ProviderAuthorizationError,
    ProviderConfigurationError,
    audit_connection,
    create_oauth_state,
    provider_for,
    save_credential_tokens,
    validate_oauth_state,
)
from .credentials import CredentialEncryptionError

logger = logging.getLogger(__name__)

MAX_EVENT_BODY_BYTES = 4096
MAX_METADATA_KEYS = 20
SENSITIVE_METADATA_KEYS = {
    "access_token",
    "authorization",
    "card",
    "conversion_value",
    "password",
    "payment",
    "purchase",
    "refresh_token",
    "revenue",
    "secret",
    "token",
}
CLIENT_EVENT_TYPES = {AdEvent.EVENT_IMPRESSION, AdEvent.EVENT_CLICK, AdEvent.EVENT_VIEW}
CLIENT_SURFACE_FLAGS = {
    "web": "ADS_RECOMMENDATION_V2_WEB_ENABLED",
    "mobile_web": "ADS_RECOMMENDATION_V2_MOBILE_WEB_ENABLED",
    "app": "ADS_RECOMMENDATION_V2_APP_ENABLED",
}
MOBILE_ADS_OAUTH_RETURN_URL = "arolanastaffmobile://ads-connected-accounts"


class StaffMobileOAuthRedirect(HttpResponseRedirect):
    """Allow only Arolana's registered native callback scheme."""

    allowed_schemes = ["http", "https", "ftp", "arolanastaffmobile"]


def _feature_disabled_response():
    return JsonResponse({"success": False, "error": "ads_recommendation_v2_disabled"}, status=404)


def _dashboard_disabled_response():
    return JsonResponse({"success": False, "error": "ads_advertiser_dashboard_disabled"}, status=404)


def _dashboard_enabled():
    return bool(getattr(settings, "ADS_ADVERTISER_DASHBOARD_ENABLED", False))


def _wants_browser_html(request):
    return "text/html" in str(request.headers.get("Accept") or "").lower()


def _staff_mobile_ads_session(request):
    """Resolve the existing staff-mobile bearer session for Ads V2 only."""
    cached = getattr(request, "_ads_mobile_session", None)
    if cached is not None:
        return cached
    header = str(request.headers.get("Authorization") or "")
    scheme, _, raw_token = header.partition(" ")
    if scheme.lower() != "bearer" or not raw_token.strip():
        request._ads_mobile_session = None
        return None
    from staff_mobile.models import StaffMobileToken

    session = (
        StaffMobileToken.objects.select_related("user")
        .filter(
            token=raw_token.strip(),
            is_active=True,
            user__is_active=True,
            role__in=[StaffMobileToken.ROLE_VENDOR, StaffMobileToken.ROLE_PROVIDER],
        )
        .first()
    )
    request._ads_mobile_session = session
    return session


def _authenticated_user(request):
    user = getattr(request, "user", None)
    if user and user.is_authenticated:
        return user
    mobile_session = _staff_mobile_ads_session(request)
    if mobile_session and mobile_session.user:
        # Ads management continues to use the normal advertiser ownership
        # resolver; the bearer token only supplies the authenticated user.
        request.user = mobile_session.user
        return mobile_session.user
    return None


def _mobile_oauth_session_for_state(provider, state_value):
    """Return the active mobile session bound to this opaque OAuth state."""
    if not state_value:
        return None
    oauth_state = (
        AdvertisingOAuthState.objects.select_related("user")
        .filter(provider=provider, state=state_value)
        .first()
    )
    session_id = (oauth_state.metadata or {}).get("mobile_staff_session_id") if oauth_state else None
    if not isinstance(session_id, int):
        return None
    from staff_mobile.models import StaffMobileToken

    session = (
        StaffMobileToken.objects.select_related("user")
        .filter(
            pk=session_id,
            is_active=True,
            user__is_active=True,
            role__in=[StaffMobileToken.ROLE_VENDOR, StaffMobileToken.ROLE_PROVIDER],
        )
        .first()
    )
    if not session or not session.user_id or session.user_id != oauth_state.user_id:
        return None
    return session


def _mobile_oauth_redirect(oauth_state, **params):
    """Return only the fixed staff-app callback scheme stored at initiation."""
    if not oauth_state or (oauth_state.metadata or {}).get("mobile_return_url") != MOBILE_ADS_OAUTH_RETURN_URL:
        return None
    safe_params = {key: str(value)[:120] for key, value in params.items() if value not in (None, "")}
    return f"{MOBILE_ADS_OAUTH_RETURN_URL}?{urlencode(safe_params)}"


def _mobile_oauth_redirect_response(oauth_state, **params):
    target = _mobile_oauth_redirect(oauth_state, **params)
    return StaffMobileOAuthRedirect(target) if target else None


def _management_identity(request):
    if not _dashboard_enabled():
        return None, _dashboard_disabled_response()
    user = _authenticated_user(request)
    if not user:
        return None, JsonResponse({"success": False, "error": "authentication_required"}, status=401)
    advertiser_id = request.GET.get("advertiser_id")
    try:
        return current_advertiser_identity(user, advertiser_id=advertiser_id), None
    except AdvertiserAccessError as exc:
        return None, JsonResponse({"success": False, "error": str(exc)}, status=403)


def _json_management_body(request):
    content_type = (request.content_type or "").lower()

    if content_type in {
        "application/x-www-form-urlencoded",
        "multipart/form-data",
    }:
        return request.POST

    data = _json_body(request)
    return {} if data is None else data


def _json_safe(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _json_body(request):
    content_length = request.META.get("CONTENT_LENGTH")
    try:
        if content_length and int(content_length) > MAX_EVENT_BODY_BYTES:
            return None
    except (TypeError, ValueError):
        return None

    try:
        return json.loads(request.body.decode("utf-8") or "{}")
    except (TypeError, ValueError, UnicodeDecodeError):
        return {}


def _safe_metadata(value):
    if not isinstance(value, dict):
        return {}

    metadata = {}
    for key, item in value.items():
        key = str(key)[:80]
        lowered_key = key.lower()
        if any(sensitive in lowered_key for sensitive in SENSITIVE_METADATA_KEYS):
            continue
        if isinstance(item, (str, int, float, bool)) or item is None:
            metadata[key] = str(item)[:500] if isinstance(item, str) else item
        if len(metadata) >= MAX_METADATA_KEYS:
            break
    return metadata


def _is_internal_test_request(request):
    user = getattr(request, "user", None)
    return bool(
        getattr(settings, "ADS_RECOMMENDATION_V2_INTERNAL_TESTING_ENABLED", False)
        and user
        and user.is_authenticated
        and getattr(user, "is_staff", False)
        and getattr(request, "session", {}).get("ads_v2_internal_test") is True
    )


def _client_surface(request):
    client = (request.GET.get("client") or request.GET.get("source") or "web").strip().lower()
    if client in {"app", "mobile", "mobile_app", "react_native"}:
        return "app"
    if client in {"mobile_web", "webview", "pwa"}:
        return "mobile_web"
    return "web"


def _client_surface_enabled(request):
    client = _client_surface(request)
    flag_name = CLIENT_SURFACE_FLAGS.get(client, "ADS_RECOMMENDATION_V2_WEB_ENABLED")
    return bool(getattr(settings, flag_name, False)), client


@require_GET
def recommendations_v2(request):
    if not getattr(settings, "ADS_RECOMMENDATION_V2_API_ENABLED", False):
        return _feature_disabled_response()
    surface_enabled, client = _client_surface_enabled(request)
    if not surface_enabled and not _is_internal_test_request(request):
        return _feature_disabled_response()

    try:
        limit = max(1, min(int(request.GET.get("limit", 10)), 50))
    except (TypeError, ValueError):
        limit = 10

    context = decisioning_service.context_from_request(request)
    candidates = decisioning_service.recommendations_for_request(request, limit=limit, context=context)
    adapted = v2_recommendation_adapter.adapt_results(
        candidates,
        surface=context.placement,
        client=client,
    )
    return JsonResponse(
        {
            "success": True,
            "context": {
                "placement": context.placement,
                "surface": context.surface,
                "page": context.page,
                "client": client,
                "internal_test": _is_internal_test_request(request),
            },
            "results": candidates,
            "adapter_results": adapted,
        }
    )


@require_POST
def management_campaign_external_action(request, campaign_id):
    identity, error = _management_identity(request)
    if error:
        return error
    user = _authenticated_user(request)
    if not getattr(user, "is_staff", False):
        return JsonResponse({"success": False, "error": "staff_required"}, status=403)
    try:
        campaign = campaign_queryset(identity).get(pk=campaign_id)
    except AdCampaign.DoesNotExist:
        return JsonResponse({"success": False, "error": "campaign_not_found"}, status=404)
    data = _json_management_body(request)
    channel = str(data.get("channel") or "google").lower()
    action = str(data.get("action") or "").lower()
    if channel != "google":
        return JsonResponse({"success": False, "error": "provider_write_not_enabled"}, status=400)
    try:
        account = ExternalAdvertisingAccount.objects.get(
            pk=int(data.get("external_account_id")),
            advertiser_identity=identity,
            channel=channel,
        )
    except (TypeError, ValueError, ExternalAdvertisingAccount.DoesNotExist):
        account = (
            identity.external_accounts
            .filter(channel=channel, status=ExternalAdvertisingAccount.STATUS_CONNECTED)
            .first()
        )
    if not account:
        return JsonResponse({"success": False, "error": "external_account_not_found"}, status=404)

    if action == "create":
        execution, result = external_campaign_execution_service.create_execution(
            campaign,
            channel,
            account,
            dry_run=False,
            user=user,
        )
        return JsonResponse(
            {
                "success": result.valid and execution.status in {AdChannelExecution.STATUS_PAUSED, AdChannelExecution.STATUS_ACTIVE},
                "execution": _safe_execution(execution),
                "errors": result.errors,
                "warnings": result.warnings,
            },
            status=200 if result.valid else 400,
        )

    try:
        execution = AdChannelExecution.objects.get(campaign=campaign, channel=channel, external_account=account)
    except AdChannelExecution.DoesNotExist:
        return JsonResponse({"success": False, "error": "execution_not_found"}, status=404)

    try:
        adapter = provider_for(channel)
        if action == "sync":
            synced = external_campaign_execution_service.sync_status(execution)
            return JsonResponse({"success": True, "execution": _safe_execution(synced)})
        if action == "pause":
            adapter.pause_campaign(execution)
            execution.status = AdChannelExecution.STATUS_PAUSED
            execution.external_status = "PAUSED"
            execution.last_synced_at = timezone.now()
            execution.save(update_fields=["status", "external_status", "last_synced_at", "updated_at"])
            return JsonResponse({"success": True, "execution": _safe_execution(execution)})
        if action == "resume":
            safety_errors = external_campaign_execution_service.live_mutation_safety_errors(campaign, channel, account, user=user)
            if safety_errors:
                return JsonResponse({"success": False, "errors": safety_errors}, status=400)
            adapter.resume_campaign(execution)
            execution.status = AdChannelExecution.STATUS_ACTIVE
            execution.external_status = "ENABLED"
            execution.last_synced_at = timezone.now()
            execution.save(update_fields=["status", "external_status", "last_synced_at", "updated_at"])
            return JsonResponse({"success": True, "execution": _safe_execution(execution)})
        if action == "reporting":
            start = _date_from_string(data.get("reporting_start")) or timezone.now().date()
            end = _date_from_string(data.get("reporting_end")) or start
            provider_payload = adapter.fetch_reporting(execution, start, end)
            snapshot = external_campaign_execution_service.normalize_reporting(execution, provider_payload, start, end)
            return JsonResponse(
                {
                    "success": True,
                    "reporting": {
                        "impressions": snapshot.impressions,
                        "clicks": snapshot.clicks,
                        "spend": str(snapshot.spend) if snapshot.spend is not None else None,
                        "video_views": snapshot.video_views,
                        "provider_conversions": snapshot.provider_conversions,
                        "currency": snapshot.currency,
                    },
                }
            )
    except (ProviderAPIError, ProviderAuthorizationError, NotImplementedError) as exc:
        execution.status = AdChannelExecution.STATUS_FAILED
        execution.last_error = str(exc)
        execution.save(update_fields=["status", "last_error", "updated_at"])
        return JsonResponse({"success": False, "error": str(exc), "execution": _safe_execution(execution)}, status=400)

    return JsonResponse({"success": False, "error": "unsupported_action"}, status=400)


def _safe_execution(execution):
    return {
        "id": execution.pk,
        "channel": execution.channel,
        "status": execution.status,
        "external_status": execution.external_status,
        "external_campaign_id": execution.external_campaign_id,
        "budget_allocation": str(execution.budget_allocation) if execution.budget_allocation is not None else None,
        "currency": execution.currency,
        "last_synced_at": execution.last_synced_at.isoformat() if execution.last_synced_at else None,
        "last_error": execution.last_error,
    }


def _date_from_string(value):
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except ValueError:
        return None


@csrf_exempt
@require_POST
def events_v2(request):
    if not getattr(settings, "ADS_RECOMMENDATION_V2_API_ENABLED", False):
        return _feature_disabled_response()

    data = _json_body(request)
    if data is None:
        return JsonResponse({"success": False, "error": "payload_too_large"}, status=413)

    event_uuid = data.get("event_uuid")
    delivery_id = data.get("delivery_id")
    event_type = data.get("event_type")
    if not event_uuid or event_type not in CLIENT_EVENT_TYPES:
        return JsonResponse({"success": False, "error": "invalid_event"}, status=400)

    asset = None
    asset_id = data.get("asset_id")
    if asset_id:
        try:
            asset = CampaignAsset.objects.select_related("campaign", "advertiser_identity").get(pk=int(asset_id))
        except (TypeError, ValueError, CampaignAsset.DoesNotExist):
            return JsonResponse({"success": False, "error": "invalid_asset"}, status=400)

    metadata = _safe_metadata(data.get("metadata", {}))
    if _is_internal_test_request(request):
        metadata["internal_test"] = True

    event, created = AdEvent.objects.get_or_create(
        event_uuid=event_uuid,
        defaults={
            "delivery_id": delivery_id or None,
            "event_type": event_type,
            "asset": asset,
            "campaign": asset.campaign if asset else None,
            "advertiser_identity": asset.advertiser_identity if asset else None,
            "session_id": data.get("session_id", "")[:200],
            "request_id": data.get("request_id", "")[:100],
            "event_source": data.get("event_source", "internal")[:50],
            "metadata": metadata,
            "user": request.user if request.user.is_authenticated else None,
        },
    )

    return JsonResponse(
        {
            "success": True,
            "created": created,
            "event_id": event.pk,
            "event_uuid": str(event.event_uuid),
        },
        status=201 if created else 200,
    )


@require_http_methods(["GET", "POST", "DELETE"])
def internal_test_session(request):
    user = getattr(request, "user", None)
    if not (
        getattr(settings, "ADS_RECOMMENDATION_V2_INTERNAL_TESTING_ENABLED", False)
        and user
        and user.is_authenticated
        and getattr(user, "is_staff", False)
    ):
        return JsonResponse({"success": False, "error": "forbidden"}, status=403)

    if request.method == "POST":
        request.session["ads_v2_internal_test"] = True
    elif request.method == "DELETE":
        request.session["ads_v2_internal_test"] = False

    return JsonResponse(
        {
            "success": True,
            "internal_test": request.session.get("ads_v2_internal_test") is True,
        }
    )


@require_GET
def management_current_advertiser(request):
    identity, error = _management_identity(request)
    if error:
        return error
    return JsonResponse({"success": True, "advertiser": identity_payload(identity)})


@require_GET
def management_overview(request):
    identity, error = _management_identity(request)
    if error:
        return error
    return JsonResponse(
        {
            "success": True,
            "advertiser": identity_payload(identity),
            "metrics": _json_safe(overview_metrics(identity)),
        }
    )


@require_http_methods(["GET", "POST"])
def management_campaigns(request):
    identity, error = _management_identity(request)
    if error:
        return error
    if request.method == "GET":
        return JsonResponse(
            {
                "success": True,
                "campaigns": _json_safe([
                    serialize_campaign(campaign)
                    for campaign in campaign_queryset(identity)
                ]),
            }
        )
    try:
        campaign, _asset = create_campaign(
            identity,
            _json_management_body(request),
            submit=bool(_json_management_body(request).get("submit")),
        )
    except AdvertiserValidationError as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=400)
    return JsonResponse({"success": True, "campaign": _json_safe(serialize_campaign(campaign))}, status=201)


@require_http_methods(["GET", "PATCH", "POST"])
def management_campaign_detail(request, campaign_id):
    identity, error = _management_identity(request)
    if error:
        return error
    try:
        campaign = campaign_queryset(identity).get(pk=campaign_id)
    except AdCampaign.DoesNotExist:
        return JsonResponse({"success": False, "error": "campaign_not_found"}, status=404)
    if request.method == "GET":
        return JsonResponse({"success": True, "campaign": _json_safe(serialize_campaign(campaign))})
    try:
        campaign = update_campaign(identity, campaign_id, _json_management_body(request))
    except (AdvertiserAccessError, AdvertiserValidationError) as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=400)
    return JsonResponse({"success": True, "campaign": _json_safe(serialize_campaign(campaign))})


@require_POST
def management_campaign_external_preview(request, campaign_id):
    identity, error = _management_identity(request)
    if error:
        return error
    user = _authenticated_user(request)
    if not getattr(user, "is_staff", False):
        return JsonResponse({"success": False, "error": "staff_required"}, status=403)
    try:
        campaign = campaign_queryset(identity).get(pk=campaign_id)
    except AdCampaign.DoesNotExist:
        return JsonResponse({"success": False, "error": "campaign_not_found"}, status=404)
    data = _json_management_body(request)
    channel = str(data.get("channel") or "").lower()
    account = None
    account_id = data.get("external_account_id")
    if account_id:
        try:
            account = ExternalAdvertisingAccount.objects.get(
                pk=int(account_id),
                advertiser_identity=identity,
                channel=channel,
            )
        except (TypeError, ValueError, ExternalAdvertisingAccount.DoesNotExist):
            return JsonResponse({"success": False, "error": "external_account_not_found"}, status=404)
    elif channel in external_campaign_execution_service.provider_channels():
        account = (
            identity.external_accounts
            .filter(channel=channel, status=ExternalAdvertisingAccount.STATUS_CONNECTED)
            .first()
        )
    result = external_campaign_execution_service.preview(campaign, channel, account)
    execution, _result = external_campaign_execution_service.create_execution(
        campaign,
        channel,
        account,
        dry_run=True,
        user=user,
    ) if channel in external_campaign_execution_service.provider_channels() and account else (None, result)
    return JsonResponse(
        {
            "success": True,
            "dry_run": True,
            "provider": channel,
            "execution_id": execution.pk if execution else None,
            "valid": result.valid,
            "objective_mapping": result.objective,
            "payload": result.payload,
            "warnings": result.warnings,
            "errors": result.errors,
        }
    )


@require_GET
def management_owned_assets(request):
    identity, error = _management_identity(request)
    if error:
        return error
    asset_type = request.GET.get("asset_type")
    assets = owned_asset_options(identity)
    if asset_type:
        assets = [asset for asset in assets if asset["asset_type"] == asset_type]
    return JsonResponse({"success": True, "assets": assets})


@require_http_methods(["GET", "POST"])
def management_creatives(request):
    identity, error = _management_identity(request)
    if error:
        return error
    if request.method == "GET":
        creatives = creative_queryset(identity)
        return JsonResponse(
            {
                "success": True,
                "creatives": [
                    {
                        "id": creative.pk,
                        "campaign_id": creative.campaign_id,
                        "name": creative.name,
                        "creative_type": creative.creative_type,
                        "headline": creative.headline,
                        "description": creative.description,
                        "cta_text": creative.cta_text,
                        "has_image": bool(creative.image),
                        "has_mobile_image": bool(creative.image_mobile),
                        "has_video": bool(creative.video_url),
                    }
                    for creative in creatives
                ],
            }
        )
    try:
        creative = create_creative(identity, _json_management_body(request))
    except (AdvertiserAccessError, AdvertiserValidationError) as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=400)
    return JsonResponse(
        {
            "success": True,
            "creative": {
                "id": creative.pk,
                "campaign_id": creative.campaign_id,
                "creative_type": creative.creative_type,
                "headline": creative.headline,
            },
        },
        status=201,
    )


@require_GET
def management_analytics(request):
    identity, error = _management_identity(request)
    if error:
        return error
    return JsonResponse(
        {
            "success": True,
            "overview": _json_safe(overview_metrics(identity)),
            "campaigns": _json_safe([
                serialize_campaign(campaign)
                for campaign in campaign_queryset(identity)
            ]),
        }
    )


@require_GET
def management_connected_accounts(request):
    identity, error = _management_identity(request)
    if error:
        return error
    return JsonResponse({"success": True, "accounts": connected_account_shells(identity)})


def _safe_discovered_account(account):
    return {
        "external_account_id": account.external_account_id,
        "display_name": account.display_name,
        "currency": account.currency,
        "timezone": account.timezone,
        "account_status": account.account_status,
        "permission_summary": account.permission_summary,
        "metadata": _safe_metadata(account.metadata),
    }


def _safe_external_account(account):
    return {
        "id": account.pk,
        "channel": account.channel,
        "external_account_id": account.external_account_id,
        "display_name": account.display_name,
        "status": account.status,
        "connected_at": account.connected_at.isoformat() if account.connected_at else None,
        "last_sync_at": account.last_sync_at.isoformat() if account.last_sync_at else None,
        "currency": account.metadata.get("currency", ""),
        "timezone": account.metadata.get("timezone", ""),
        "permission_summary": account.metadata.get("permission_summary", ""),
        "meta_page_id": account.metadata.get("meta_page_id", ""),
        "meta_page_name": account.metadata.get("meta_page_name", ""),
    }


def _provider_error_response(exc, status=400):
    return JsonResponse({"success": False, "error": str(exc)}, status=status)


@require_POST
def management_connected_account_connect(request, provider):
    identity, error = _management_identity(request)
    if error:
        return error
    data = _json_management_body(request)
    mobile_session = _staff_mobile_ads_session(request) if data.get("mobile_oauth") is True else None
    if data.get("mobile_oauth") is True and not mobile_session:
        return JsonResponse({"success": False, "error": "authentication_required"}, status=401)
    try:
        adapter = provider_for(provider)
        if not adapter.configured():
            raise ProviderConfigurationError("provider_not_configured")
        oauth_state = create_oauth_state(
            request,
            identity,
            provider,
            # Native WebBrowser cannot carry the app's bearer token through the
            # Google redirect. Bind the state to its active server-side mobile
            # session instead of weakening the existing browser-session path.
            metadata=(
                {
                    "mobile_staff_session_id": mobile_session.pk,
                    "mobile_return_url": MOBILE_ADS_OAUTH_RETURN_URL,
                }
                if mobile_session
                else None
            ),
            session_key="" if mobile_session else None,
        )
        authorization_url = adapter.get_authorization_url(request, oauth_state)
    except ProviderConfigurationError as exc:
        return _provider_error_response(exc, status=503)
    return JsonResponse(
        {
            "success": True,
            "provider": provider,
            "authorization_url": authorization_url,
            "state_expires_at": oauth_state.expires_at.isoformat(),
        }
    )


@require_GET
def management_connected_account_callback(request, provider):
    if not _dashboard_enabled():
        return _dashboard_disabled_response()
    user = _authenticated_user(request)
    state_value = request.GET.get("state", "")
    mobile_session = None
    if not user:
        mobile_session = _mobile_oauth_session_for_state(provider, state_value)
        if mobile_session:
            user = mobile_session.user
            request.user = user
    if not user:
        return JsonResponse({"success": False, "error": "authentication_required"}, status=401)

    code = request.GET.get("code", "")
    failure_stage = "state_validation"
    oauth_state = None
    identity = None
    safe_token_summary = {}
    try:
        adapter = provider_for(provider)
        oauth_state = validate_oauth_state(request, provider, state_value)
        failure_stage = "advertiser_authorization"
        identity = current_advertiser_identity(user, advertiser_id=oauth_state.advertiser_identity_id)
        if identity.pk != oauth_state.advertiser_identity_id:
            raise ProviderAuthorizationError("advertiser_mismatch")
        if request.GET.get("error"):
            raise ProviderAuthorizationError("oauth_denied")
        if not code:
            raise ProviderAuthorizationError("missing_code")
        with transaction.atomic():
            failure_stage = "code_exchange"
            token_data = adapter.exchange_code(code, request)
            safe_token_summary = token_data.pop("_safe_token_summary", {})
            failure_stage = "external_account_creation"
            pending_account = ExternalAdvertisingAccount.objects.create(
                advertiser_identity=identity,
                channel=provider,
                external_account_id=f"pending:{oauth_state.pk}",
                display_name=f"{provider.title()} pending account selection",
                status=ExternalAdvertisingAccount.STATUS_PENDING,
                metadata={"oauth_state_id": oauth_state.pk},
            )
            failure_stage = "credential_encryption"
            credential = save_credential_tokens(pending_account, provider, token_data)
            failure_stage = "list_accessible_customers"
            discovered_accounts = [_safe_discovered_account(account) for account in adapter.list_ad_accounts(credential)]
            pending_account.metadata = {
                "oauth_state_id": oauth_state.pk,
                "discovered_accounts": discovered_accounts,
            }
            pending_account.save(update_fields=["metadata", "updated_at"])
            failure_stage = "account_selection_session"
            audit_connection(
                provider,
                AdvertisingConnectionAuditLog.EVENT_CONNECTION_COMPLETED,
                user,
                identity,
                pending_account,
                status=pending_account.status,
                metadata={"discovered_account_count": len(discovered_accounts)},
            )
    except AdvertiserAccessError as exc:
        audit_connection(provider, AdvertisingConnectionAuditLog.EVENT_AUTHORIZATION_FAILED, user, status="forbidden")
        mobile_redirect = _mobile_oauth_redirect_response(oauth_state, provider=provider, oauth_error="authorization_failed")
        if mobile_redirect:
            return mobile_redirect
        if _wants_browser_html(request):
            return redirect("/ads/marketing/connected-accounts/?oauth_error=authorization_failed")
        return JsonResponse({"success": False, "error": str(exc)}, status=403)
    except ProviderConfigurationError as exc:
        mobile_redirect = _mobile_oauth_redirect_response(oauth_state, provider=provider, oauth_error="provider_not_configured")
        if mobile_redirect:
            return mobile_redirect
        if _wants_browser_html(request):
            return redirect("/ads/marketing/connected-accounts/?oauth_error=provider_not_configured")
        return _provider_error_response(exc, status=503)
    except (ProviderAuthorizationError, ProviderAPIError, IntegrityError, CredentialEncryptionError, ImproperlyConfigured) as exc:
        stage = str(getattr(exc, "stage", "") or failure_stage or "other")
        details = dict(safe_token_summary)
        details.update(getattr(exc, "safe_details", {}) or {})
        details.update({
            "stage": stage,
            "exception_class": exc.__class__.__name__,
            "http_status": getattr(exc, "http_status", None),
            "reason": str(exc),
        })
        logger.warning(
            "Google OAuth callback failed failure_stage=%s exception_class=%s "
            "reason=%s http_status=%s google_ads_error_code=%s",
            details["stage"],
            details["exception_class"],
            details["reason"],
            details.get("http_status") or "none",
            details.get("google_ads_error_code") or "none",
            extra={"google_oauth_diagnostic": details},
        )
        audit_connection(
            provider,
            AdvertisingConnectionAuditLog.EVENT_AUTHORIZATION_FAILED,
            user,
            identity,
            status="error",
            message=str(exc),
            metadata=details,
        )
        mobile_redirect = _mobile_oauth_redirect_response(oauth_state, provider=provider, oauth_error="connection_failed")
        if mobile_redirect:
            return mobile_redirect
        if _wants_browser_html(request):
            return redirect("/ads/marketing/connected-accounts/?oauth_error=connection_failed")
        return _provider_error_response(exc, status=400)

    mobile_redirect = _mobile_oauth_redirect_response(
        oauth_state,
        provider=provider,
        connection_id=pending_account.pk,
        status=ExternalAdvertisingAccount.STATUS_PENDING,
    )
    if mobile_redirect:
        return mobile_redirect
    if _wants_browser_html(request):
        request.session["ads_pending_account_selection"] = {
            "provider": provider,
            "connection_id": pending_account.pk,
        }
        return redirect("ads:marketing_connected_account_select", provider=provider)

    return JsonResponse(
        {
            "success": True,
            "provider": provider,
            "connection_id": pending_account.pk,
            "status": pending_account.status,
            "accounts": discovered_accounts,
        }
    )


@require_GET
def management_connected_account_accounts(request, provider):
    identity, error = _management_identity(request)
    if error:
        return error
    accounts = ExternalAdvertisingAccount.objects.filter(advertiser_identity=identity, channel=provider).exclude(
        status__in=[ExternalAdvertisingAccount.STATUS_DISCONNECTED, ExternalAdvertisingAccount.STATUS_REVOKED]
    )
    payload = []
    for account in accounts:
        if account.status == ExternalAdvertisingAccount.STATUS_PENDING:
            payload.append(
                {
                    **_safe_external_account(account),
                    "discovered_accounts": account.metadata.get("discovered_accounts", []),
                }
            )
        else:
            payload.append(_safe_external_account(account))
    return JsonResponse({"success": True, "provider": provider, "accounts": payload})


def _meta_page_account(identity, provider, account_id):
    if provider != ExternalAdvertisingAccount.CHANNEL_META:
        raise ProviderAPIError("meta_page_discovery_wrong_provider", stage="page_discovery")
    try:
        return ExternalAdvertisingAccount.objects.select_related("credential").get(
            pk=account_id,
            advertiser_identity=identity,
            channel=provider,
            status=ExternalAdvertisingAccount.STATUS_CONNECTED,
        )
    except ExternalAdvertisingAccount.DoesNotExist as exc:
        raise ProviderAPIError("connected_account_not_found", stage="page_discovery") from exc


def _safe_facebook_page(page):
    return {
        "page_id": page.page_id,
        "name": page.name,
        "category": page.category,
        "tasks": page.tasks,
    }


def _meta_page_error_response(exc):
    if isinstance(exc, ProviderAuthorizationError):
        status = 401
    elif getattr(exc, "http_status", None) == 429:
        status = 429
    elif str(exc) == "connected_account_not_found":
        status = 404
    else:
        status = 400
    return JsonResponse({"success": False, "error": str(exc)}, status=status)


@require_GET
def management_connected_account_pages(request, provider, account_id):
    identity, error = _management_identity(request)
    if error:
        return error
    try:
        account = _meta_page_account(identity, provider, account_id)
        credential = getattr(account, "credential", None)
        if not credential:
            raise ProviderAuthorizationError("missing_credential", stage="page_discovery")
        pages = provider_for(provider).list_facebook_pages(credential)
        selected_page_id = str((account.metadata or {}).get("meta_page_id") or "")
        if selected_page_id and not any(page.page_id == selected_page_id for page in pages):
            raise ProviderAPIError(
                "meta_selected_page_not_accessible",
                stage="page_selection",
            )
    except (ProviderAuthorizationError, ProviderAPIError) as exc:
        return _meta_page_error_response(exc)
    return JsonResponse({
        "success": True,
        "account_id": account.pk,
        "selected_page": {
            "page_id": str((account.metadata or {}).get("meta_page_id") or ""),
            "name": str((account.metadata or {}).get("meta_page_name") or ""),
        },
        "pages": [_safe_facebook_page(page) for page in pages],
    })


@require_POST
def management_connected_account_page_select(request, provider, account_id):
    identity, error = _management_identity(request)
    if error:
        return error
    data = _json_management_body(request)
    selected_page_id = str(data.get("page_id") or "").strip()
    if not selected_page_id:
        return JsonResponse({"success": False, "error": "missing_page_id"}, status=400)
    try:
        account = _meta_page_account(identity, provider, account_id)
        credential = getattr(account, "credential", None)
        if not credential:
            raise ProviderAuthorizationError("missing_credential", stage="page_selection")
        pages = provider_for(provider).list_facebook_pages(credential)
        selected = next((page for page in pages if page.page_id == selected_page_id), None)
        if not selected:
            raise ProviderAPIError("meta_page_not_accessible", stage="page_selection")
        account.metadata = {
            **(account.metadata or {}),
            "meta_page_id": selected.page_id,
            "meta_page_name": selected.name,
            "meta_page_selected_at": timezone.now().isoformat(),
        }
        account.save(update_fields=["metadata", "updated_at"])
    except (ProviderAuthorizationError, ProviderAPIError) as exc:
        return _meta_page_error_response(exc)
    return JsonResponse({
        "success": True,
        "account_id": account.pk,
        "selected_page": {
            "page_id": selected.page_id,
            "name": selected.name,
        },
    })


@require_POST
def management_connected_account_select(request, provider):
    identity, error = _management_identity(request)
    if error:
        return error
    data = _json_management_body(request)
    selected_id = str(data.get("external_account_id") or "").strip()
    if not selected_id:
        return JsonResponse({"success": False, "error": "missing_external_account_id"}, status=400)
    try:
        connection_id = int(data.get("connection_id"))
    except (TypeError, ValueError):
        return JsonResponse({"success": False, "error": "pending_connection_not_found"}, status=404)

    try:
        with transaction.atomic():
            # Lock the short-lived OAuth shell first. Do not join its optional
            # credential relation here: PostgreSQL cannot lock nullable outer joins.
            pending_account = ExternalAdvertisingAccount.objects.select_for_update().get(
                pk=connection_id,
                advertiser_identity=identity,
                channel=provider,
                status=ExternalAdvertisingAccount.STATUS_PENDING,
            )
            discovered = pending_account.metadata.get("discovered_accounts", [])
            selected = next(
                (item for item in discovered if str(item.get("external_account_id")) == selected_id),
                None,
            )
            if not selected:
                return JsonResponse({"success": False, "error": "external_account_not_discovered"}, status=400)

            active_accounts = ExternalAdvertisingAccount.objects.select_for_update().filter(
                channel=provider,
                external_account_id=selected_id,
            ).exclude(
                status__in=[
                    ExternalAdvertisingAccount.STATUS_DISCONNECTED,
                    ExternalAdvertisingAccount.STATUS_REVOKED,
                ]
            ).exclude(pk=pending_account.pk)
            existing_account = active_accounts.first()
            if existing_account and existing_account.advertiser_identity_id != identity.pk:
                audit_connection(
                    provider,
                    AdvertisingConnectionAuditLog.EVENT_AUTHORIZATION_FAILED,
                    request.user,
                    identity,
                    status="duplicate_external_account",
                )
                return JsonResponse({"success": False, "error": "duplicate_external_account"}, status=400)

            selected_metadata = _safe_metadata(selected)
            now = timezone.now()
            if existing_account:
                # This is a reconnect. Keep the established account identity and
                # atomically replace its credential with the newly authorized one.
                pending_credential = AdvertisingCredential.objects.select_for_update().filter(
                    external_account=pending_account
                ).first()
                if not pending_credential or not pending_credential.encrypted_access_token:
                    return JsonResponse({"success": False, "error": "pending_credential_not_found"}, status=409)

                existing_credential = AdvertisingCredential.objects.select_for_update().filter(
                    external_account=existing_account
                ).first()
                if existing_credential is None:
                    existing_credential = AdvertisingCredential(external_account=existing_account, provider=provider)

                existing_credential.provider = pending_credential.provider
                existing_credential.encrypted_access_token = pending_credential.encrypted_access_token
                # Google can omit refresh_token on a later authorization. Retain a
                # valid existing encrypted refresh credential in that case.
                if pending_credential.encrypted_refresh_token:
                    existing_credential.encrypted_refresh_token = pending_credential.encrypted_refresh_token
                    existing_credential.refresh_token_expires_at = pending_credential.refresh_token_expires_at
                existing_credential.access_token_expires_at = pending_credential.access_token_expires_at
                existing_credential.credential_version = pending_credential.credential_version
                existing_credential.scopes = pending_credential.scopes or existing_credential.scopes
                existing_credential.revoked_at = None
                existing_credential.metadata = pending_credential.metadata or existing_credential.metadata
                existing_credential.save()

                existing_account.display_name = selected.get("display_name", "")[:200]
                existing_account.status = ExternalAdvertisingAccount.STATUS_CONNECTED
                existing_account.connected_at = now
                existing_account.metadata = selected_metadata
                existing_account.save(update_fields=["display_name", "status", "connected_at", "metadata", "updated_at"])
                # The credential is now on the established row; deleting the shell
                # also removes its encrypted duplicate through the one-to-one FK.
                pending_account.delete()
                account = existing_account
            else:
                pending_account.external_account_id = selected_id
                pending_account.display_name = selected.get("display_name", "")[:200]
                pending_account.status = ExternalAdvertisingAccount.STATUS_CONNECTED
                pending_account.connected_at = now
                pending_account.metadata = selected_metadata
                pending_account.save(
                    update_fields=["external_account_id", "display_name", "status", "connected_at", "metadata", "updated_at"]
                )
                account = pending_account
    except ExternalAdvertisingAccount.DoesNotExist:
        return JsonResponse({"success": False, "error": "pending_connection_not_found"}, status=404)
    except IntegrityError:
        # A concurrent initial connection won the active-account constraint.
        # Keep the database invariant and return a controlled response instead
        # of surfacing a database exception to the browser.
        audit_connection(provider, AdvertisingConnectionAuditLog.EVENT_AUTHORIZATION_FAILED, request.user, identity, status="duplicate_external_account")
        return JsonResponse({"success": False, "error": "duplicate_external_account"}, status=409)

    request.session.pop("ads_pending_account_selection", None)
    audit_connection(provider, AdvertisingConnectionAuditLog.EVENT_ACCOUNT_SELECTED, request.user, identity, account, status=account.status)
    return JsonResponse({"success": True, "account": _safe_external_account(account)})


@require_POST
def management_connected_account_disconnect(request, provider):
    identity, error = _management_identity(request)
    if error:
        return error
    data = _json_management_body(request)
    try:
        account = ExternalAdvertisingAccount.objects.get(
            pk=int(data.get("account_id")),
            advertiser_identity=identity,
            channel=provider,
        )
    except (TypeError, ValueError, ExternalAdvertisingAccount.DoesNotExist):
        return JsonResponse({"success": False, "error": "connected_account_not_found"}, status=404)
    try:
        credential = getattr(account, "credential", None)
        if credential:
            provider_for(provider).revoke_credentials(credential)
    except ProviderAPIError:
        account.status = ExternalAdvertisingAccount.STATUS_REAUTHORIZATION_REQUIRED
    else:
        account.status = ExternalAdvertisingAccount.STATUS_REVOKED
    account.save(update_fields=["status", "updated_at"])
    audit_connection(provider, AdvertisingConnectionAuditLog.EVENT_CONNECTION_REVOKED, request.user, identity, account, status=account.status)
    return JsonResponse({"success": True, "account": _safe_external_account(account)})
