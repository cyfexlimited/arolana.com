import base64
import hashlib
import hmac
import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from .models import SocialAccount, SocialConnectionAuditLog, SocialDataDeletionRequest
from .oauth import callback_uri
from .services import platform_connection_enabled, platform_enabled


def signed_request(secret, payload):
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    signature = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).decode().rstrip("=")
    return f"{encoded_signature}.{encoded}"


class FacebookFeatureFlagTests(SimpleTestCase):
    @override_settings(
        SOCIAL_PUBLISHING_ENABLED=True,
        SOCIAL_PUBLISHING_FACEBOOK_ENABLED=True,
        SOCIAL_PUBLISHING_FACEBOOK_CONNECTION_ENABLED=False,
        SOCIAL_PUBLISHING_FACEBOOK_PUBLISHING_ENABLED=False,
    )
    def test_legacy_flag_cannot_enable_connection_or_publishing(self):
        self.assertFalse(platform_connection_enabled("facebook"))
        self.assertFalse(platform_enabled("facebook"))

    @override_settings(
        SOCIAL_PUBLISHING_ENABLED=True,
        SOCIAL_PUBLISHING_FACEBOOK_CONNECTION_ENABLED=True,
        SOCIAL_PUBLISHING_FACEBOOK_PUBLISHING_ENABLED=False,
    )
    def test_connection_does_not_enable_publishing(self):
        self.assertTrue(platform_connection_enabled("facebook"))
        self.assertFalse(platform_enabled("facebook"))


