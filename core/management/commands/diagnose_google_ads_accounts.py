import json

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from ads.credentials import credential_encryption_service
from ads.models import ExternalAdvertisingAccount


class Command(BaseCommand):
    help = "Read-only Google Ads accessible-customer and customer_client diagnostic."

    def add_arguments(self, parser):
        parser.add_argument("--external-account-id", required=True, type=int)
        parser.add_argument("--manager-customer-id", required=True)
        parser.add_argument("--refresh-access-in-memory", action="store_true")

    def handle(self, *args, **options):
        account = ExternalAdvertisingAccount.objects.select_related("credential").get(
            pk=options["external_account_id"],
            channel=ExternalAdvertisingAccount.CHANNEL_GOOGLE,
        )
        credential = getattr(account, "credential", None)
        if not credential or credential.revoked_at:
            raise CommandError("A usable encrypted Google credential was not found.")
        developer_token = str(getattr(settings, "ADS_GOOGLE_DEVELOPER_TOKEN", "") or "")
        if not developer_token:
            raise CommandError("ADS_GOOGLE_DEVELOPER_TOKEN is not configured.")
        configured_login = str(getattr(settings, "ADS_GOOGLE_LOGIN_CUSTOMER_ID", "") or "").replace("-", "")
        manager_id = str(options["manager_customer_id"]).replace("-", "")
        if configured_login != manager_id:
            raise CommandError("Configured login customer ID does not match the requested diagnostic manager.")

        access_token = credential_encryption_service.decrypt(credential.encrypted_access_token)
        if not access_token:
            raise CommandError("The encrypted Google access token could not be loaded.")
        if credential.access_token_expires_at and credential.access_token_expires_at <= timezone.now():
            if not options["refresh_access_in_memory"]:
                raise CommandError("The selected Google access token is expired; use --refresh-access-in-memory for a non-persisted read-only refresh.")
            access_token = self._refresh_access_token(credential)
        api_version = "v25"
        base_url = "https://googleads.googleapis.com"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "developer-token": developer_token,
            "login-customer-id": manager_id,
            "Content-Type": "application/json",
        }

        accessible_response = requests.get(
            f"{base_url}/{api_version}/customers:listAccessibleCustomers",
            headers=headers,
            timeout=30,
        )
        self.stdout.write(f"listAccessibleCustomers HTTP {accessible_response.status_code}")
        accessible_data = self._json(accessible_response)
        if accessible_response.status_code >= 400:
            self.stdout.write(json.dumps({"error": self._safe_error(accessible_data)}, sort_keys=True))
            raise CommandError("Accessible-customer query failed.")
        roots = [str(item) for item in accessible_data.get("resourceNames", [])]
        self.stdout.write(json.dumps({"resourceNames": roots}, sort_keys=True))

        query = (
            "SELECT customer_client.id, customer_client.descriptive_name, "
            "customer_client.manager, customer_client.level, customer_client.status, "
            "customer_client.test_account FROM customer_client"
        )
        hierarchy_response = requests.post(
            f"{base_url}/{api_version}/customers/{manager_id}/googleAds:search",
            headers=headers,
            json={"query": query},
            timeout=30,
        )
        self.stdout.write(f"customer_client HTTP {hierarchy_response.status_code}")
        hierarchy_data = self._json(hierarchy_response)
        if hierarchy_response.status_code >= 400:
            self.stdout.write(json.dumps({"error": self._safe_error(hierarchy_data)}, sort_keys=True))
            raise CommandError("customer_client hierarchy query failed.")

        rows = []
        for result in hierarchy_data.get("results", []):
            client = result.get("customerClient") or result.get("customer_client") or {}
            rows.append({
                "id": str(client.get("id") or ""),
                "descriptive_name": str(client.get("descriptiveName") or client.get("descriptive_name") or ""),
                "manager": client.get("manager"),
                "level": client.get("level"),
                "status": str(client.get("status") or ""),
                "test_account": client.get("testAccount") if "testAccount" in client else client.get("test_account"),
            })
        self.stdout.write(json.dumps({"customer_client_rows": rows}, sort_keys=True))

    def _refresh_access_token(self, credential):
        refresh_token = credential_encryption_service.decrypt(credential.encrypted_refresh_token)
        if not refresh_token:
            raise CommandError("No encrypted refresh token is available for the read-only diagnostic.")
        response = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": str(getattr(settings, "ADS_GOOGLE_CLIENT_ID", "") or ""),
                "client_secret": str(getattr(settings, "ADS_GOOGLE_CLIENT_SECRET", "") or ""),
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=30,
        )
        payload = self._json(response)
        summary = {
            "http_status": response.status_code,
            "access_token_present": bool(payload.get("access_token")),
            "refresh_token_present": bool(payload.get("refresh_token")),
            "expires_in_present": "expires_in" in payload,
            "scope": str(payload.get("scope") or ""),
            "token_type": str(payload.get("token_type") or ""),
        }
        self.stdout.write(json.dumps({"in_memory_refresh_token_response": summary}, sort_keys=True))
        if response.status_code >= 400 or not payload.get("access_token"):
            self.stdout.write(json.dumps({"error": self._safe_error(payload)}, sort_keys=True))
            raise CommandError("In-memory access-token refresh failed.")
        return payload["access_token"]

    @staticmethod
    def _json(response):
        try:
            value = response.json()
        except ValueError:
            return {"error": {"status": "NON_JSON_RESPONSE", "message": "Google returned a non-JSON response."}}
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _safe_error(payload):
        error = payload.get("error") if isinstance(payload, dict) else {}
        error = error if isinstance(error, dict) else {}
        safe = {
            "code": error.get("code"),
            "status": error.get("status"),
            "message": error.get("message"),
        }
        details = []
        for detail in error.get("details", []) if isinstance(error.get("details"), list) else []:
            if not isinstance(detail, dict):
                continue
            item = {key: detail.get(key) for key in ("@type", "requestId") if detail.get(key) is not None}
            errors = detail.get("errors")
            if isinstance(errors, list):
                item["errors"] = [
                    {
                        "errorCode": entry.get("errorCode"),
                        "message": entry.get("message"),
                    }
                    for entry in errors
                    if isinstance(entry, dict)
                ]
            if item:
                details.append(item)
        if details:
            safe["details"] = details
        return safe
