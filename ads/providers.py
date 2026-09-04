import logging
import re
import secrets
from dataclasses import dataclass, field
from datetime import timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests
from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from .credentials import credential_encryption_service
from .models import (
    AdvertisingConnectionAuditLog,
    AdvertisingCredential,
    AdvertisingOAuthState,
    ExternalAdvertisingAccount,
)


logger = logging.getLogger(__name__)


class ProviderConfigurationError(Exception):
    pass


class ProviderAuthorizationError(Exception):
    def __init__(self, message, *, stage="", http_status=None, safe_details=None):
        super().__init__(message)
        self.stage = stage
        self.http_status = http_status
        self.safe_details = safe_details or {}


class ProviderAPIError(Exception):
    def __init__(self, message, *, stage="", http_status=None, safe_details=None):
        super().__init__(message)
        self.stage = stage
        self.http_status = http_status
        self.safe_details = safe_details or {}


@dataclass
class DiscoveredAdAccount:
    external_account_id: str
    display_name: str
    currency: str = ""
    timezone: str = ""
    account_status: str = ""
    permission_summary: str = ""
    metadata: dict = field(default_factory=dict)


class AdvertisingProviderAdapter:
    provider = ""
    connection_flag = ""
    authorization_base_url = ""
    token_url = ""
    revoke_url = ""
    default_scopes = []

    def configured(self):
        return bool(self.client_id and self.client_secret and getattr(settings, self.connection_flag, False))

    @property
    def client_id(self):
        return getattr(settings, f"ADS_{self.provider.upper()}_CLIENT_ID", "")

    @property
    def client_secret(self):
        return getattr(settings, f"ADS_{self.provider.upper()}_CLIENT_SECRET", "")

    def redirect_uri(self, request):
        return request.build_absolute_uri(
            reverse("ads_api:management_connected_account_callback", args=[self.provider])
        )

    def get_authorization_url(self, request, oauth_state):
        if not self.configured():
            raise ProviderConfigurationError("provider_not_configured")
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri(request),
            "response_type": "code",
            "state": oauth_state.state,
            "scope": self.scope_string(),
        }
        params.update(self.authorization_params())
        return f"{self.authorization_base_url}?{urlencode(params)}"

    def authorization_params(self):
        return {}

    def scope_string(self):
        return " ".join(self.default_scopes)

    def exchange_code(self, code, request):
        if not self.configured():
            raise ProviderConfigurationError("provider_not_configured")
        response = requests.post(
            self.token_url,
            data={
                "grant_type": "authorization_code",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "redirect_uri": self.redirect_uri(request),
                "code": code,
            },
            timeout=20,
        )
        try:
            data = response.json()
        except ValueError:
            data = {}
        summary = {
            "http_status": response.status_code,
            "access_credential_present": bool(data.get("access_token")),
            "refresh_credential_present": bool(data.get("refresh_token")),
            "expires_in_present": data.get("expires_in") is not None,
            "scope_returned": str(data.get("scope") or ""),
            "credential_type": str(data.get("token_type") or ""),
        }
        if response.status_code >= 400:
            raise ProviderAuthorizationError(
                "token_exchange_failed",
                stage="code_exchange",
                http_status=response.status_code,
                safe_details={**summary, "reason": str(data.get("error") or "token_exchange_failed")[:120]},
            )
        if not data.get("access_token"):
            raise ProviderAuthorizationError(
                "missing_access_token",
                stage="token_response_validation",
                http_status=response.status_code,
                safe_details=summary,
            )
        data["_safe_token_summary"] = summary
        return data

    def refresh_credentials(self, credential, *, only_if_expired=False):
        """Refresh one credential without losing a rotated/omitted refresh token.

        The row lock makes concurrent expired-access-token requests converge on a
        single refresh.  A second request that acquires the lock after the first
        one will reuse the newly persisted access token instead of refreshing
        again.
        """
        external_account = credential.external_account
        try:
            with transaction.atomic():
                credential = (
                    AdvertisingCredential.objects.select_for_update()
                    .select_related("external_account", "external_account__advertiser_identity")
                    .get(pk=credential.pk)
                )
                external_account = credential.external_account
                if credential.revoked_at:
                    raise ProviderAuthorizationError("credential_revoked")
                if self._refresh_token_expired(credential):
                    raise ProviderAuthorizationError("refresh_token_expired")
                if (
                    only_if_expired
                    and credential.access_token_expires_at
                    and credential.access_token_expires_at > timezone.now()
                ):
                    return credential

                refresh_token = credential_encryption_service.decrypt(credential.encrypted_refresh_token)
                if not refresh_token:
                    raise ProviderAuthorizationError("missing_refresh_token")
                try:
                    response = requests.post(
                        self.token_url,
                        data={
                            "grant_type": "refresh_token",
                            "client_id": self.client_id,
                            "client_secret": self.client_secret,
                            "refresh_token": refresh_token,
                        },
                        timeout=20,
                    )
                except requests.RequestException as exc:
                    raise ProviderAuthorizationError("refresh_failed") from exc
                if response.status_code >= 400:
                    raise ProviderAuthorizationError("refresh_failed")
                try:
                    data = response.json()
                except ValueError as exc:
                    raise ProviderAuthorizationError("refresh_failed") from exc
                if not data.get("access_token"):
                    raise ProviderAuthorizationError("refresh_failed")

                updated_credential = save_credential_tokens(
                    external_account,
                    self.provider,
                    data,
                    scopes=credential.scopes,
                )
                audit_connection(
                    self.provider,
                    AdvertisingConnectionAuditLog.EVENT_TOKEN_REFRESHED,
                    external_account=external_account,
                    advertiser_identity=external_account.advertiser_identity,
                    status="connected",
                )
                return updated_credential
        except ProviderAuthorizationError as exc:
            if str(exc) in {"refresh_token_expired", "missing_refresh_token", "refresh_failed"}:
                self._mark_refresh_failed(external_account)
            raise

    def revoke_credentials(self, credential):
        credential.revoked_at = timezone.now()
        credential.encrypted_access_token = None
        credential.encrypted_refresh_token = None
        credential.save(update_fields=["revoked_at", "encrypted_access_token", "encrypted_refresh_token", "updated_at"])
        return True

    def list_ad_accounts(self, credential):
        raise NotImplementedError

    def validate_account_access(self, credential, external_account_id):
        return any(account.external_account_id == external_account_id for account in self.list_ad_accounts(credential))

    def validate_campaign(self, campaign, external_account=None):
        from .execution import external_campaign_execution_service

        return external_campaign_execution_service.validate_campaign(campaign, self.provider, external_account)

    def build_external_payload(self, campaign, external_account=None):
        from .execution import external_campaign_execution_service

        return external_campaign_execution_service.build_external_payload(campaign, self.provider, external_account)

    def get_connection_status(self, external_account):
        credential = getattr(external_account, "credential", None)
        if external_account.status != ExternalAdvertisingAccount.STATUS_CONNECTED:
            return external_account.status
        if not credential or credential.revoked_at:
            return ExternalAdvertisingAccount.STATUS_REVOKED
        if self._refresh_token_expired(credential):
            return ExternalAdvertisingAccount.STATUS_REAUTHORIZATION_REQUIRED
        if (
            credential.access_token_expires_at
            and credential.access_token_expires_at <= timezone.now()
            and not self._has_usable_refresh_token(credential)
        ):
            return ExternalAdvertisingAccount.STATUS_EXPIRED
        return ExternalAdvertisingAccount.STATUS_CONNECTED

    @staticmethod
    def _refresh_token_expired(credential):
        return bool(
            credential.refresh_token_expires_at
            and credential.refresh_token_expires_at <= timezone.now()
        )

    def _has_usable_refresh_token(self, credential):
        return bool(
            credential.encrypted_refresh_token
            and not credential.revoked_at
            and not self._refresh_token_expired(credential)
        )

    def _bearer_headers(self, credential):
        return {"Authorization": f"Bearer {credential_encryption_service.decrypt(credential.encrypted_access_token)}"}

    def _mark_refresh_failed(self, external_account):
        external_account.status = ExternalAdvertisingAccount.STATUS_REAUTHORIZATION_REQUIRED
        external_account.save(update_fields=["status", "updated_at"])
        audit_connection(
            self.provider,
            AdvertisingConnectionAuditLog.EVENT_REFRESH_FAILED,
            external_account=external_account,
            advertiser_identity=external_account.advertiser_identity,
            status=external_account.status,
        )

    def create_campaign(self, execution, payload, *, idempotency_key=None):
        raise NotImplementedError("external_campaign_publishing_not_implemented")

    def update_campaign(self, execution, payload, *, idempotency_key=None):
        raise NotImplementedError("external_campaign_update_not_implemented")

    def pause_campaign(self, execution):
        raise NotImplementedError("external_campaign_pause_not_implemented")

    def resume_campaign(self, execution):
        raise NotImplementedError("external_campaign_resume_not_implemented")

    def fetch_campaign(self, execution):
        raise NotImplementedError("external_campaign_fetch_not_implemented")

    def fetch_reporting(self, execution, reporting_start=None, reporting_end=None):
        raise NotImplementedError("external_reporting_sync_not_implemented")

    def sync_status(self, execution):
        data = self.fetch_campaign(execution)
        return {
            "status": data.get("status", execution.status),
            "external_status": data.get("external_status", data.get("status", "")),
        }