@override_settings(
    SOCIAL_PUBLISHING_META_APP_SECRET="facebook-secret",
    SOCIAL_PUBLISHING_INSTAGRAM_APP_SECRET="instagram-secret",
)
class MetaLifecycleCallbackTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            "meta-lifecycle@example.com", password="x", username="meta-lifecycle"
        )
        self.facebook = SocialAccount.objects.create(
            user=self.user, owner_role="vendor", platform="facebook", status="connected",
            external_account_id="page-123", access_token_encrypted="ciphertext-facebook",
            platform_metadata={"authorizing_user_id": "facebook-user-1"},
        )
        self.instagram = SocialAccount.objects.create(
            user=self.user, owner_role="vendor", platform="instagram", status="connected",
            external_account_id="instagram-user-1", access_token_encrypted="ciphertext-instagram",
        )

    def test_valid_facebook_deauthorization_revokes_only_facebook(self):
        response = self.client.post(
            reverse("social_publishing_web:meta_facebook_deauthorize"),
            {"signed_request": signed_request("facebook-secret", {"user_id": "facebook-user-1"})},
        )
        self.assertEqual(response.status_code, 200)
        self.facebook.refresh_from_db()
        self.instagram.refresh_from_db()
        self.assertEqual(self.facebook.status, "revoked")
        self.assertEqual(self.facebook.access_token_encrypted, "")
        self.assertEqual(self.instagram.status, "connected")
        self.assertEqual(self.instagram.access_token_encrypted, "ciphertext-instagram")
        audit = SocialConnectionAuditLog.objects.get(event="revoked", platform="facebook")
        self.assertEqual(audit.external_identity_id, "facebook-user-1")

    def test_instagram_callback_cannot_disconnect_facebook(self):
        response = self.client.post(
            reverse("social_publishing_web:meta_deauthorize"),
            {"signed_request": signed_request("instagram-secret", {"user_id": "instagram-user-1"})},
        )
        self.assertEqual(response.status_code, 200)
        self.facebook.refresh_from_db()
        self.assertEqual(self.facebook.status, "connected")
        self.assertFalse(SocialAccount.objects.filter(pk=self.instagram.pk).exists())

    def test_invalid_signature_and_malformed_payload_are_safe(self):
        invalid = self.client.post(
            reverse("social_publishing_web:meta_facebook_deauthorize"),
            {"signed_request": signed_request("wrong-secret", {"user_id": "facebook-user-1"})},
        )
        malformed = self.client.post(
            reverse("social_publishing_web:meta_facebook_deauthorize"),
            {"signed_request": "not-a-signed-request"},
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(malformed.status_code, 400)
        self.assertEqual(invalid.json(), {"success": False, "error": "Invalid signed request."})
        self.assertNotIn("facebook-secret", invalid.content.decode())
        self.facebook.refresh_from_db()
        self.assertEqual(self.facebook.status, "connected")

    def test_unknown_external_account_is_idempotent_and_safely_audited(self):
        request_value = signed_request("facebook-secret", {"user_id": "unknown-user"})
        for _ in range(2):
            response = self.client.post(
                reverse("social_publishing_web:meta_facebook_deauthorize"),
                {"signed_request": request_value},
            )
            self.assertEqual(response.status_code, 200)
        self.assertTrue(SocialAccount.objects.filter(pk=self.facebook.pk).exists())
        self.assertTrue(SocialConnectionAuditLog.objects.filter(
            platform="facebook", failure_reason="unknown_external_account"
        ).exists())

    def test_data_deletion_is_idempotent_and_confirmation_status_is_durable(self):
        request_value = signed_request("facebook-secret", {"user_id": "facebook-user-1"})
        first = self.client.post(
            reverse("social_publishing_web:meta_facebook_data_deletion"),
            {"signed_request": request_value},
        )
        second = self.client.post(
            reverse("social_publishing_web:meta_facebook_data_deletion"),
            {"signed_request": request_value},
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["confirmation_code"], second.json()["confirmation_code"])
        self.assertFalse(SocialAccount.objects.filter(pk=self.facebook.pk).exists())
        self.assertTrue(SocialAccount.objects.filter(pk=self.instagram.pk).exists())
        self.assertEqual(SocialDataDeletionRequest.objects.filter(platform="facebook").count(), 1)
        status = self.client.get(first.json()["url"])
        self.assertEqual(status.status_code, 200)


@override_settings(DEBUG=False, SITE_URL="https://arolana.com", ALLOWED_HOSTS=["arolana.com", "www.arolana.com", "testserver"])
class CanonicalHostTests(SimpleTestCase):
    def test_www_ordinary_request_redirects_with_path_and_query(self):
        response = self.client.get("/privacy/?language=en", HTTP_HOST="www.arolana.com")
        self.assertEqual(response.status_code, 308)
        self.assertEqual(response["Location"], "https://arolana.com/privacy/?language=en")

    def test_wrong_host_oauth_callback_fails_without_copying_query_to_location(self):
        response = self.client.get(
            "/social-publishing/callback/facebook/?code=secret-code&state=secret-state",
            HTTP_HOST="www.arolana.com",
        )
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("Location", response)
        self.assertNotIn("secret-code", response.content.decode())
        self.assertNotIn("secret-state", response.content.decode())

    def test_wrong_host_meta_lifecycle_callback_does_not_redirect_signed_body(self):
        response = self.client.post(
            "/social-publishing/meta/facebook/deauthorize/",
            {"signed_request": "sensitive-signed-request"},
            HTTP_HOST="www.arolana.com",
        )
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("Location", response)
        self.assertNotIn("sensitive-signed-request", response.content.decode())

    def test_facebook_callback_builder_uses_canonical_site_url(self):
        request = type("Request", (), {"build_absolute_uri": lambda self, path: f"https://www.arolana.com{path}"})()
        with self.settings(SOCIAL_PUBLISHING_FACEBOOK_REDIRECT_URI=""):
            self.assertEqual(
                callback_uri(request, "facebook"),
                "https://arolana.com/social-publishing/callback/facebook/",
            )


class GunicornAccessLogConfigurationTests(SimpleTestCase):
    def test_web_commands_log_path_without_query_string(self):
        root = Path(__file__).resolve().parents[1]
        commands = [
            (root / "Procfile").read_text(),
            json.loads((root / "railway.web.json").read_text())["deploy"]["startCommand"],
        ]
        for command in commands:
            self.assertIn("%(U)s", command)
            self.assertNotIn("%(q)s", command)
            self.assertNotIn("%(r)s", command)
            self.assertNotIn("RAW_URI", command.upper())
