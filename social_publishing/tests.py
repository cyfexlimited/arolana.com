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

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from .services import normalize_owner_role
from .models import (
    PublicationStatus,
    SocialAccount,
    SocialConnectionStatus,
    SocialPlatform,
    SocialPublication,
)
from .publisher import InstagramPublicationError, publish_uploaded_video_to_instagram
from staff_mobile.models import StaffMobileToken


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
            with self.assertRaises(InstagramPublishingError):
                create_reel_container(
                    self.account,
                    video_url="http://example.com/video.mp4",
                )

    @patch("social_publishing.instagram.get_published_media")
    @patch("social_publishing.instagram.publish_reel_container")
    @patch("social_publishing.instagram.wait_for_container")
    @patch("social_publishing.instagram.create_reel_container")
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

        self.assertEqual(result["container_id"], "container-123")
        self.assertEqual(result["media_id"], "media-999")
        self.assertEqual(
            result["permalink"],
            "https://www.instagram.com/reel/example/",
        )


@override_settings(
    SOCIAL_PUBLISHING_ENABLED=True,
    SOCIAL_PUBLISHING_INSTAGRAM_ENABLED=True,
)
class InstagramPublicationOrchestrationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="instagram-publisher",
            email="instagram-publisher@example.com",
            password="test-password",
            is_staff=True,
        )
        self.upload = SimpleUploadedFile(
            "reel.mp4",
            b"temporary-video",
            content_type="video/mp4",
        )

    def _account(self, role="vendor", status=SocialConnectionStatus.CONNECTED):
        return SocialAccount.objects.create(
            user=self.user,
            owner_role=role,
            platform=SocialPlatform.INSTAGRAM,
            status=status,
            external_account_id=f"instagram-{role}",
            access_token_encrypted="encrypted-token",
        )

    def _publish(self, role="vendor"):
        return publish_uploaded_video_to_instagram(
            user=self.user,
            owner_role=role,
            content_object=self.user,
            uploaded_file=self.upload,
            caption="Arolana reel",
            share_to_feed=True,
        )

    @patch("social_publishing.publisher.cleanup_video_lease")
    @patch("social_publishing.publisher.publish_reel")
    @patch("social_publishing.publisher.get_video_delivery_url", return_value="https://media.example/reel.mp4")
    @patch("social_publishing.publisher.stage_video_for_social", return_value=SimpleNamespace())
    @patch("social_publishing.publisher.social_publishing_access")
    def test_vendor_provider_and_admin_roles_use_exact_role_account(
        self, mock_access, _mock_stage, _mock_url, mock_publish, _mock_cleanup
    ):
        mock_access.return_value = SimpleNamespace(allowed=True, reason="")
        mock_publish.return_value = {
            "container_id": "container-1",
            "media_id": "media-1",
            "permalink": "https://www.instagram.com/reel/example/",
        }

        for role in ("vendor", "provider", "admin"):
            with self.subTest(role=role):
                account = self._account(role)
                publication = self._publish(role)
                self.assertEqual(publication.social_account, account)
                self.assertEqual(publication.owner_role, role)
                publication.delete()
                account.delete()

    @patch("social_publishing.publisher.social_publishing_access")
    def test_disconnected_instagram_account_is_rejected(self, mock_access):
        mock_access.return_value = SimpleNamespace(allowed=True, reason="")
        self._account(status=SocialConnectionStatus.REVOKED)

        with self.assertRaises(InstagramPublicationError) as caught:
            self._publish()

        self.assertEqual(caught.exception.code, "instagram_not_connected")
        self.assertFalse(SocialPublication.objects.exists())

    @patch("social_publishing.publisher.stage_video_for_social")
    @patch("social_publishing.publisher.social_publishing_access")
    def test_already_published_content_is_not_published_again(self, mock_access, mock_stage):
        mock_access.return_value = SimpleNamespace(allowed=True, reason="")
        account = self._account()
        SocialPublication.objects.create(
            owner_user=self.user,
            owner_role="vendor",
            social_account=account,
            platform=SocialPlatform.INSTAGRAM,
            content_object=self.user,
            status=PublicationStatus.PUBLISHED,
            attempt_count=1,
            external_id="existing-media",
        )

        with self.assertRaises(InstagramPublicationError) as caught:
            self._publish()

        self.assertEqual(caught.exception.code, "already_published")
        mock_stage.assert_not_called()

    @patch("social_publishing.publisher.cleanup_video_lease")
    @patch("social_publishing.publisher.publish_reel")
    @patch("social_publishing.publisher.get_video_delivery_url", return_value="https://media.example/reel.mp4")
    @patch("social_publishing.publisher.stage_video_for_social", return_value=SimpleNamespace())
    @patch("social_publishing.publisher.social_publishing_access")
    def test_successful_publish_is_persisted(
        self, mock_access, _mock_stage, _mock_url, mock_publish, mock_cleanup
    ):
        mock_access.return_value = SimpleNamespace(allowed=True, reason="")
        self._account()
        mock_publish.return_value = {
            "container_id": "container-123",
            "media_id": "media-999",
            "permalink": "https://www.instagram.com/reel/example/",
        }

        publication = self._publish()

        self.assertEqual(publication.status, PublicationStatus.PUBLISHED)
        self.assertEqual(publication.attempt_count, 1)
        self.assertEqual(publication.external_id, "media-999")
        self.assertEqual(publication.external_url, "https://www.instagram.com/reel/example/")
        mock_publish.assert_called_once_with(
            publication.social_account,
            video_url="https://media.example/reel.mp4",
            caption="Arolana reel",
            share_to_feed=True,
        )
        mock_cleanup.assert_called_once()

    @patch("social_publishing.publisher.cleanup_video_lease")
    @patch("social_publishing.publisher.publish_reel")
    @patch("social_publishing.publisher.get_video_delivery_url", return_value="https://media.example/reel.mp4")
    @patch("social_publishing.publisher.stage_video_for_social", return_value=SimpleNamespace())
    @patch("social_publishing.publisher.social_publishing_access")
    def test_failed_publish_is_safe_and_still_cleans_up(
        self, mock_access, _mock_stage, _mock_url, mock_publish, mock_cleanup
    ):
        mock_access.return_value = SimpleNamespace(allowed=True, reason="")
        self._account()
        mock_publish.side_effect = InstagramPublishingError(
            "Provider failed access_token=top-secret",
            error_code="OAuthException",
        )

        with self.assertRaises(InstagramPublicationError) as caught:
            self._publish()

        publication = SocialPublication.objects.get()
        self.assertEqual(publication.status, PublicationStatus.FAILED)
        self.assertEqual(publication.attempt_count, 1)
        self.assertEqual(publication.error_code, "OAuthException")
        self.assertNotIn("top-secret", publication.error_message)
        self.assertNotIn("top-secret", str(caught.exception))
        mock_cleanup.assert_called_once()

    @patch("social_publishing.publisher.cleanup_video_lease")
    @patch("social_publishing.publisher.publish_reel")
    @patch("social_publishing.publisher.get_video_delivery_url", return_value="http://media.example/reel.mp4")
    @patch("social_publishing.publisher.stage_video_for_social", return_value=SimpleNamespace())
    @patch("social_publishing.publisher.social_publishing_access")
    def test_temporary_delivery_url_must_be_https(
        self, mock_access, _mock_stage, _mock_url, mock_publish, mock_cleanup
    ):
        mock_access.return_value = SimpleNamespace(allowed=True, reason="")
        self._account()

        with self.assertRaises(InstagramPublicationError) as caught:
            self._publish()

        self.assertEqual(caught.exception.code, "https_video_url_required")
        publication = SocialPublication.objects.get()
        self.assertEqual(publication.status, PublicationStatus.FAILED)
        mock_publish.assert_not_called()
        mock_cleanup.assert_called_once()