class MetaAdsProvider(AdvertisingProviderAdapter):
    provider = "meta"
    connection_flag = "ADS_META_CONNECTION_ENABLED"
    authorization_base_url = "https://www.facebook.com/v24.0/dialog/oauth"
    token_url = "https://graph.facebook.com/v24.0/oauth/access_token"
    default_scopes = ["ads_read", "business_management", "pages_show_list", "instagram_business_basic"]

    def scope_string(self):
        return ",".join(self.default_scopes)

    def list_ad_accounts(self, credential):
        response = requests.get(
            "https://graph.facebook.com/v24.0/me/adaccounts",
            headers=self._bearer_headers(credential),
            params={"fields": "id,name,account_status,currency,timezone_name,business"},
            timeout=20,
        )
        if response.status_code >= 400:
            raise ProviderAPIError("meta_account_discovery_failed")
        return [
            DiscoveredAdAccount(
                external_account_id=str(item.get("id") or "").replace("act_", ""),
                display_name=item.get("name") or str(item.get("id") or ""),
                currency=item.get("currency") or "",
                timezone=item.get("timezone_name") or "",
                account_status=str(item.get("account_status") or ""),
                permission_summary="authorized_ad_account",
                metadata={"raw_id": item.get("id")},
            )
            for item in response.json().get("data", [])
        ]


