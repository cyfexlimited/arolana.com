from django.test import SimpleTestCase

from .services import normalize_owner_role


class SocialPublishingRoleTests(SimpleTestCase):
    def test_provider_aliases_are_normalized(self):
        self.assertEqual(normalize_owner_role("service_provider"), "provider")
        self.assertEqual(normalize_owner_role("installer"), "provider")

    def test_staff_alias_is_admin(self):
        self.assertEqual(normalize_owner_role("staff"), "admin")

from types import SimpleNamespace

from django.test import override_settings

from .crypto import decrypt_token, encrypt_token
from .services import platform_enabled
from .web_views import make_launch_token


class SocialPublishingPhase2Tests(SimpleTestCase):
    def test_token_encryption_round_trip(self):
        encrypted = encrypt_token("secret-token")
        self.assertNotEqual(encrypted, "secret-token")
        self.assertEqual(decrypt_token(encrypted), "secret-token")

    @override_settings(
        SOCIAL_PUBLISHING_ENABLED=False,
        SOCIAL_PUBLISHING_TIKTOK_ENABLED=True,
    )
    def test_global_feature_flag_keeps_social_platform_dark(self):
        self.assertFalse(platform_enabled("tiktok"))
        self.assertTrue(platform_enabled("youtube"))

    def test_mobile_launch_token_contains_no_oauth_credentials(self):
        token = make_launch_token(
            SimpleNamespace(pk=17),
            "provider",
            "tiktok",
            return_url="arolanastaffmobile://social-accounts",
        )
        self.assertTrue(token)
        self.assertNotIn("secret", token.lower())
