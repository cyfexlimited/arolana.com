from unittest.mock import Mock, patch

from social_publishing.instagram import (
    InstagramPublishingError,
    create_reel_container,
    get_container_status,
    get_published_media,
    publish_reel,
    publish_reel_container,
    wait_for_container,
)

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


class _FakeInstagramAccount:
    platform = "instagram"
    external_account_id = "123456789"
    access_token_encrypted = "encrypted-test-token"
    is_connected = True


class InstagramPublishingAdapterTests(SimpleTestCase):
    def setUp(self):
        self.account = _FakeInstagramAccount()

    @patch(
        "social_publishing.instagram.decrypt_token",
        return_value="test-access-token",
    )
    @patch("social_publishing.instagram.requests.post")
    def test_create_reel_container(
        self,
        mock_post,
        _mock_decrypt,
    ):
        response = Mock()
        response.ok = True
        response.status_code = 200
        response.json.return_value = {
            "id": "container-123",
        }
        mock_post.return_value = response

        result = create_reel_container(
            self.account,
            video_url="https://example.com/video.mp4",
            caption="Arolana test",
        )

        self.assertEqual(
            result["container_id"],
            "container-123",
        )

        payload = mock_post.call_args.kwargs["data"]

        self.assertEqual(
            payload["media_type"],
            "REELS",
        )
        self.assertEqual(
            payload["video_url"],
            "https://example.com/video.mp4",
        )
        self.assertEqual(
            payload["caption"],
            "Arolana test",
        )

    @patch(
        "social_publishing.instagram.decrypt_token",
        return_value="test-access-token",
    )
    @patch("social_publishing.instagram.requests.get")
    def test_container_status_finished(
        self,
        mock_get,
        _mock_decrypt,
    ):
        response = Mock()
        response.ok = True
        response.status_code = 200
        response.json.return_value = {
            "id": "container-123",
            "status_code": "FINISHED",
        }
        mock_get.return_value = response

        result = get_container_status(
            self.account,
            "container-123",
        )

        self.assertEqual(
            result["status_code"],
            "FINISHED",
        )

    @patch(
        "social_publishing.instagram.get_container_status"
    )
    def test_wait_for_container_returns_when_finished(
        self,
        mock_status,
    ):
        mock_status.side_effect = [
            {
                "container_id": "container-123",
                "status_code": "IN_PROGRESS",
                "response": {},
            },
            {
                "container_id": "container-123",
                "status_code": "FINISHED",
                "response": {},
            },
        ]

        with patch(
            "social_publishing.instagram.time.sleep"
        ):
            result = wait_for_container(
                self.account,
                "container-123",
                timeout=30,
                poll_interval=1,
            )

        self.assertEqual(
            result["status_code"],
            "FINISHED",
        )

    @patch(
        "social_publishing.instagram.decrypt_token",
        return_value="test-access-token",
    )
    @patch("social_publishing.instagram.requests.post")
    def test_publish_reel_container(
        self,
        mock_post,
        _mock_decrypt,
    ):
        response = Mock()
        response.ok = True
        response.status_code = 200
        response.json.return_value = {
            "id": "media-999",
        }
        mock_post.return_value = response

        result = publish_reel_container(
            self.account,
            "container-123",
        )

        self.assertEqual(
            result["media_id"],
            "media-999",
        )

    @patch(
        "social_publishing.instagram.decrypt_token",
        return_value="test-access-token",
    )
    @patch("social_publishing.instagram.requests.get")
    def test_get_published_media(
        self,
        mock_get,
        _mock_decrypt,
    ):
        response = Mock()
        response.ok = True
        response.status_code = 200
        response.json.return_value = {
            "id": "media-999",
            "permalink": "https://www.instagram.com/reel/example/",
            "media_type": "VIDEO",
        }
        mock_get.return_value = response

        result = get_published_media(
            self.account,
            "media-999",
        )

        self.assertEqual(
            result["permalink"],
            "https://www.instagram.com/reel/example/",
        )

    def test_rejects_non_https_video_url(self):
        with patch(
            "social_publishing.instagram.decrypt_token",
            return_value="test-access-token",
        ):
            with self.assertRaises(
                InstagramPublishingError
            ):
                create_reel_container(
                    self.account,
                    video_url="http://example.com/video.mp4",
                )

    @patch(
        "social_publishing.instagram.get_published_media"
    )
    @patch(
        "social_publishing.instagram.publish_reel_container"
    )
    @patch(
        "social_publishing.instagram.wait_for_container"
    )
    @patch(
        "social_publishing.instagram.create_reel_container"
    )
    def test_complete_publish_reel_flow(
        self,
        mock_create,
        mock_wait,
        mock_publish,
        mock_media,
    ):
        mock_create.return_value = {
            "container_id": "container-123",
            "response": {},
        }

        mock_wait.return_value = {
            "container_id": "container-123",
            "status_code": "FINISHED",
            "response": {},
        }

        mock_publish.return_value = {
            "media_id": "media-999",
            "response": {},
        }

        mock_media.return_value = {
            "id": "media-999",
            "permalink": "https://www.instagram.com/reel/example/",
        }

        result = publish_reel(
            self.account,
            video_url="https://example.com/video.mp4",
            caption="Arolana",
        )

        self.assertEqual(
            result["container_id"],
            "container-123",
        )
        self.assertEqual(
            result["media_id"],
            "media-999",
        )
        self.assertEqual(
            result["permalink"],
            "https://www.instagram.com/reel/example/",
        )