class GoogleAdsProvider(AdvertisingProviderAdapter):
    provider = "google"
    connection_flag = "ADS_GOOGLE_CONNECTION_ENABLED"
    authorization_base_url = "https://accounts.google.com/o/oauth2/v2/auth"
    token_url = "https://oauth2.googleapis.com/token"
    default_scopes = ["https://www.googleapis.com/auth/adwords"]
    api_version = "v25"
    api_base_url = "https://googleads.googleapis.com"

    @property
    def developer_token(self):
        return getattr(settings, "ADS_GOOGLE_DEVELOPER_TOKEN", "")

    def authorization_params(self):
        return {"access_type": "offline", "prompt": "consent"}

    @property
    def login_customer_id(self):
        return getattr(settings, "ADS_GOOGLE_LOGIN_CUSTOMER_ID", "")

    def configured(self):
        return super().configured() and bool(self.developer_token)

    def _google_headers(self, credential, *, idempotency_key=None):
        headers = {
            **self._bearer_headers(credential),
            "developer-token": self.developer_token,
            "Content-Type": "application/json",
        }
        if self.login_customer_id:
            headers["login-customer-id"] = self.login_customer_id.replace("-", "")
        if idempotency_key:
            headers["request-id"] = idempotency_key
        return headers

    def _customer_id(self, execution_or_account):
        account = getattr(execution_or_account, "external_account", execution_or_account)
        return str(account.external_account_id).replace("customers/", "").replace("-", "")

    def _credential(self, execution):
        credential = getattr(execution.external_account, "credential", None)
        if not credential:
            raise ProviderAuthorizationError("missing_credential")
        if credential.revoked_at:
            raise ProviderAuthorizationError("credential_revoked")
        if self._refresh_token_expired(credential):
            self._mark_refresh_failed(credential.external_account)
            raise ProviderAuthorizationError("refresh_token_expired")
        if credential.access_token_expires_at and credential.access_token_expires_at <= timezone.now():
            if not self._has_usable_refresh_token(credential):
                raise ProviderAuthorizationError("credential_expired")
            return self.refresh_credentials(credential, only_if_expired=True)
        return credential

    def list_ad_accounts(self, credential):
        logger.warning("Google Ads discovery entering listAccessibleCustomers")
        response = requests.get(
            f"{self.api_base_url}/{self.api_version}/customers:listAccessibleCustomers",
            headers=self._google_headers(credential),
            timeout=20,
        )
        if response.status_code >= 400:
            safe_error = self._safe_google_error(response)
            logger.warning(
                "Google Ads listAccessibleCustomers failed http_status=%s "
                "google_ads_error_code=%s",
                response.status_code,
                safe_error.get("google_ads_error_code") or "none",
            )
            raise ProviderAPIError(
                "google_account_discovery_failed",
                stage="list_accessible_customers",
                http_status=response.status_code,
                safe_details=safe_error,
            )
        accessible_roots = self._safe_customer_resource_names(
            response.json().get("resourceNames", [])
        )
        configured_login_resource = ""
        configured_login_id = str(self.login_customer_id or "").replace("-", "")
        if configured_login_id.isdigit():
            configured_login_resource = f"customers/{configured_login_id}"
        logger.warning(
            "Google Ads listAccessibleCustomers succeeded resource_names=%s "
            "includes_login_customer=%s",
            accessible_roots,
            bool(configured_login_resource and configured_login_resource in accessible_roots),
        )
        logger.warning(
            "Google Ads manager hierarchy target login_customer_id=%s",
            configured_login_id if configured_login_id.isdigit() else "none",
        )
        if configured_login_resource:
            if configured_login_resource not in accessible_roots:
                raise ProviderAuthorizationError(
                    "configured_login_customer_not_accessible",
                    stage="manager_hierarchy_discovery",
                )
            discovery_roots = [configured_login_resource]
        else:
            discovery_roots = accessible_roots
        discovered = {}
        query = (
            "SELECT customer_client.client_customer, customer_client.descriptive_name, "
            "customer_client.currency_code, customer_client.time_zone, customer_client.manager, "
            "customer_client.status, customer_client.level, customer_client.test_account "
            "FROM customer_client"
        )
        for resource_name in discovery_roots:
            root_id = str(resource_name).split("/")[-1].replace("-", "")
            if not root_id:
                continue
            logger.warning(
                "Google Ads customer_client query operating_customer_id=%s "
                "login_customer_id=%s",
                root_id,
                configured_login_id if configured_login_id.isdigit() else "none",
            )
            try:
                hierarchy = self._search_google(root_id, credential, query, stage="manager_hierarchy_discovery")
            except (ProviderAPIError, ProviderAuthorizationError) as exc:
                if getattr(exc, "stage", ""):
                    raise
                raise ProviderAPIError("google_account_discovery_failed", stage="manager_hierarchy_discovery") from exc
            for row in hierarchy.get("results", []):
                client = row.get("customerClient") or row.get("customer_client") or {}
                if client.get("manager") is True:
                    continue
                client_resource = client.get("clientCustomer") or client.get("client_customer") or ""
                client_id = str(client_resource).split("/")[-1].replace("-", "")
                if not client_id:
                    continue
                status = str(client.get("status") or "").upper()
                test_account = client.get("testAccount") if "testAccount" in client else client.get("test_account")
                allowlist = {
                    str(value).replace("customers/", "").replace("-", "")
                    for value in (getattr(settings, "ADS_GOOGLE_TEST_ACCOUNT_ALLOWLIST", []) or [])
                }
                eligible_closed_test_account = (
                    status in {"CLOSED", "CANCELED", "CANCELLED"}
                    and getattr(settings, "ADS_EXTERNAL_CAMPAIGN_TEST_MODE_ENABLED", False) is True
                    and test_account is True
                    and client_id in allowlist
                    and bool(configured_login_id)
                    and root_id == configured_login_id
                )
                if status and status not in {"ENABLED", "UNKNOWN", "UNSPECIFIED"} and not eligible_closed_test_account:
                    continue
                discovered[client_id] = DiscoveredAdAccount(
                    external_account_id=client_id,
                    display_name=str(client.get("descriptiveName") or client.get("descriptive_name") or client_resource),
                    currency=str(client.get("currencyCode") or client.get("currency_code") or ""),
                    timezone=str(client.get("timeZone") or client.get("time_zone") or ""),
                    account_status=status.lower(),
                    permission_summary="manager_hierarchy_verified",
                    metadata={
                        "manager_customer_id": root_id,
                        "level": client.get("level"),
                        "test_account": test_account is True,
                    },
                )
        return list(discovered.values())

    @staticmethod
    def _safe_customer_resource_names(resource_names):
        safe_names = []
        for resource_name in resource_names if isinstance(resource_names, list) else []:
            normalized = str(resource_name or "").replace("-", "")
            if re.fullmatch(r"customers/\d+", normalized):
                safe_names.append(normalized)
        return safe_names

    def create_campaign(self, execution, payload, *, idempotency_key=None):
        if execution.external_campaign_id:
            return self.fetch_campaign(execution)
        credential = self._credential(execution)
        customer_id = self._customer_id(execution)
        budget_name = f"Arolana Test Budget {execution.idempotency_key[:12]}"
        campaign_name = f"{payload['campaign']['name']} [Arolana Test {execution.pk}]"
        budget_response = self._post_google(
            f"/customers/{customer_id}/campaignBudgets:mutate",
            credential,
            {
                "operations": [
                    {
                        "create": {
                            "name": budget_name,
                            "amountMicros": int((execution.budget_allocation or 0) * 1000000),
                            "deliveryMethod": "STANDARD",
                            "explicitlyShared": False,
                        }
                    }
                ],
                "partialFailure": False,
                "validateOnly": False,
            },
            idempotency_key=idempotency_key,
            stage="campaign_budget_create",
        )
        budget_resource = budget_response.get("results", [{}])[0].get("resourceName")
        if not budget_resource:
            raise ProviderAPIError("google_budget_create_missing_resource", stage="campaign_budget_create")
        campaign_create = {
            "name": campaign_name,
            "status": "PAUSED",
            "advertisingChannelType": "DEMAND_GEN",
            "campaignBudget": budget_resource,
            "containsEuPoliticalAdvertising": "DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING",
            "targetSpend": {},
        }
        customer_timezone = str(execution.external_account.metadata.get("timezone") or settings.TIME_ZONE)
        if execution.campaign.start_date is not None:
            campaign_create["startDateTime"] = self._google_datetime(
                execution.campaign.start_date,
                customer_timezone,
                end_of_day=False,
            )
        if execution.campaign.end_date is not None:
            campaign_create["endDateTime"] = self._google_datetime(
                execution.campaign.end_date,
                customer_timezone,
                end_of_day=True,
            )
        campaign_response = self._post_google(
            f"/customers/{customer_id}/campaigns:mutate",
            credential,
            {
                "operations": [
                    {
                        "create": campaign_create
                    }
                ],
                "partialFailure": False,
                "validateOnly": False,
            },
            idempotency_key=idempotency_key,
            stage="campaign_create",
        )
        campaign_resource = campaign_response.get("results", [{}])[0].get("resourceName")
        if not campaign_resource:
            raise ProviderAPIError("google_campaign_create_missing_resource", stage="campaign_create")
        external_campaign_id = campaign_resource.split("/")[-1]
        readback = self.fetch_campaign_by_id(execution, external_campaign_id, stage="campaign_readback")
        mismatches = self._readback_mismatches(execution, payload, readback)
        if mismatches:
            audit_connection(
                self.provider,
                AdvertisingConnectionAuditLog.EVENT_READBACK_MISMATCH,
                advertiser_identity=execution.advertiser_identity,
                external_account=execution.external_account,
                status="mismatch",
                metadata={"mismatches": ",".join(mismatches), "external_campaign_id": external_campaign_id},
            )
        return {
            "external_campaign_id": external_campaign_id,
            "external_status": readback.get("status", "PAUSED"),
            "campaign_resource_name": campaign_resource,
            "budget_resource_name": budget_resource,
            "readback": readback,
            "readback_mismatches": mismatches,
        }

    def fetch_campaign(self, execution):
        if not execution.external_campaign_id:
            raise ProviderAPIError("missing_external_campaign_id")
        return self.fetch_campaign_by_id(execution, execution.external_campaign_id)

    def fetch_campaign_by_id(self, execution, external_campaign_id, *, stage="google_api_read"):
        credential = self._credential(execution)
        customer_id = self._customer_id(execution)
        query = (
            "SELECT campaign.id, campaign.name, campaign.status, "
            "campaign.advertising_channel_type, campaign.start_date_time, campaign.end_date_time, "
            "campaign.campaign_budget, customer.currency_code, customer.time_zone "
            "FROM campaign "
            f"WHERE campaign.id = {external_campaign_id} LIMIT 1"
        )
        data = self._search_google(customer_id, credential, query, stage=stage)
        row = (data.get("results") or [{}])[0]
        return self._normalize_google_campaign_row(row, fallback_id=external_campaign_id)

    def find_campaign_by_name(self, execution, campaign_name):
        credential = self._credential(execution)
        customer_id = self._customer_id(execution)
        safe_name = str(campaign_name or "")[:300].replace("\\", "\\\\").replace("'", "\\'")
        query = (
            "SELECT campaign.id, campaign.name, campaign.status, "
            "campaign.advertising_channel_type, campaign.start_date_time, campaign.end_date_time, "
            "campaign.campaign_budget "
            "FROM campaign "
            f"WHERE campaign.name = '{safe_name}' LIMIT 10"
        )
        data = self._search_google(customer_id, credential, query, stage="campaign_recovery_lookup")
        return [self._normalize_google_campaign_row(row) for row in data.get("results", [])]

    @staticmethod
    def _normalize_google_campaign_row(row, fallback_id=""):
        campaign = row.get("campaign", {})
        customer = row.get("customer", {})
        return {
            "external_campaign_id": str(campaign.get("id") or fallback_id),
            "name": campaign.get("name", ""),
            "status": campaign.get("status", ""),
            "campaign_type": campaign.get("advertisingChannelType") or campaign.get("advertising_channel_type", ""),
            "start_date_time": campaign.get("startDateTime") or campaign.get("start_date_time", ""),
            "end_date_time": campaign.get("endDateTime") or campaign.get("end_date_time", ""),
            "budget_resource_name": campaign.get("campaignBudget") or campaign.get("campaign_budget", ""),
            "currency": customer.get("currencyCode") or customer.get("currency_code", ""),
            "timezone": customer.get("timeZone") or customer.get("time_zone", ""),
        }

    def pause_campaign(self, execution):
        return self._update_campaign_status(execution, "PAUSED", AdvertisingConnectionAuditLog.EVENT_EXTERNAL_CAMPAIGN_PAUSED)

    def resume_campaign(self, execution):
        return self._update_campaign_status(execution, "ENABLED", AdvertisingConnectionAuditLog.EVENT_EXTERNAL_CAMPAIGN_RESUMED)

    def sync_status(self, execution):
        data = self.fetch_campaign(execution)
        status_map = {
            "PAUSED": "paused",
            "ENABLED": "active",
            "REMOVED": "completed",
        }
        return {
            "status": status_map.get(data.get("status"), execution.status),
            "external_status": data.get("status", ""),
            "readback": data,
        }

    def fetch_reporting(self, execution, reporting_start=None, reporting_end=None):
        credential = self._credential(execution)
        customer_id = self._customer_id(execution)
        start = reporting_start.isoformat() if hasattr(reporting_start, "isoformat") else reporting_start
        end = reporting_end.isoformat() if hasattr(reporting_end, "isoformat") else reporting_end
        where = f"WHERE campaign.id = {execution.external_campaign_id}"
        if start and end:
            where += f" AND segments.date BETWEEN '{start}' AND '{end}'"
        query = (
            "SELECT campaign.id, metrics.impressions, metrics.clicks, metrics.cost_micros, "
            "metrics.video_trueview_views, metrics.conversions, customer.currency_code "
            "FROM campaign "
            f"{where}"
        )
        try:
            data = self._search_google(customer_id, credential, query, stage="reporting_fetch")
        except (ProviderAPIError, ProviderAuthorizationError) as exc:
            details = getattr(exc, "safe_details", {}) or {}
            logger.warning(
                "Google Ads reporting failed stage=reporting_fetch http_status=%s "
                "google_ads_request_id=%s google_error_status=%s "
                "google_ads_error_code=%s google_field_path=%s google_message=%s "
                "failure_reason=%s",
                getattr(exc, "http_status", None) or "none",
                details.get("google_ads_request_id") or "none",
                details.get("google_error_status") or "none",
                details.get("google_ads_error_code") or "none",
                details.get("google_field_path") or "none",
                details.get("google_message") or "none",
                str(exc),
            )
            raise
        totals = {"impressions": 0, "clicks": 0, "spend": 0, "video_views": 0, "conversions": 0, "currency": execution.currency}
        for row in data.get("results", []):
            metrics = row.get("metrics", {})
            totals["impressions"] += int(metrics.get("impressions") or 0)
            totals["clicks"] += int(metrics.get("clicks") or 0)
            totals["spend"] += int(metrics.get("costMicros") or metrics.get("cost_micros") or 0)
            totals["video_views"] += int(
                metrics.get("videoTrueviewViews")
                or metrics.get("video_trueview_views")
                or 0
            )
            totals["conversions"] += int(float(metrics.get("conversions") or 0))
            customer = row.get("customer", {})
            totals["currency"] = customer.get("currencyCode") or customer.get("currency_code") or totals["currency"]
        totals["spend"] = str(totals["spend"] / 1000000)
        audit_connection(
            self.provider,
            AdvertisingConnectionAuditLog.EVENT_REPORT_PULLED,
            advertiser_identity=execution.advertiser_identity,
            external_account=execution.external_account,
            status="pulled",
            metadata={"external_campaign_id": execution.external_campaign_id},
        )
        return {"metrics": totals}

    def _update_campaign_status(self, execution, status, audit_event):
        credential = self._credential(execution)
        customer_id = self._customer_id(execution)
        if not execution.external_campaign_id:
            raise ProviderAPIError("missing_external_campaign_id")
        resource_name = f"customers/{customer_id}/campaigns/{execution.external_campaign_id}"
        data = self._post_google(
            f"/customers/{customer_id}/campaigns:mutate",
            credential,
            {
                "operations": [
                    {
                        "updateMask": "status",
                        "update": {"resourceName": resource_name, "status": status},
                    }
                ],
                "partialFailure": False,
                "validateOnly": False,
            },
            idempotency_key=f"{execution.idempotency_key}:{status}",
        )
        audit_connection(
            self.provider,
            audit_event,
            advertiser_identity=execution.advertiser_identity,
            external_account=execution.external_account,
            status=status.lower(),
            metadata={"external_campaign_id": execution.external_campaign_id},
        )
        return data

    def _post_google(self, path, credential, payload, *, idempotency_key=None, stage="google_api_mutation"):
        response = requests.post(
            f"{self.api_base_url}/{self.api_version}{path}",
            headers=self._google_headers(credential, idempotency_key=idempotency_key),
            json=payload,
            timeout=30,
        )
        if response.status_code in {401, 403}:
            raise ProviderAuthorizationError(
                "google_authorization_failed",
                stage=stage,
                http_status=response.status_code,
                safe_details=self._safe_google_error(response),
            )
        if response.status_code == 429:
            raise ProviderAPIError(
                "google_rate_limited",
                stage=stage,
                http_status=response.status_code,
                safe_details=self._safe_google_error(response),
            )
        if response.status_code >= 400:
            raise ProviderAPIError(
                "google_api_error",
                stage=stage,
                http_status=response.status_code,
                safe_details=self._safe_google_error(response),
            )
        data = response.json()
        if data.get("partialFailureError"):
            raise ProviderAPIError("google_partial_failure", stage=stage)
        return data

    def _search_google(self, customer_id, credential, query, *, stage="google_api_read"):
        response = requests.post(
            f"{self.api_base_url}/{self.api_version}/customers/{customer_id}/googleAds:search",
            headers=self._google_headers(credential),
            json={"query": query},
            timeout=30,
        )
        if response.status_code in {401, 403}:
            raise ProviderAuthorizationError("google_authorization_failed", stage=stage, http_status=response.status_code, safe_details=self._safe_google_error(response))
        if response.status_code == 429:
            raise ProviderAPIError("google_rate_limited", stage=stage, http_status=response.status_code, safe_details=self._safe_google_error(response))
        if response.status_code >= 400:
            raise ProviderAPIError("google_api_error", stage=stage, http_status=response.status_code, safe_details=self._safe_google_error(response))
        return response.json()

    @staticmethod
    def _safe_google_error(response):
        try:
            payload = response.json()
        except ValueError:
            return {"reason": "non_json_google_response"}
        error = payload.get("error") if isinstance(payload, dict) else {}
        error = error if isinstance(error, dict) else {}
        google_ads_error_code = ""
        google_ads_request_id = re.sub(
            r"[^A-Za-z0-9_-]",
            "",
            str((getattr(response, "headers", {}) or {}).get("request-id") or ""),
        )[:120]
        google_field_path = ""
        google_message = ""
        for detail in error.get("details", []) if isinstance(error.get("details"), list) else []:
            if not isinstance(detail, dict):
                continue
            if not google_ads_request_id:
                google_ads_request_id = re.sub(
                    r"[^A-Za-z0-9_-]",
                    "",
                    str(detail.get("requestId") or detail.get("request_id") or ""),
                )[:120]
            for item in detail.get("errors", []) if isinstance(detail.get("errors"), list) else []:
                if not isinstance(item, dict):
                    continue
                error_code = item.get("errorCode") or item.get("error_code")
                if isinstance(error_code, dict) and error_code:
                    category, value = next(iter(error_code.items()))
                    google_ads_error_code = f"{category}:{value}"[:160]
                location = item.get("location") if isinstance(item.get("location"), dict) else {}
                elements = location.get("fieldPathElements") or location.get("field_path_elements") or []
                path_parts = []
                for element in elements if isinstance(elements, list) else []:
                    if not isinstance(element, dict):
                        continue
                    field_name = re.sub(r"[^A-Za-z0-9_]", "", str(element.get("fieldName") or element.get("field_name") or ""))
                    if field_name:
                        index = element.get("index")
                        path_parts.append(f"{field_name}[{index}]" if isinstance(index, int) else field_name)
                if path_parts and not google_field_path:
                    google_field_path = ".".join(path_parts)[:240]
                if item.get("message") and not google_message:
                    google_message = GoogleAdsProvider._sanitize_google_message(item.get("message"))
        return {
            "google_error_status": str(error.get("status") or "")[:120],
            "google_message": google_message or GoogleAdsProvider._sanitize_google_message(error.get("message")),
            "google_ads_request_id": google_ads_request_id,
            "google_ads_error_code": google_ads_error_code,
            "google_field_path": google_field_path,
        }

    @staticmethod
    def _sanitize_google_message(message):
        value = str(message or "")[:1000]
        value = re.sub(r"[\r\n\t]+", " ", value)
        value = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+", "[redacted]", value)
        value = re.sub(
            r"(?i)\b(?:access[_ -]?token|refresh[_ -]?token|authorization[_ -]?code|"
            r"oauth[_ -]?state|client[_ -]?secret|developer[_ -]?token|encryption[_ -]?key)"
            r"\s*[:=]\s*[^\s,;]+",
            "[redacted]",
            value,
        )
        return value[:240]

    def _readback_mismatches(self, execution, payload, readback):
        mismatches = []
        if str(readback.get("external_campaign_id")) != str(execution.external_campaign_id or readback.get("external_campaign_id")):
            mismatches.append("campaign_id")
        if readback.get("status") and readback.get("status") != "PAUSED":
            mismatches.append("status_not_paused")
        if readback.get("campaign_type") and readback.get("campaign_type") != "DEMAND_GEN":
            mismatches.append("campaign_type")
        payload_currency = payload.get("budget", {}).get("currency")
        if readback.get("currency") and payload_currency and readback.get("currency") != payload_currency:
            mismatches.append("currency")
        return mismatches

    def _google_datetime(self, value, timezone_name, *, end_of_day=False):
        if value is None:
            return None
        try:
            customer_timezone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            customer_timezone = ZoneInfo(settings.TIME_ZONE)
        if timezone.is_naive(value):
            value = timezone.make_aware(value, customer_timezone)
        else:
            value = value.astimezone(customer_timezone)
        if end_of_day:
            value = value.replace(hour=23, minute=59, second=59, microsecond=0)
        else:
            value = value.replace(hour=0, minute=0, second=0, microsecond=0)
        return value.strftime("%Y-%m-%d %H:%M:%S")


