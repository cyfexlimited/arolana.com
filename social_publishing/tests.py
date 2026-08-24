from unittest.mock import Mock, patch
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

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
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from .services import normalize_owner_role
from .models import (
    PublicationStatus,
    SocialAccount,
    SocialConnectionStatus,
    SocialPlatform,
    SocialPublication,
    TemporaryVideoLease,
)
from .publisher import (
    InstagramPublicationError,
    _content_is_approved_for_distribution,
    _prepare_publication,
    continue_deferred_instagram_publication,
    cleanup_orphaned_pending_instagram_publications,
    release_pending_instagram_publications,
    publish_uploaded_video_to_instagram,
)
from .oauth import (
    INSTAGRAM_LONG_LIVED_TOKEN_KIND,
    INSTAGRAM_TOKEN_ISSUED_AT_KEY,
    INSTAGRAM_TOKEN_KIND_KEY,
    InstagramTokenLifecycleError,
    exchange_instagram_long_lived_token,
    refresh_instagram_account_if_needed,
    refresh_instagram_long_lived_token,
)
from staff_mobile.models import StaffMobileToken


class SocialPublishingRoleTests(SimpleTestCase):
    def test_provider_aliases_are_normalized(self):
        self.assertEqual(normalize_owner_role("service_provider"), "provider")
        self.assertEqual(normalize_owner_role("installer"), "provider")

    def test_staff_alias_is_admin(self):
        self.assertEqual(normalize_owner_role("staff"), "admin")

    def test_video_moderation_blocks_external_distribution_until_approved(self):
        product_video_type = SimpleNamespace(app_label="products", model="productvideo")
        provider_media_type = SimpleNamespace(app_label="installers", model="serviceprojectmedia")

        self.assertFalse(
            _content_is_approved_for_distribution(
                product_video_type,
                SimpleNamespace(moderation_status="pending"),
            )
        )
        self.assertTrue(
            _content_is_approved_for_distribution(
                product_video_type,
                SimpleNamespace(moderation_status="approved"),
            )
        )
        self.assertFalse(
            _content_is_approved_for_distribution(
                provider_media_type,
                SimpleNamespace(approval_status="requires_changes"),
            )
        )
        self.assertTrue(
            _content_is_approved_for_distribution(
                provider_media_type,
                SimpleNamespace(approval_status="approved"),
            )
        )

    def test_admin_surfaces_hide_tokens_and_attach_publication_history(self):
        from django.contrib import admin
        from installers.models import ServiceProjectMedia
        from products.models import ProductVideo

        from .admin_inlines import SocialPublicationInline

        account_admin = admin.site._registry[SocialAccount]
        self.assertIn("access_token_encrypted", account_admin.exclude)
        self.assertIn("refresh_token_encrypted", account_admin.exclude)
        self.assertIn(SocialPublicationInline, admin.site._registry[ProductVideo].inlines)
        self.assertIn(SocialPublicationInline, admin.site._registry[ServiceProjectMedia].inlines)

    def test_provider_web_connection_and_retry_states_are_explicit(self):
        template = Path(settings.BASE_DIR, "templates/installers/project_media.html").read_text()
        self.assertIn('let instagramAccountState="loading"', template)
        self.assertIn('connectButton.style.display=canConnect?"inline-flex":"none"', template)
        self.assertIn('instagramAccountState==="connected"', template)
        self.assertIn('instagramAccountState=needsReconnect?"expired":"disconnected"', template)
        self.assertIn("Pending Arolana approval", template)
        self.assertIn("Retry Instagram", template)
        self.assertIn("uploadedProjectMediaId", template)

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


@override_settings(SOCIAL_PUBLISHING_INSTAGRAM_APP_SECRET="instagram-app-secret")
class InstagramOAuthTokenExchangeTests(SimpleTestCase):
    @patch("social_publishing.oauth.requests.get")
    def test_short_lived_token_is_exchanged_for_long_lived_token(self, mock_get):
        response = Mock(ok=True, status_code=200)
        response.json.return_value = {
            "access_token": "long-lived-token",
            "token_type": "bearer",
            "expires_in": 5184000,
        }
        mock_get.return_value = response

        result = exchange_instagram_long_lived_token("short-lived-token")

        self.assertEqual(result["access_token"], "long-lived-token")
        params = mock_get.call_args.kwargs["params"]
        self.assertEqual(params["grant_type"], "ig_exchange_token")
        self.assertEqual(params["access_token"], "short-lived-token")

    @patch("social_publishing.oauth.requests.get")
    def test_long_lived_token_refresh_uses_instagram_refresh_endpoint(self, mock_get):
        response = Mock(ok=True, status_code=200)
        response.json.return_value = {
            "access_token": "refreshed-token",
            "token_type": "bearer",
            "expires_in": 5184000,
        }
        mock_get.return_value = response

        result = refresh_instagram_long_lived_token("current-token")

        self.assertEqual(result["access_token"], "refreshed-token")
        self.assertIn("refresh_access_token", mock_get.call_args.args[0])
        self.assertEqual(
            mock_get.call_args.kwargs["params"]["grant_type"],
            "ig_refresh_token",
        )


class InstagramOAuthTokenLifecycleTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="instagram-oauth-admin",
            email="instagram-oauth-admin@example.com",
            password="test-password",
            is_staff=True,
        )

    @patch("social_publishing.web_views.exchange_instagram_long_lived_token")
    @patch("social_publishing.web_views.exchange_code")
    def test_callback_persists_long_lived_token_and_expiry(
        self, mock_exchange_code, mock_long_lived
    ):
        mock_exchange_code.return_value = {
            "access_token": "short-lived-token",
            "user_id": "instagram-user-1",
        }
        mock_long_lived.return_value = {
            "access_token": "long-lived-token",
            "expires_in": 5184000,
            "token_type": "bearer",
        }
        self.client.force_login(self.user)
        session = self.client.session
        session["social_oauth"] = {
            "state": "safe-state",
            "user_id": self.user.pk,
            "role": "admin",
            "platform": "instagram",
            "return_url": "",
        }
        session.save()

        response = self.client.get(
            reverse(
                "social_publishing_web:oauth_callback",
                kwargs={"platform": "instagram"},
            ),
            {"state": "safe-state", "code": "authorization-code"},
        )

        self.assertEqual(response.status_code, 302)
        account = SocialAccount.objects.get(user=self.user, owner_role="admin")
        self.assertEqual(decrypt_token(account.access_token_encrypted), "long-lived-token")
        self.assertEqual(account.external_account_id, "instagram-user-1")
        self.assertGreater(account.token_expires_at, timezone.now() + timedelta(days=59))
        self.assertEqual(
            account.platform_metadata[INSTAGRAM_TOKEN_KIND_KEY],
            INSTAGRAM_LONG_LIVED_TOKEN_KIND,
        )
        mock_long_lived.assert_called_once_with("short-lived-token")

    @patch("social_publishing.oauth.refresh_instagram_long_lived_token")
    def test_approaching_expiry_refreshes_and_persists_token(self, mock_refresh):
        account = SocialAccount.objects.create(
            user=self.user,
            owner_role="admin",
            platform=SocialPlatform.INSTAGRAM,
            status=SocialConnectionStatus.CONNECTED,
            access_token_encrypted=encrypt_token("current-long-lived-token"),
            token_expires_at=timezone.now() + timedelta(days=1),
            platform_metadata={
                INSTAGRAM_TOKEN_KIND_KEY: INSTAGRAM_LONG_LIVED_TOKEN_KIND,
                INSTAGRAM_TOKEN_ISSUED_AT_KEY: (
                    timezone.now() - timedelta(days=30)
                ).isoformat(),
            },
        )
        mock_refresh.return_value = {
            "access_token": "new-long-lived-token",
            "expires_in": 5184000,
        }

        refresh_instagram_account_if_needed(account)

        account.refresh_from_db()
        refresh_instagram_account_if_needed(account)
        self.assertEqual(decrypt_token(account.access_token_encrypted), "new-long-lived-token")
        self.assertGreater(account.token_expires_at, timezone.now() + timedelta(days=59))
        self.assertEqual(account.status, SocialConnectionStatus.CONNECTED)
        mock_refresh.assert_called_once_with("current-long-lived-token")

    @patch("social_publishing.oauth.refresh_instagram_long_lived_token")
    def test_refresh_failure_is_safe_and_requires_attention(self, mock_refresh):
        account = SocialAccount.objects.create(
            user=self.user,
            owner_role="admin",
            platform=SocialPlatform.INSTAGRAM,
            status=SocialConnectionStatus.CONNECTED,
            access_token_encrypted=encrypt_token("current-secret-token"),
            token_expires_at=timezone.now() + timedelta(days=1),
            platform_metadata={
                INSTAGRAM_TOKEN_KIND_KEY: INSTAGRAM_LONG_LIVED_TOKEN_KIND,
                INSTAGRAM_TOKEN_ISSUED_AT_KEY: (
                    timezone.now() - timedelta(days=30)
                ).isoformat(),
            },
        )
        mock_refresh.side_effect = InstagramTokenLifecycleError(
            "Instagram long-lived token refresh failed (400)."
        )

        with self.assertRaises(InstagramTokenLifecycleError) as caught:
            refresh_instagram_account_if_needed(account)

        account.refresh_from_db()
        self.assertEqual(account.status, SocialConnectionStatus.ERROR)
        self.assertNotIn("current-secret-token", str(caught.exception))
        self.assertNotIn("current-secret-token", account.last_error)

    @patch("social_publishing.oauth.refresh_instagram_long_lived_token")
    def test_unverified_token_is_never_sent_to_refresh_endpoint(self, mock_refresh):
        account = SocialAccount.objects.create(
            user=self.user,
            owner_role="admin",
            platform=SocialPlatform.INSTAGRAM,
            status=SocialConnectionStatus.CONNECTED,
            access_token_encrypted=encrypt_token("unverified-token"),
            token_expires_at=timezone.now() + timedelta(days=1),
            platform_metadata={},
        )

        with self.assertRaises(InstagramTokenLifecycleError):
            refresh_instagram_account_if_needed(account)

        account.refresh_from_db()
        self.assertEqual(account.status, SocialConnectionStatus.ERROR)
        mock_refresh.assert_not_called()

    @patch("social_publishing.oauth.refresh_instagram_long_lived_token")
    def test_long_lived_token_younger_than_24_hours_is_not_refreshed(self, mock_refresh):
        account = SocialAccount.objects.create(
            user=self.user,
            owner_role="admin",
            platform=SocialPlatform.INSTAGRAM,
            status=SocialConnectionStatus.CONNECTED,
            access_token_encrypted=encrypt_token("young-long-lived-token"),
            token_expires_at=timezone.now() + timedelta(days=1),
            platform_metadata={
                INSTAGRAM_TOKEN_KIND_KEY: INSTAGRAM_LONG_LIVED_TOKEN_KIND,
                INSTAGRAM_TOKEN_ISSUED_AT_KEY: (
                    timezone.now() - timedelta(hours=12)
                ).isoformat(),
            },
        )

        result = refresh_instagram_account_if_needed(account)

        self.assertEqual(result.pk, account.pk)
        self.assertEqual(result.status, SocialConnectionStatus.CONNECTED)
        mock_refresh.assert_not_called()


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

    def _lease(self, role="vendor"):
        return TemporaryVideoLease.objects.create(
            owner_user=self.user,
            owner_role=role,
            storage_key=f"social-publishing/test/{role}.mp4",
            original_filename="reel.mp4",
            expires_at=timezone.now() + timedelta(days=1),
        )

    def _pending_product_publication(self, suffix):
        from products.models import Category, Product, ProductVideo

        vendor = get_user_model().objects.create_user(
            username=f"release-vendor-{suffix}", email=f"release-{suffix}@example.com"
        )
        category = Category.objects.create(
            name=f"Release {suffix}", slug=f"release-{suffix}", is_active=True
        )
        product = Product.objects.create(
            vendor=vendor, category=category, sku=f"RELEASE-{suffix}",
            name=f"Release product {suffix}", slug=f"release-product-{suffix}",
            description="Pending", price="100.00", stock_quantity=1,
            approval_status="pending", is_active=False,
        )
        video = ProductVideo.objects.create(
            product=product, title="Hosted video", source="youtube",
            youtube_video_id=f"release-{suffix}", moderation_status="pending", is_active=True,
        )
        account = SocialAccount.objects.create(
            user=vendor, owner_role="vendor", platform=SocialPlatform.INSTAGRAM,
            status=SocialConnectionStatus.CONNECTED,
            external_account_id=f"instagram-{suffix}", access_token_encrypted="encrypted",
        )
        lease = TemporaryVideoLease.objects.create(
            owner_user=vendor, owner_role="vendor", storage_key=f"release/{suffix}.mp4",
            original_filename="source.mp4", expires_at=timezone.now() + timedelta(days=1),
        )
        publication = SocialPublication.objects.create(
            owner_user=vendor, owner_role="vendor", social_account=account,
            platform=SocialPlatform.INSTAGRAM, content_object=video,
            status=PublicationStatus.PENDING, deferred_video_lease=lease,
            request_metadata={"caption": "Deferred", "share_to_feed": True},
        )
        return product, video, publication, account

    @patch("social_publishing.publisher.cleanup_video_lease")
    @patch("social_publishing.publisher.publish_reel")
    @patch("social_publishing.publisher.get_video_delivery_url", return_value="https://media.example/reel.mp4")
    @patch("social_publishing.publisher.stage_video_for_social")
    @patch("social_publishing.publisher.social_publishing_access")
    def test_vendor_provider_and_admin_roles_use_exact_role_account(
        self, mock_access, _mock_stage, _mock_url, mock_publish, _mock_cleanup
    ):
        mock_access.return_value = SimpleNamespace(allowed=True, reason="")
        _mock_stage.side_effect = lambda **kwargs: self._lease(kwargs["owner_role"])
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
        publication = SocialPublication.objects.get()
        self.assertEqual(publication.status, PublicationStatus.FAILED)
        self.assertEqual(publication.error_code, "instagram_not_connected")
        self.assertEqual(publication.attempt_count, 1)

    def test_audit_records_support_vendor_product_video_and_provider_project_media(self):
        from django.contrib.contenttypes.models import ContentType
        from installers.models import ServiceProjectMedia
        from products.models import ProductVideo

        for role, model, object_id in (
            ("vendor", ProductVideo, 7001),
            ("provider", ServiceProjectMedia, 7002),
        ):
            with self.subTest(role=role, model=model.__name__):
                publication = _prepare_publication(
                    user=self.user,
                    owner_role=role,
                    account=None,
                    content_type=ContentType.objects.get_for_model(model),
                    object_id=object_id,
                    share_to_feed=True,
                )
                self.assertEqual(publication.owner_role, role)
                self.assertEqual(publication.status, PublicationStatus.UPLOADING)
                self.assertEqual(publication.attempt_count, 1)

    @patch("social_publishing.publisher.stage_video_for_social")
    @patch("social_publishing.publisher._content_is_approved_for_distribution", return_value=False)
    @patch("social_publishing.publisher.social_publishing_access")
    def test_pending_moderation_records_request_without_external_publish(
        self, mock_access, _mock_approval, mock_stage
    ):
        mock_access.return_value = SimpleNamespace(allowed=True, reason="")
        self._account()
        mock_stage.return_value = self._lease()
        publication = self._publish()
        self.assertEqual(publication.status, PublicationStatus.PENDING)
        self.assertEqual(publication.attempt_count, 1)
        self.assertTrue(publication.request_metadata["awaiting_moderation"])
        self.assertEqual(publication.deferred_video_lease, mock_stage.return_value)
        mock_stage.assert_called_once()

    @patch("social_publishing.publisher.cleanup_video_lease")
    @patch("social_publishing.publisher.publish_reel")
    @patch("social_publishing.publisher.get_video_delivery_url", return_value="https://media.example/reel.mp4")
    @patch("social_publishing.publisher._content_is_approved_for_distribution", return_value=True)
    @patch("social_publishing.publisher.social_publishing_access")
    def test_approval_continues_pending_publication_without_new_upload(
        self, mock_access, _mock_approved, _mock_url, mock_publish, mock_cleanup
    ):
        mock_access.return_value = SimpleNamespace(allowed=True, reason="")
        account = self._account()
        publication = SocialPublication.objects.create(
            owner_user=self.user,
            owner_role="vendor",
            social_account=account,
            platform=SocialPlatform.INSTAGRAM,
            content_object=self.user,
            status=PublicationStatus.PENDING,
            attempt_count=1,
            deferred_video_lease=self._lease(),
            request_metadata={"caption": "Deferred", "share_to_feed": True, "awaiting_moderation": True},
        )
        mock_publish.return_value = {"media_id": "released-1", "permalink": "https://www.instagram.com/reel/released/"}

        result = continue_deferred_instagram_publication(publication)

        self.assertEqual(result.status, PublicationStatus.PUBLISHED)
        self.assertEqual(result.attempt_count, 2)
        mock_publish.assert_called_once()
        mock_cleanup.assert_called_once()

    @patch.object(SocialPublication.objects, "select_for_update")
    def test_deferred_release_locks_publication_without_nullable_related_joins(
        self, mock_select_for_update
    ):
        publication = Mock(pk=91, status=PublicationStatus.PUBLISHED)
        mock_select_for_update.return_value.get.return_value = publication

        result = continue_deferred_instagram_publication(publication)

        self.assertIs(result, publication)
        mock_select_for_update.assert_called_once_with()
        mock_select_for_update.return_value.get.assert_called_once_with(pk=91)
        mock_select_for_update.return_value.select_related.assert_not_called()

    @patch("social_publishing.publisher.continue_deferred_instagram_publication")
    def test_automatic_failure_is_recorded_without_raising_into_approval(self, mock_continue):
        account = self._account()
        publication = SocialPublication.objects.create(
            owner_user=self.user,
            owner_role="vendor",
            social_account=account,
            platform=SocialPlatform.INSTAGRAM,
            content_object=self.user,
            status=PublicationStatus.PENDING,
            deferred_video_lease=self._lease(),
        )
        mock_continue.side_effect = InstagramPublicationError("safe failure", publication=publication)

        results = release_pending_instagram_publications([self.user])

        self.assertEqual([item.pk for item in results], [publication.pk])
        publication.refresh_from_db()
        self.assertEqual(publication.status, PublicationStatus.FAILED)
        self.assertEqual(publication.error_code, "instagram_publish_failed")

    @patch(
        "social_publishing.publisher.release_pending_instagram_publications",
        side_effect=RuntimeError("provider unavailable"),
    )
    def test_post_commit_release_exception_does_not_escape_product_approval(
        self, _mock_release
    ):
        from social_publishing.moderation import approve_product_package

        product, video, _publication, _account = self._pending_product_publication(
            "callback-failure"
        )
        reviewer = get_user_model().objects.create_user(
            username="callback-reviewer",
            email="callback-reviewer@example.com",
            is_staff=True,
        )

        with self.captureOnCommitCallbacks(execute=True):
            approve_product_package(product, reviewer)

        product.refresh_from_db()
        video.refresh_from_db()
        self.assertEqual(product.approval_status, "approved")
        self.assertEqual(video.moderation_status, "approved")


    @patch("social_publishing.publisher.release_pending_instagram_publications")
    def test_vendor_product_approval_approves_video_and_schedules_release(self, mock_release):
        from products.models import Category, Product, ProductVideo
        from social_publishing.moderation import approve_product_package

        vendor = get_user_model().objects.create_user(
            username="approval-vendor", email="approval-vendor@example.com"
        )
        reviewer = get_user_model().objects.create_user(
            username="approval-reviewer", email="approval-reviewer@example.com", is_staff=True
        )
        category = Category.objects.create(name="Approval Test", slug="approval-test", is_active=True)
        product = Product.objects.create(
            vendor=vendor, category=category, sku="APPROVAL-1", name="Approval product",
            slug="approval-product", description="Pending", price="100.00", stock_quantity=1,
            approval_status="pending", is_active=False,
        )
        video = ProductVideo.objects.create(
            product=product, title="Hosted video", source="youtube",
            youtube_video_id="approval-video", moderation_status="pending", is_active=True,
        )

        with self.captureOnCommitCallbacks(execute=True):
            approve_product_package(product, reviewer)

        product.refresh_from_db()
        video.refresh_from_db()
        self.assertEqual(product.approval_status, "approved")
        self.assertEqual(video.moderation_status, "approved")
        mock_release.assert_called_once()

    @patch("social_publishing.publisher.cleanup_video_lease")
    @patch("social_publishing.publisher.publish_reel")
    @patch("social_publishing.publisher.get_video_delivery_url", return_value="https://media.example/source.mp4")
    @patch("social_publishing.publisher._connected_instagram_account")
    @patch("social_publishing.publisher.social_publishing_access")
    def test_product_approval_releases_exact_pending_video_publication(
        self, mock_access, mock_account, _mock_url, mock_publish, _mock_cleanup
    ):
        from social_publishing.moderation import approve_product_package

        product, video, publication, account = self._pending_product_publication("package")
        reviewer = get_user_model().objects.create_user(
            username="package-reviewer", email="package-reviewer@example.com", is_staff=True
        )
        mock_access.return_value = SimpleNamespace(allowed=True, reason="")
        mock_account.return_value = account
        mock_publish.return_value = {
            "media_id": "released-package",
            "permalink": "https://www.instagram.com/reel/released-package/",
        }

        with self.captureOnCommitCallbacks(execute=True):
            approve_product_package(product, reviewer)

        video.refresh_from_db()
        publication.refresh_from_db()
        self.assertEqual(video.moderation_status, "approved")
        self.assertEqual(publication.status, PublicationStatus.PUBLISHED)
        self.assertEqual(publication.external_id, "released-package")

    @patch("social_publishing.publisher.cleanup_video_lease")
    @patch("social_publishing.publisher.publish_reel")
    @patch("social_publishing.publisher.get_video_delivery_url", return_value="https://media.example/source.mp4")
    @patch("social_publishing.publisher._connected_instagram_account")
    @patch("social_publishing.publisher.social_publishing_access")
    def test_direct_video_approval_releases_exact_pending_publication(
        self, mock_access, mock_account, _mock_url, mock_publish, _mock_cleanup
    ):
        from social_publishing.moderation import approve_product_video

        _product, video, publication, account = self._pending_product_publication("direct")
        reviewer = get_user_model().objects.create_user(
            username="direct-reviewer", email="direct-reviewer@example.com", is_staff=True
        )
        mock_access.return_value = SimpleNamespace(allowed=True, reason="")
        mock_account.return_value = account
        mock_publish.return_value = {
            "media_id": "released-direct",
            "permalink": "https://www.instagram.com/reel/released-direct/",
        }

        with self.captureOnCommitCallbacks(execute=True):
            approve_product_video(video, reviewer)

        publication.refresh_from_db()
        self.assertEqual(publication.status, PublicationStatus.PUBLISHED)
        self.assertEqual(publication.external_id, "released-direct")

    @patch("social_publishing.publisher.cleanup_video_lease")
    def test_orphaned_pending_publication_is_failed_and_cleaned(self, mock_cleanup):
        _product, video, publication, _account = self._pending_product_publication("orphan")
        video.delete()

        cleaned = cleanup_orphaned_pending_instagram_publications()

        publication.refresh_from_db()
        self.assertEqual(cleaned, 1)
        self.assertEqual(publication.status, PublicationStatus.FAILED)
        self.assertEqual(publication.error_code, "content_deleted")
        mock_cleanup.assert_called_once()

    @patch("social_publishing.moderation.approve_product_package")
    def test_product_admin_change_form_routes_approval_through_release_service(
        self, mock_approve
    ):
        from django.contrib import admin
        from products.models import Product

        product, video, _publication, _account = self._pending_product_publication("admin-form")
        product.approval_status = "approved"
        product.save(update_fields=["approval_status", "updated_at"])
        video.moderation_status = "approved"
        video.save(update_fields=["moderation_status", "updated_at"])
        reviewer = get_user_model().objects.create_user(
            username="admin-form-reviewer", email="admin-form@example.com", is_staff=True
        )
        form = SimpleNamespace(instance=product, save_m2m=Mock())

        admin.site._registry[Product].save_related(
            SimpleNamespace(user=reviewer), form, [], True
        )

        mock_approve.assert_called_once_with(product, reviewer)

    @patch("social_publishing.moderation.approve_product_video")
    def test_product_video_admin_change_form_routes_approval_through_release_service(
        self, mock_approve
    ):
        from django.contrib import admin
        from products.models import ProductVideo

        _product, video, _publication, _account = self._pending_product_publication("video-form")
        video.moderation_status = "approved"
        reviewer = get_user_model().objects.create_user(
            username="video-form-reviewer", email="video-form@example.com", is_staff=True
        )

        admin.site._registry[ProductVideo].save_model(
            SimpleNamespace(user=reviewer), video, SimpleNamespace(), True
        )

        mock_approve.assert_called_once_with(video, reviewer, video.moderation_note)

    @patch("social_publishing.publisher.release_pending_instagram_publications")
    def test_provider_project_approval_approves_media_and_schedules_release(self, mock_release):
        from datetime import date
        from installers.models import ServiceCategory, ServicePortfolio, ServiceProjectMedia, ServiceProviderProfile
        from installers.project_services import moderate_project

        provider_user = get_user_model().objects.create_user(
            username="approval-provider", email="approval-provider@example.com"
        )
        reviewer = get_user_model().objects.create_user(
            username="project-reviewer", email="project-reviewer@example.com", is_staff=True
        )
        provider = ServiceProviderProfile.objects.create(
            user=provider_user, business_name="Approval Provider", contact_person="Owner",
            provider_type="installer", phone_number="+2348000000099",
            email="approval-provider@example.com", country="Nigeria", state="Lagos",
            city="Ikeja", address="1 Approval Road", description="Provider",
            verification_status=ServiceProviderProfile.STATUS_APPROVED,
            subscription_status="active", subscription_plan="Plus", is_active=True,
        )
        category = ServiceCategory.objects.create(name="Approval Service")
        project = ServicePortfolio.objects.create(
            provider=provider, title="Approval project", short_summary="Summary",
            description="Description", service_category=category, city="Ikeja", state="Lagos",
            country="Nigeria", completed_at=date.today(), project_result="Complete",
            approval_status=ServicePortfolio.STATUS_PENDING,
        )
        media = ServiceProjectMedia.objects.create(
            project=project, media_type=ServiceProjectMedia.TYPE_VIDEO,
            external_video_url="https://youtu.be/dQw4w9WgXcQ",
            approval_status=ServiceProjectMedia.STATUS_PENDING,
        )
        mock_release.side_effect = RuntimeError("provider unavailable")

        with patch("installers.project_services.Notification.send"), patch(
            "installers.project_services.safe_project_email"
        ), self.captureOnCommitCallbacks(execute=True):
            moderate_project(project, ServicePortfolio.STATUS_APPROVED, reviewer)

        media.refresh_from_db()
        self.assertEqual(media.approval_status, ServiceProjectMedia.STATUS_APPROVED)
        mock_release.assert_called_once()

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
    @patch("social_publishing.publisher.stage_video_for_social")
    @patch("social_publishing.publisher.social_publishing_access")
    def test_successful_publish_is_persisted(
        self, mock_access, _mock_stage, _mock_url, mock_publish, mock_cleanup
    ):
        mock_access.return_value = SimpleNamespace(allowed=True, reason="")
        _mock_stage.return_value = self._lease()
        self._account()
        def publish_result(*_args, **_kwargs):
            in_flight = SocialPublication.objects.get()
            self.assertEqual(in_flight.status, PublicationStatus.PROCESSING)
            return {
                "container_id": "container-123",
                "media_id": "media-999",
                "permalink": "https://www.instagram.com/reel/example/",
            }
        mock_publish.side_effect = publish_result

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
    @patch("social_publishing.publisher.stage_video_for_social")
    @patch("social_publishing.publisher.social_publishing_access")
    def test_failed_publish_is_safe_and_still_cleans_up(
        self, mock_access, _mock_stage, _mock_url, mock_publish, mock_cleanup
    ):
        mock_access.return_value = SimpleNamespace(allowed=True, reason="")
        _mock_stage.return_value = self._lease()
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
        mock_cleanup.assert_not_called()

    @patch("social_publishing.publisher.cleanup_video_lease")
    @patch("social_publishing.publisher.publish_reel")
    @patch("social_publishing.publisher.get_video_delivery_url", return_value="http://media.example/reel.mp4")
    @patch("social_publishing.publisher.stage_video_for_social")
    @patch("social_publishing.publisher.social_publishing_access")
    def test_temporary_delivery_url_must_be_https(
        self, mock_access, _mock_stage, _mock_url, mock_publish, mock_cleanup
    ):
        mock_access.return_value = SimpleNamespace(allowed=True, reason="")
        _mock_stage.return_value = self._lease()
        self._account()

        with self.assertRaises(InstagramPublicationError) as caught:
            self._publish()

        self.assertEqual(caught.exception.code, "https_video_url_required")
        publication = SocialPublication.objects.get()
        self.assertEqual(publication.status, PublicationStatus.FAILED)
        mock_publish.assert_not_called()
        mock_cleanup.assert_not_called()

    @patch("social_publishing.publisher.cleanup_video_lease")
    @patch("social_publishing.publisher.publish_reel")
    @patch(
        "social_publishing.publisher.get_video_delivery_url",
        return_value="https://media.example/reel.mp4",
    )
    @patch(
        "social_publishing.publisher.stage_video_for_social",
        autospec=True,
    )
    @patch("social_publishing.publisher.social_publishing_access")
    def test_meta_oauth_code_190_marks_account_expired(
        self, mock_access, _mock_stage, _mock_url, mock_publish, mock_cleanup
    ):
        mock_access.return_value = SimpleNamespace(allowed=True, reason="")
        _mock_stage.return_value = self._lease()
        account = self._account()
        mock_publish.side_effect = InstagramPublishingError(
            "The access token has expired.",
            status_code=400,
            error_code=190,
        )

        with self.assertRaises(InstagramPublicationError) as caught:
            self._publish()

        account.refresh_from_db()
        self.assertEqual(account.status, SocialConnectionStatus.EXPIRED)
        self.assertEqual(caught.exception.code, "190")
        self.assertNotIn("encrypted-test-token", str(caught.exception))
        mock_cleanup.assert_not_called()


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

    def test_pending_moderation_response_is_safe_and_actionable(self):
        publication = self._publication(
            status=PublicationStatus.PENDING,
            external_id="",
            external_url="",
            request_metadata={"awaiting_moderation": True},
        )
        with patch("social_publishing.api_views._role_available", return_value=True), patch(
            "social_publishing.api_views._resolve_publication_content", return_value=self.user
        ), patch(
            "social_publishing.api_views.publish_uploaded_video_to_instagram",
            return_value=publication,
        ):
            response = self.client.post(self.url, self._payload("vendor"), format="multipart")

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.data["status"], PublicationStatus.PENDING)
        self.assertTrue(response.data["awaiting_moderation"])
        self.assertEqual(response.data["instagram_permalink"], "")

    def test_failed_post_approval_retry_reuses_retained_source_without_upload(self):
        account = SocialAccount.objects.create(
            user=self.user, owner_role="vendor", platform=SocialPlatform.INSTAGRAM,
            status=SocialConnectionStatus.CONNECTED, external_account_id="retry-account",
            access_token_encrypted="encrypted",
        )
        SocialPublication.objects.create(
            owner_user=self.user, owner_role="vendor", social_account=account,
            platform=SocialPlatform.INSTAGRAM, content_object=self.user,
            status=PublicationStatus.FAILED, deferred_video_lease=TemporaryVideoLease.objects.create(
                owner_user=self.user, owner_role="vendor", storage_key="retry/source.mp4",
                original_filename="source.mp4", expires_at=timezone.now() + timedelta(days=1),
            ),
        )
        payload = self._payload("vendor")
        payload.pop("video")
        payload["retry"] = "true"
        with patch("social_publishing.api_views._role_available", return_value=True), patch(
            "social_publishing.api_views._resolve_publication_content", return_value=self.user
        ), patch(
            "social_publishing.api_views.publish_uploaded_video_to_instagram",
            return_value=self._publication(),
        ) as mock_publish:
            response = self.client.post(self.url, payload, format="multipart")

        self.assertEqual(response.status_code, 201)
        self.assertIsNone(mock_publish.call_args.kwargs["uploaded_file"])

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
                "awaiting_moderation",
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

    def test_mobile_bearer_can_load_account_status_for_issued_role(self):
        self.client.force_authenticate(user=None)
        session = StaffMobileToken.issue(role="provider", user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {session.token}")

        with patch("social_publishing.api_views._role_available", return_value=True), patch(
            "social_publishing.api_views.social_publishing_access",
            return_value=SimpleNamespace(allowed=True, tier="professional", reason=""),
        ):
            response = self.client.get(
                reverse("social_publishing:accounts_status"),
                {"role": "provider"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["role"], "provider")

    def test_vendor_and_provider_connection_states_are_role_bound(self):
        status_url = reverse("social_publishing:accounts_status")
        states = (
            (SocialConnectionStatus.CONNECTED, True),
            (SocialConnectionStatus.EXPIRED, False),
            (None, False),
        )
        with patch("social_publishing.api_views._role_available", return_value=True), patch(
            "social_publishing.api_views.social_publishing_access",
            return_value=SimpleNamespace(allowed=True, tier="professional", reason=""),
        ):
            for role in ("vendor", "provider"):
                for account_status, expected_connected in states:
                    with self.subTest(role=role, account_status=account_status):
                        SocialAccount.objects.filter(user=self.user).delete()
                        if account_status:
                            SocialAccount.objects.create(
                                user=self.user,
                                owner_role=role,
                                platform=SocialPlatform.INSTAGRAM,
                                status=account_status,
                                account_username=f"{role}-instagram",
                            )
                        response = self.client.get(status_url, {"role": role})
                        instagram = next(
                            item for item in response.data["platforms"]
                            if item["platform"] == SocialPlatform.INSTAGRAM
                        )
                        self.assertEqual(response.status_code, 200)
                        self.assertEqual(instagram["connected"], expected_connected)
                        self.assertEqual(
                            instagram["account_username"],
                            f"{role}-instagram" if account_status else "",
                        )

    def test_mobile_account_status_role_cannot_be_changed(self):
        self.client.force_authenticate(user=None)
        session = StaffMobileToken.issue(role="provider", user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {session.token}")

        with patch("social_publishing.api_views._role_available", return_value=True):
            response = self.client.get(
                reverse("social_publishing:accounts_status"),
                {"role": "vendor"},
            )

        self.assertEqual(response.status_code, 403)

    def test_mobile_connect_role_cannot_be_changed(self):
        self.client.force_authenticate(user=None)
        session = StaffMobileToken.issue(role="provider", user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {session.token}")

        with patch("social_publishing.api_views._role_available", return_value=True):
            response = self.client.post(
                reverse(
                    "social_publishing:account_connect_launch",
                    kwargs={"platform": "instagram"},
                ),
                {"role": "vendor"},
                format="json",
            )

        self.assertEqual(response.status_code, 403)

    def test_session_connect_requires_csrf(self):
        csrf_client = APIClient(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        with patch("social_publishing.api_views._role_available", return_value=True):
            response = csrf_client.post(
                reverse(
                    "social_publishing:account_connect_launch",
                    kwargs={"platform": "instagram"},
                ),
                {"role": "vendor"},
                format="json",
            )
        self.assertEqual(response.status_code, 403)