@override_settings(
    SOCIAL_PUBLISHING_ENABLED=True,
    SOCIAL_PUBLISHING_INSTAGRAM_ENABLED=True,
)
class InstagramVideoPublicationAPITests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="instagram-api-user",
            email="instagram-api@example.com",
            password="test-password",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.url = reverse("social_publishing:instagram_video_publish")

    def _video(self, content_type="video/mp4"):
        return SimpleUploadedFile("reel.mp4", b"video-bytes", content_type=content_type)

    def _payload(self, role="vendor"):
        return {
            "role": role,
            "content_type": "products.productvideo",
            "object_id": 42,
            "video": self._video(),
            "caption": "Arolana API reel",
            "share_to_feed": "true",
        }

    def _publication(self, **overrides):
        values = {
            "pk": 91,
            "status": PublicationStatus.PUBLISHED,
            "external_id": "instagram-media-91",
            "external_url": "https://www.instagram.com/reel/example/",
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def _successful_role_request(self, role):
        publication = self._publication()
        with patch("social_publishing.api_views._role_available", return_value=True), patch(
            "social_publishing.api_views._resolve_publication_content",
            return_value=self.user,
        ), patch(
            "social_publishing.api_views.publish_uploaded_video_to_instagram",
            return_value=publication,
        ) as mock_publish:
            response = self.client.post(self.url, self._payload(role), format="multipart")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(mock_publish.call_args.kwargs["owner_role"], role)
        return response

    def test_vendor_can_publish_through_shared_endpoint(self):
        self._successful_role_request("vendor")

    def test_provider_can_publish_through_shared_endpoint(self):
        self._successful_role_request("provider")

    def test_admin_can_publish_through_shared_endpoint(self):
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        self._successful_role_request("admin")

    def test_unauthorized_role_is_rejected(self):
        with patch("social_publishing.api_views.publish_uploaded_video_to_instagram") as mock_publish:
            response = self.client.post(self.url, self._payload("admin"), format="multipart")
        self.assertEqual(response.status_code, 403)
        mock_publish.assert_not_called()

    def test_missing_and_invalid_video_are_rejected(self):
        missing = self._payload()
        missing.pop("video")
        response = self.client.post(self.url, missing, format="multipart")
        self.assertEqual(response.status_code, 400)
        self.assertIn("video", response.data)

        missing_mime = self._payload()
        missing_mime["video"] = self._video("")
        response = self.client.post(self.url, missing_mime, format="multipart")
        self.assertEqual(response.status_code, 400)
        self.assertIn("video", response.data)

        invalid = self._payload()
        invalid["video"] = self._video("image/png")
        response = self.client.post(self.url, invalid, format="multipart")
        self.assertEqual(response.status_code, 400)
        self.assertIn("video", response.data)

    def test_duplicate_publish_returns_safe_conflict(self):
        publication = self._publication()
        error = InstagramPublicationError(
            "This content has already been published to Instagram.",
            code="already_published",
            publication=publication,
        )
        with patch("social_publishing.api_views._role_available", return_value=True), patch(
            "social_publishing.api_views._resolve_publication_content", return_value=self.user
        ), patch(
            "social_publishing.api_views.publish_uploaded_video_to_instagram",
            side_effect=error,
        ):
            response = self.client.post(self.url, self._payload(), format="multipart")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["error_code"], "already_published")
        self.assertEqual(response.data["publication_id"], 91)

    def test_disconnected_instagram_returns_safe_conflict(self):
        error = InstagramPublicationError(
            "A connected Instagram account is required.",
            code="instagram_not_connected",
        )
        with patch("social_publishing.api_views._role_available", return_value=True), patch(
            "social_publishing.api_views._resolve_publication_content", return_value=self.user
        ), patch(
            "social_publishing.api_views.publish_uploaded_video_to_instagram",
            side_effect=error,
        ):
            response = self.client.post(self.url, self._payload(), format="multipart")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["error_code"], "instagram_not_connected")
        self.assertNotIn("access_token", str(response.data).lower())

    def test_unknown_provider_error_cannot_leak_credentials(self):
        error = InstagramPublicationError(
            "Provider failed access_token=api-secret refresh_token=refresh-secret",
            code="api-secret",
        )
        with patch("social_publishing.api_views._role_available", return_value=True), patch(
            "social_publishing.api_views._resolve_publication_content", return_value=self.user
        ), patch(
            "social_publishing.api_views.publish_uploaded_video_to_instagram",
            side_effect=error,
        ):
            response = self.client.post(self.url, self._payload(), format="multipart")

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.data["error_code"], "instagram_publish_failed")
        self.assertEqual(response.data["detail"], "Instagram publishing failed.")
        self.assertNotIn("api-secret", str(response.data))
        self.assertNotIn("refresh-secret", str(response.data))

    def test_success_response_contains_only_safe_publication_fields(self):
        response = self._successful_role_request("vendor")
        self.assertEqual(
            set(response.data),
            {
                "publication_id",
                "status",
                "instagram_media_id",
                "instagram_permalink",
            },
        )
        self.assertEqual(response.data["instagram_media_id"], "instagram-media-91")

    def test_mobile_bearer_session_is_bound_to_issued_role(self):
        self.client.force_authenticate(user=None)
        session = StaffMobileToken.issue(role="provider", user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {session.token}")
        payload = self._payload("vendor")

        with patch("social_publishing.api_views._role_available", return_value=True), patch(
            "social_publishing.api_views.publish_uploaded_video_to_instagram"
        ) as mock_publish:
            response = self.client.post(self.url, payload, format="multipart")

        self.assertEqual(response.status_code, 403)
        mock_publish.assert_not_called()