class TikTokAdsProvider(AdvertisingProviderAdapter):
    provider = "tiktok"
    connection_flag = "ADS_TIKTOK_CONNECTION_ENABLED"
    authorization_base_url = "https://business-api.tiktok.com/portal/auth"
    token_url = "https://business-api.tiktok.com/open_api/v1.3/oauth2/access_token/"
    default_scopes = ["advertiser_management"]

    @property
    def client_id(self):
        return getattr(settings, "ADS_TIKTOK_CLIENT_ID", "") or getattr(settings, "ADS_TIKTOK_APP_ID", "")

    def exchange_code(self, code, request):
        response = requests.post(
            self.token_url,
            json={
                "app_id": self.client_id,
                "secret": self.client_secret,
                "auth_code": code,
            },
            timeout=20,
        )
        if response.status_code >= 400:
            raise ProviderAuthorizationError("token_exchange_failed")
        return response.json().get("data", response.json())

    def list_ad_accounts(self, credential):
        response = requests.get(
            "https://business-api.tiktok.com/open_api/v1.3/oauth2/advertiser/get/",
            headers={"Access-Token": credential_encryption_service.decrypt(credential.encrypted_access_token)},
            params={"app_id": self.client_id, "secret": self.client_secret},
            timeout=20,
        )
        if response.status_code >= 400:
            raise ProviderAPIError("tiktok_account_discovery_failed")
        data = response.json().get("data", {})
        return [
            DiscoveredAdAccount(
                external_account_id=str(item.get("advertiser_id") or item.get("id") or ""),
                display_name=item.get("advertiser_name") or item.get("name") or str(item.get("advertiser_id") or ""),
                account_status=str(item.get("status") or ""),
                permission_summary=str(item.get("role") or "authorized_advertiser"),
            )
            for item in data.get("list", data.get("advertisers", []))
        ]


