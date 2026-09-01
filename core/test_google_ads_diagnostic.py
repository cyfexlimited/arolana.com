from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from core.management.commands.diagnose_google_ads_accounts import Command


class GoogleAdsDiagnosticSafetyTests(SimpleTestCase):
    @override_settings(
        ADS_GOOGLE_CLIENT_ID="configured-client",
        ADS_GOOGLE_CLIENT_SECRET="configured-secret",
    )
    @patch("core.management.commands.diagnose_google_ads_accounts.credential_encryption_service.decrypt")
    @patch("core.management.commands.diagnose_google_ads_accounts.requests.post")
    def test_oauth_refresh_error_reports_safe_code_and_description_only(
        self, mock_post, mock_decrypt
    ):
        class Response:
            status_code = 400

            @staticmethod
            def json():
                return {
                    "error": "invalid_grant",
                    "error_description": (
                        "Refresh token=refresh-secret was revoked; "
                        "client_secret=configured-secret"
                    ),
                }

        mock_decrypt.return_value = "refresh-secret"
        mock_post.return_value = Response()
        command = Command()
        output = StringIO()
        command.stdout = output
        credential = SimpleNamespace(encrypted_refresh_token=b"encrypted-refresh")

        with self.assertRaisesMessage(CommandError, "In-memory access-token refresh failed."):
            command._refresh_access_token(credential)

        rendered = output.getvalue()
        self.assertIn('"code": "invalid_grant"', rendered)
        self.assertIn("[redacted]", rendered)
        self.assertNotIn("refresh-secret", rendered)
        self.assertNotIn("configured-secret", rendered)

    @override_settings(
        ADS_GOOGLE_CLIENT_ID="configured-client",
        ADS_GOOGLE_CLIENT_SECRET="configured-secret",
    )
    def test_oauth_refresh_configuration_is_boolean_only(self):
        details = Command._oauth_refresh_configuration(
            SimpleNamespace(encrypted_refresh_token=b"encrypted-refresh")
        )

        self.assertTrue(details["oauth_client_id_configured"])
        self.assertTrue(details["oauth_client_secret_configured"])
        self.assertTrue(details["encrypted_refresh_token_present"])
        self.assertEqual(details["token_endpoint"], "https://oauth2.googleapis.com/token")
        self.assertNotIn("configured-client", str(details))
        self.assertNotIn("configured-secret", str(details))