class LinkedInAdsProvider(AdvertisingProviderAdapter):
    provider = "linkedin"
    connection_flag = "ADS_LINKEDIN_CONNECTION_ENABLED"
    authorization_base_url = "https://www.linkedin.com/oauth/v2/authorization"
    token_url = "https://www.linkedin.com/oauth/v2/accessToken"
    default_scopes = ["r_ads", "r_ads_reporting"]

    def list_ad_accounts(self, credential):
        response = requests.get(
            "https://api.linkedin.com/rest/adAccounts",
            headers={**self._bearer_headers(credential), "LinkedIn-Version": "202406"},
            timeout=20,
        )
        if response.status_code >= 400:
            raise ProviderAPIError("linkedin_account_discovery_failed")
        return [
            DiscoveredAdAccount(
                external_account_id=str(item.get("id") or ""),
                display_name=item.get("name") or str(item.get("id") or ""),
                currency=item.get("currency") or "",
                account_status=str(item.get("status") or ""),
                permission_summary="authorized_ad_account",
            )
            for item in response.json().get("elements", [])
        ]


PROVIDERS = {
    "meta": MetaAdsProvider(),
    "google": GoogleAdsProvider(),
    "tiktok": TikTokAdsProvider(),
    "linkedin": LinkedInAdsProvider(),
}


def provider_for(provider):
    try:
        return PROVIDERS[provider]
    except KeyError as exc:
        raise ProviderConfigurationError("unsupported_provider") from exc


def create_oauth_state(request, advertiser_identity, provider, *, metadata=None, session_key=None):
    if session_key is None:
        if not request.session.session_key:
            request.session.create()
        session_key = request.session.session_key
    state = AdvertisingOAuthState.objects.create(
        provider=provider,
        state=secrets.token_urlsafe(48),
        user=request.user,
        advertiser_identity=advertiser_identity,
        session_key=session_key,
        expires_at=timezone.now() + timedelta(minutes=10),
        redirect_uri=provider_for(provider).redirect_uri(request),
        metadata=metadata or {},
    )
    audit_connection(provider, AdvertisingConnectionAuditLog.EVENT_CONNECTION_INITIATED, request.user, advertiser_identity)
    return state


def validate_oauth_state(request, provider, state_value):
    with transaction.atomic():
        try:
            state = AdvertisingOAuthState.objects.select_for_update().get(state=state_value)
        except AdvertisingOAuthState.DoesNotExist as exc:
            raise ProviderAuthorizationError("invalid_state") from exc
        if state.provider != provider:
            raise ProviderAuthorizationError("provider_mismatch")
        if state.user_id != request.user.id:
            raise ProviderAuthorizationError("user_mismatch")
        if state.session_key and state.session_key != request.session.session_key:
            raise ProviderAuthorizationError("session_mismatch")
        if state.used_at:
            raise ProviderAuthorizationError("state_reused")
        if state.expires_at <= timezone.now():
            raise ProviderAuthorizationError("state_expired")
        consumed_at = timezone.now()
        consumed = AdvertisingOAuthState.objects.filter(
            pk=state.pk,
            used_at__isnull=True,
        ).update(used_at=consumed_at, updated_at=consumed_at)
        if consumed != 1:
            raise ProviderAuthorizationError("state_reused")
        state.used_at = consumed_at
        state.updated_at = consumed_at
        audit_connection(
            provider,
            AdvertisingConnectionAuditLog.EVENT_CALLBACK_ACCEPTED,
            request.user,
            state.advertiser_identity,
        )
        return state


def save_credential_tokens(external_account, provider, token_data, scopes=None):
    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")
    expires_in = token_data.get("expires_in") or token_data.get("access_token_expires_in")
    refresh_expires_in = token_data.get("refresh_expires_in")
    credential, _created = AdvertisingCredential.objects.get_or_create(
        external_account=external_account,
        defaults={"provider": provider},
    )
    credential.provider = provider
    credential.encrypted_access_token = credential_encryption_service.encrypt(access_token)
    if refresh_token:
        credential.encrypted_refresh_token = credential_encryption_service.encrypt(refresh_token)
    credential.access_token_expires_at = timezone.now() + timedelta(seconds=int(expires_in)) if expires_in else None
    # Google commonly omits refresh_token (and its expiry) on a refresh grant.
    # Preserve the already encrypted refresh credential and its recorded expiry
    # rather than clearing either from a partial token response.
    if refresh_expires_in is not None:
        credential.refresh_token_expires_at = timezone.now() + timedelta(seconds=int(refresh_expires_in))
    credential.scopes = scopes or token_data.get("scope", [])
    if isinstance(credential.scopes, str):
        credential.scopes = credential.scopes.replace(",", " ").split()
    credential.revoked_at = None
    credential.save()
    return credential


def audit_connection(provider, event_type, user=None, advertiser_identity=None, external_account=None, status="", message="", metadata=None):
    scrubbed = {}
    for key, value in (metadata or {}).items():
        lowered = str(key).lower()
        if any(secret in lowered for secret in ("token", "secret", "authorization")):
            continue
        if "code" in lowered and lowered != "google_ads_error_code":
            continue
        scrubbed[str(key)[:80]] = str(value)[:500]
    return AdvertisingConnectionAuditLog.objects.create(
        provider=provider,
        event_type=event_type,
        user=user,
        advertiser_identity=advertiser_identity,
        external_account=external_account,
        status=status,
        message=str(message or "")[:240],
        metadata=scrubbed,
    )
