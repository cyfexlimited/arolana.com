from unittest.mock import Mock, patch
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import requests

from social_publishing.instagram import (
    InstagramPublishingError,
    create_reel_container,
    get_container_status,
    get_published_media,
    publish_reel,
    publish_reel_container,
    wait_for_container,
)
from social_publishing.facebook import FacebookPublishingError, publish_page_video

from django.contrib.auth import get_user_model
from django.conf import settings
from django.core import signing
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from .services import normalize_owner_role, publication_summary_for_content
from .models import (
    PublicationStatus,
    SocialAccount,
    SocialConnectionStatus,
    SocialPlatform,
    SocialPublication,
    TemporaryVideoLease,
)
from .publisher import (
    FacebookPublicationError,
    InstagramPublicationError,
    _content_is_approved_for_distribution,
    _prepare_publication,
    continue_deferred_instagram_publication,
    cleanup_orphaned_pending_instagram_publications,
    release_pending_instagram_publications,
    publish_uploaded_video_to_instagram,
    prepare_uploaded_video_for_facebook,
    continue_deferred_facebook_publication,
    release_pending_facebook_publications,
)
from .oauth import (
    INSTAGRAM_LONG_LIVED_TOKEN_KIND,
    INSTAGRAM_TOKEN_ISSUED_AT_KEY,
    INSTAGRAM_TOKEN_KIND_KEY,
    InstagramTokenLifecycleError,
    exchange_instagram_long_lived_token,
    refresh_instagram_account_if_needed,
    refresh_instagram_long_lived_token,
    resolve_instagram_identity,
)
from staff_mobile.models import StaffMobileToken
from .deletion import ActiveSocialPublicationError
from .connection_security import create_oauth_state
from .web_views import _signed_oauth_state


class SocialPublishingRoleTests(SimpleTestCase):
    def test_facebook_connection_requests_page_publishing_permission(self):
        from .oauth import platform_config

        self.assertIn(
            "pages_manage_posts",
            platform_config(SocialPlatform.FACEBOOK).scopes,
        )

    @patch("social_publishing.facebook.decrypt_token", return_value="test-page-token")
    @patch("social_publishing.facebook.requests.post")
    @patch("social_publishing.facebook.requests.get")
    def test_facebook_publish_validates_and_uses_only_the_selected_page(
        self, mock_get, mock_post, _mock_decrypt
    ):
        account = SimpleNamespace(
            pk=71,
            platform=SocialPlatform.FACEBOOK,
            is_connected=True,
            external_account_id="selected-page-71",
            access_token_encrypted="encrypted",
        )
        mock_get.return_value = Mock(ok=True)
        mock_get.return_value.json.return_value = {"id": "selected-page-71"}
        mock_post.return_value = Mock(ok=True)
        mock_post.return_value.json.return_value = {"id": "facebook-video-71", "post_id": "post-71"}

        result = publish_page_video(
            account, video_url="https://media.example/video.mp4", description="Caption"
        )

        self.assertEqual(result, {"video_id": "facebook-video-71", "post_id": "post-71"})
        self.assertEqual(
            mock_get.call_args.args[0],
            "https://graph.facebook.com/v25.0/selected-page-71",
        )
        self.assertEqual(
            mock_post.call_args.args[0],
            "https://graph.facebook.com/v25.0/selected-page-71/videos",
        )
        self.assertNotIn("/me/accounts", mock_get.call_args.args[0])

    @patch("social_publishing.facebook.decrypt_token", return_value="test-page-token")
    @patch("social_publishing.facebook.requests.post")
    @patch("social_publishing.facebook.requests.get")
    def test_facebook_page_identity_mismatch_never_falls_back_or_posts(
        self, mock_get, mock_post, _mock_decrypt
    ):
        account = SimpleNamespace(
            pk=72,
            platform=SocialPlatform.FACEBOOK,
            is_connected=True,
            external_account_id="selected-page-72",
            access_token_encrypted="encrypted",
        )
        mock_get.return_value = Mock(ok=True)
        mock_get.return_value.json.return_value = {"id": "another-page"}

        with self.assertRaises(FacebookPublishingError) as caught:
            publish_page_video(account, video_url="https://media.example/video.mp4")

        self.assertEqual(caught.exception.error_code, "page_identity_mismatch")
        mock_post.assert_not_called()

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
        self.assertIn("form.querySelector('input[name=\"csrfmiddlewaretoken\"]')", template)
        self.assertNotIn('cookie("csrftoken")', template)
        self.assertIn('role:"provider"', template)
        self.assertIn('credentials:"same-origin"', template)
        self.assertIn("let uploadInFlight=false", template)
        self.assertIn("if(uploadInFlight){event.preventDefault();return;}", template)
        self.assertEqual(template.count("const uploadBody=new FormData(form)"), 1)
        self.assertNotIn('uploadBody.append("files"', template)
        self.assertIn('uploadBody.delete("csrfmiddlewaretoken")', template)
        self.assertIn('response.headers.get("Content-Type")', template)
        self.assertIn('throw new Error(fallback)', template)

    def test_provider_header_first_csrf_does_not_parse_multipart_post(self):
        from installers.csrf import HeaderFirstCsrfViewMiddleware

        class HeaderOnlyRequest:
            method = "POST"
            COOKIES = {settings.CSRF_COOKIE_NAME: "A" * 32}
            META = {
                "CSRF_COOKIE": "A" * 32,
                settings.CSRF_HEADER_NAME: "A" * 32,
            }

            @property
            def POST(self):
                raise AssertionError("multipart POST was parsed during CSRF validation")

        middleware = HeaderFirstCsrfViewMiddleware(lambda request: None)
        middleware._check_token(HeaderOnlyRequest())

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

    @patch("social_publishing.oauth.requests.get")
    @patch("social_publishing.web_views.exchange_instagram_long_lived_token")
    @patch("social_publishing.web_views.exchange_code")
    def test_callback_persists_long_lived_token_and_expiry(
        self, mock_exchange_code, mock_long_lived, mock_profile_get
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
        mock_profile_get.return_value = Mock(
            ok=True,
            json=Mock(return_value={
                "id": "instagram-user-1",
                "username": "arolana_professional",
                "account_type": "BUSINESS",
                "profile_picture_url": "https://cdninstagram.example/avatar.jpg",
            }),
        )
        self.client.force_login(self.user)
        session = self.client.session
        session.save()
        state_row, raw_state = create_oauth_state(
            user=self.user, owner_role="admin", platform="instagram",
            session_identity=session.session_key,
        )
        safe_state = _signed_oauth_state(state_row, raw_state, session.session_key, "")

        response = self.client.get(
            reverse(
                "social_publishing_web:oauth_callback",
                kwargs={"platform": "instagram"},
            ),
            {"state": safe_state, "code": "authorization-code"},
        )

        self.assertEqual(response.status_code, 302)
        account = SocialAccount.objects.get(user=self.user, owner_role="admin")
        self.assertEqual(decrypt_token(account.access_token_encrypted), "long-lived-token")
        self.assertEqual(account.external_account_id, "instagram-user-1")
        self.assertEqual(account.account_username, "arolana_professional")
        self.assertEqual(account.account_name, "Instagram Professional Account")
        self.assertEqual(
            account.platform_metadata["profile_picture_url"],
            "https://cdninstagram.example/avatar.jpg",
        )
        self.assertGreater(account.token_expires_at, timezone.now() + timedelta(days=59))
        self.assertEqual(
            account.platform_metadata[INSTAGRAM_TOKEN_KIND_KEY],
            INSTAGRAM_LONG_LIVED_TOKEN_KIND,
        )
        mock_long_lived.assert_called_once_with("short-lived-token")


class InstagramConnectedIdentityTests(SimpleTestCase):
    @patch("social_publishing.oauth.requests.get")
    def test_connected_identity_uses_meta_username_and_safe_profile_fields(self, mock_get):
        mock_get.return_value = Mock(
            ok=True,
            json=Mock(return_value={
                "id": "17841400000000001",
                "username": "actual_business",
                "account_type": "BUSINESS",
                "profile_picture_url": "https://cdninstagram.example/profile.jpg",
                "access_token": "must-not-be-persisted",
            }),
        )

        identity = resolve_instagram_identity("secret-token", "fallback-id")

        self.assertEqual(identity["account_username"], "actual_business")
        self.assertEqual(identity["external_account_id"], "17841400000000001")
        self.assertEqual(identity["account_name"], "Instagram Professional Account")
        self.assertEqual(identity["platform_metadata"]["account_type"], "BUSINESS")
        self.assertNotIn("secret-token", str(identity))
        self.assertNotIn("must-not-be-persisted", str(identity))

    @patch("social_publishing.oauth.requests.get")
    def test_connected_identity_without_username_uses_professional_fallback(self, mock_get):
        mock_get.return_value = Mock(
            ok=True,
            json=Mock(return_value={"id": "17841400000000002", "account_type": "CREATOR"}),
        )

        identity = resolve_instagram_identity("secret-token", "fallback-id")

        self.assertEqual(identity["account_username"], "")
        self.assertEqual(identity["account_name"], "Instagram Professional Account")

    @patch(
        "social_publishing.oauth.requests.get",
        side_effect=requests.RequestException("provider unavailable"),
    )
    def test_failed_profile_lookup_keeps_safe_connected_identity(self, _mock_get):
        identity = resolve_instagram_identity("secret-token", "fallback-id")

        self.assertEqual(identity["external_account_id"], "fallback-id")
        self.assertEqual(identity["account_name"], "Instagram Professional Account")
        self.assertEqual(identity["account_username"], "")
        self.assertNotIn("secret-token", str(identity))

    def test_no_token_uses_safe_connected_identity_without_lookup(self):
        identity = resolve_instagram_identity("", "fallback-id")

        self.assertEqual(identity["external_account_id"], "fallback-id")
        self.assertEqual(identity["account_name"], "Instagram Professional Account")


@override_settings(
    SOCIAL_PUBLISHING_ENABLED=True,
    SOCIAL_PUBLISHING_INSTAGRAM_ENABLED=True,
    SOCIAL_PUBLISHING_INSTAGRAM_APP_ID="instagram-app-id",
    SOCIAL_PUBLISHING_INSTAGRAM_APP_SECRET="instagram-app-secret",
)
class InstagramConnectedIdentityUITests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="instagram-identity-admin",
            email="instagram-identity@example.com",
            password="test-password",
            is_staff=True,
        )
        self.client.force_login(self.user)

    def test_connected_account_renders_username_professional_label_and_avatar(self):
        SocialAccount.objects.create(
            user=self.user,
            owner_role="admin",
            platform=SocialPlatform.INSTAGRAM,
            status=SocialConnectionStatus.CONNECTED,
            external_account_id="17841400000000003",
            account_name="Instagram Professional Account",
            account_username="actual_business",
            access_token_encrypted="encrypted-token-must-not-render",
            platform_metadata={
                "account_type": "BUSINESS",
                "profile_picture_url": "https://cdninstagram.example/avatar.jpg",
            },
        )

        response = self.client.get(
            reverse("social_publishing_web:accounts"), {"role": "admin"}
        )

        self.assertContains(response, "@actual_business")
        self.assertContains(response, "Instagram Professional Account")
        self.assertContains(response, "https://cdninstagram.example/avatar.jpg")
        self.assertNotContains(response, "encrypted-token-must-not-render")
        self.assertNotContains(response, "Instagram account")

    def test_connected_account_without_username_renders_professional_fallback(self):
        SocialAccount.objects.create(
            user=self.user,
            owner_role="admin",
            platform=SocialPlatform.INSTAGRAM,
            status=SocialConnectionStatus.CONNECTED,
            external_account_id="17841400000000004",
            account_name="Instagram Professional Account",
        )

        response = self.client.get(
            reverse("social_publishing_web:accounts"), {"role": "admin"}
        )

        self.assertContains(response, "Instagram Professional Account")
        self.assertNotContains(response, "Instagram account")

    @patch("social_publishing.instagram.verify_instagram_account")
    def test_accounts_page_does_not_fetch_missing_identity_from_meta(self, mock_verify):
        SocialAccount.objects.create(
            user=self.user,
            owner_role="admin",
            platform=SocialPlatform.INSTAGRAM,
            status=SocialConnectionStatus.CONNECTED,
            external_account_id="17841400000000006",
            account_name="Instagram account",
            access_token_encrypted=encrypt_token("stored-token-must-not-render"),
        )

        response = self.client.get(
            reverse("social_publishing_web:accounts"), {"role": "admin"}
        )

        mock_verify.assert_not_called()
        self.assertContains(response, "Instagram Professional Account")
        self.assertNotContains(response, "stored-token-must-not-render")

    @patch(
        "social_publishing.instagram.verify_instagram_account",
        side_effect=InstagramPublishingError("provider lookup failed"),
    )
    def test_existing_account_profile_failure_does_not_break_connected_ui(self, mock_verify):
        SocialAccount.objects.create(
            user=self.user,
            owner_role="admin",
            platform=SocialPlatform.INSTAGRAM,
            status=SocialConnectionStatus.CONNECTED,
            external_account_id="17841400000000007",
            account_name="Instagram account",
            access_token_encrypted=encrypt_token("failed-token-must-not-render"),
        )

        response = self.client.get(
            reverse("social_publishing_web:accounts"), {"role": "admin"}
        )

        self.assertContains(response, "Connected")
        self.assertContains(response, "Instagram Professional Account")
        mock_verify.assert_not_called()
        self.assertNotContains(response, "provider lookup failed")
        self.assertNotContains(response, "failed-token-must-not-render")

    def test_disconnected_account_keeps_not_connected_state(self):
        response = self.client.get(
            reverse("social_publishing_web:accounts"), {"role": "admin"}
        )

        self.assertContains(response, "Not connected")
        self.assertNotContains(response, "@actual_business")

    def test_status_api_returns_only_safe_instagram_identity(self):
        SocialAccount.objects.create(
            user=self.user,
            owner_role="admin",
            platform=SocialPlatform.INSTAGRAM,
            status=SocialConnectionStatus.CONNECTED,
            external_account_id="17841400000000005",
            account_name="Instagram Professional Account",
            account_username="api_business",
            access_token_encrypted="encrypted-api-token-must-not-render",
            refresh_token_encrypted="encrypted-refresh-token-must-not-render",
            platform_metadata={
                "profile_picture_url": "https://cdninstagram.example/api-avatar.jpg",
            },
        )

        response = self.client.get(
            reverse("social_publishing:accounts_status"), {"role": "admin"}
        )
        instagram = next(
            item for item in response.data["platforms"]
            if item["platform"] == SocialPlatform.INSTAGRAM
        )

        self.assertEqual(instagram["account_username"], "api_business")
        self.assertEqual(instagram["external_account_id"], "17841400000000005")
        self.assertEqual(
            instagram["profile_picture_url"],
            "https://cdninstagram.example/api-avatar.jpg",
        )
        rendered = str(response.data)
        self.assertNotIn("encrypted-api-token-must-not-render", rendered)
        self.assertNotIn("encrypted-refresh-token-must-not-render", rendered)

    @patch("social_publishing.instagram.verify_instagram_account")
    def test_status_api_does_not_fetch_missing_identity_from_meta(self, mock_verify):
        SocialAccount.objects.create(
            user=self.user,
            owner_role="admin",
            platform=SocialPlatform.INSTAGRAM,
            status=SocialConnectionStatus.CONNECTED,
            external_account_id="17841400000000008",
            account_name="Instagram Professional Account",
            access_token_encrypted=encrypt_token("api-token-must-not-render"),
        )

        response = self.client.get(
            reverse("social_publishing:accounts_status"), {"role": "admin"}
        )

        self.assertEqual(response.status_code, 200)
        mock_verify.assert_not_called()
        self.assertNotIn("api-token-must-not-render", str(response.data))


@override_settings(
    SOCIAL_PUBLISHING_ENABLED=True,
    SOCIAL_PUBLISHING_INSTAGRAM_ENABLED=True,
    SOCIAL_PUBLISHING_INSTAGRAM_APP_ID="provider-instagram-app",
    SOCIAL_PUBLISHING_INSTAGRAM_APP_SECRET="provider-instagram-secret",
    SOCIAL_PUBLISHING_INSTAGRAM_SCOPES="instagram_business_basic,instagram_business_content_publish",
)
class ProviderInstagramReconnectTests(TestCase):
    def setUp(self):
        from installers.models import ServiceProviderProfile

        self.user = get_user_model().objects.create_user(
            username="expired-instagram-provider",
            email="expired-provider@example.com",
            password="test-password",
        )
        ServiceProviderProfile.objects.create(
            user=self.user,
            business_name="Expired Instagram Provider",
            contact_person="Provider Owner",
            provider_type="installer",
            phone_number="+2348000000299",
            email="expired-provider@example.com",
            country="Nigeria",
            state="Lagos",
            city="Ikeja",
            address="1 Reconnect Road",
            description="Provider reconnect fixture.",
            verification_status=ServiceProviderProfile.STATUS_APPROVED,
            subscription_status="active",
            subscription_plan="enterprise",
            is_active=True,
        )
        self.account = SocialAccount.objects.create(
            user=self.user,
            owner_role="provider",
            platform=SocialPlatform.INSTAGRAM,
            status=SocialConnectionStatus.EXPIRED,
            external_account_id="27349604818046482",
            access_token_encrypted="expired-encrypted-token",
            last_error="Instagram authorization expired. Reauthorization is required.",
        )
        self.connect_url = reverse(
            "social_publishing:account_connect_launch",
            kwargs={"platform": "instagram"},
        )

    @patch("social_publishing.api_views.social_publishing_access")
    def test_expired_provider_web_account_can_launch_reauthorization(self, mock_access):
        mock_access.return_value = SimpleNamespace(
            allowed=True, tier="enterprise", reason=""
        )
        client = APIClient()
        client.force_authenticate(self.user)

        response = client.post(
            self.connect_url,
            {
                "role": "provider",
                "return_url": "/dashboard/provider/projects/1/media/",
            },
            format="json",
            secure=True,
            HTTP_HOST="arolana.com",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["role"], "provider")
        authorization_url = response.data["authorization_url"]
        launch = parse_qs(urlparse(authorization_url).query)["launch"][0]
        payload = signing.loads(
            launch,
            salt="arolana.social-publishing.launch.v1",
            max_age=600,
        )
        self.assertEqual(payload["user_id"], self.user.pk)
        self.assertEqual(payload["role"], "provider")
        self.assertEqual(payload["return_url"], "/dashboard/provider/projects/1/media/")
        self.account.refresh_from_db()
        self.assertEqual(self.account.status, SocialConnectionStatus.EXPIRED)

    @patch("social_publishing.api_views.social_publishing_access")
    def test_expired_provider_staff_mobile_account_uses_role_bound_launch(self, mock_access):
        mock_access.return_value = SimpleNamespace(
            allowed=True, tier="enterprise", reason=""
        )
        mobile_session = StaffMobileToken.issue("provider", user=self.user)
        client = APIClient()

        response = client.post(
            self.connect_url,
            {
                "role": "provider",
                "return_url": "arolanastaffmobile://social-accounts",
            },
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {mobile_session.token}",
        )

        self.assertEqual(response.status_code, 200)
        launch = parse_qs(urlparse(response.data["authorization_url"]).query)["launch"][0]
        payload = signing.loads(
            launch,
            salt="arolana.social-publishing.launch.v1",
            max_age=600,
        )
        self.assertEqual(payload["role"], "provider")
        self.assertEqual(payload["return_url"], "arolanastaffmobile://social-accounts")

    @patch("social_publishing.web_views.resolve_identity")
    @patch("social_publishing.web_views.exchange_instagram_long_lived_token")
    @patch("social_publishing.web_views.exchange_code")
    def test_provider_callback_reconnects_existing_expired_account_only(
        self, mock_exchange_code, mock_long_lived, mock_identity
    ):
        mock_exchange_code.return_value = {
            "access_token": "new-short-lived-token",
            "user_id": self.account.external_account_id,
        }
        mock_long_lived.return_value = {
            "access_token": "new-long-lived-token",
            "expires_in": 5184000,
            "token_type": "bearer",
        }
        mock_identity.return_value = {
            "external_account_id": self.account.external_account_id,
            "account_name": "Provider Instagram",
            "account_username": "provider_instagram",
            "platform_metadata": {},
        }
        client = APIClient()
        session = client.session
        session.save()
        state_row, raw_state = create_oauth_state(
            user=self.user, owner_role="provider", platform="instagram",
            session_identity=session.session_key,
            return_target="/dashboard/provider/projects/1/media/",
        )
        safe_state = _signed_oauth_state(state_row, raw_state, session.session_key, "")

        response = client.get(
            reverse(
                "social_publishing_web:oauth_callback",
                kwargs={"platform": "instagram"},
            ),
            {"state": safe_state, "code": "authorization-code"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/dashboard/provider/projects/1/media/?status=connected&platform=instagram")
        account = SocialAccount.objects.get(pk=self.account.pk)
        self.assertEqual(account.status, SocialConnectionStatus.CONNECTED)
        self.assertEqual(account.owner_role, "provider")
        self.assertEqual(account.user_id, self.user.pk)
        self.assertEqual(
            SocialAccount.objects.filter(
                user=self.user, platform="instagram", owner_role="provider"
            ).count(),
            1,
        )
        self.assertFalse(
            SocialAccount.objects.filter(
                user=self.user, platform="instagram", owner_role="vendor"
            ).exists()
        )
        mock_long_lived.assert_called_once_with("new-short-lived-token")


class InstagramOAuthTokenRefreshLifecycleTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="instagram-refresh-admin",
            email="instagram-refresh-admin@example.com",
            password="test-password",
            is_staff=True,
        )

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
        # Simulate a legacy orphan without bypassing the active-publication
        # deletion guard that now protects normal source deletion.
        publication.object_id = video.pk + 999999
        publication.save(update_fields=["object_id", "updated_at"])

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

    @patch("social_publishing.publisher.cleanup_video_lease")
    @patch("social_publishing.publisher.publish_reel")
    @patch(
        "social_publishing.publisher.get_video_delivery_url",
        return_value="https://media.example/provider-source.mp4",
    )
    @patch("social_publishing.publisher._connected_instagram_account")
    @patch("social_publishing.publisher.social_publishing_access")
    def test_provider_approval_releases_existing_pending_media_publication(
        self, mock_access, mock_account, _mock_url, mock_publish, _mock_cleanup
    ):
        from datetime import date
        from installers.models import (
            ServiceCategory,
            ServicePortfolio,
            ServiceProjectMedia,
            ServiceProviderProfile,
        )
        from installers.project_services import moderate_project

        provider_user = get_user_model().objects.create_user(
            username="intent-release-provider", email="intent-release@example.com"
        )
        reviewer = get_user_model().objects.create_user(
            username="intent-release-reviewer", email="intent-reviewer@example.com", is_staff=True
        )
        provider = ServiceProviderProfile.objects.create(
            user=provider_user, business_name="Intent Release Provider", contact_person="Owner",
            provider_type="installer", phone_number="+2348000000199",
            email="intent-release@example.com", country="Nigeria", state="Lagos",
            city="Ikeja", address="1 Intent Road", description="Provider",
            verification_status=ServiceProviderProfile.STATUS_APPROVED,
            subscription_status="active", subscription_plan="Plus", is_active=True,
        )
        category = ServiceCategory.objects.create(name="Intent Release Service")
        project = ServicePortfolio.objects.create(
            provider=provider, title="Intent release project", short_summary="Summary",
            description="Description", service_category=category, city="Ikeja", state="Lagos",
            country="Nigeria", completed_at=date.today(), project_result="Complete",
            approval_status=ServicePortfolio.STATUS_PENDING,
        )
        media = ServiceProjectMedia.objects.create(
            project=project, media_type=ServiceProjectMedia.TYPE_VIDEO,
            external_video_url="https://youtu.be/provider-release",
            approval_status=ServiceProjectMedia.STATUS_PENDING,
        )
        account = SocialAccount.objects.create(
            user=provider_user, owner_role="provider", platform=SocialPlatform.INSTAGRAM,
            status=SocialConnectionStatus.CONNECTED,
            external_account_id="provider-release", access_token_encrypted="encrypted",
        )
        publication = SocialPublication.objects.create(
            owner_user=provider_user, owner_role="provider", social_account=account,
            platform=SocialPlatform.INSTAGRAM, content_object=media,
            status=PublicationStatus.PENDING,
            deferred_video_lease=TemporaryVideoLease.objects.create(
                owner_user=provider_user, owner_role="provider",
                storage_key="provider-release/source.mp4", original_filename="source.mp4",
                expires_at=timezone.now() + timedelta(days=1),
            ),
            request_metadata={"caption": "Provider proof", "share_to_feed": True},
        )
        mock_access.return_value = SimpleNamespace(allowed=True, reason="")
        mock_account.return_value = account
        mock_publish.return_value = {
            "media_id": "released-provider-media",
            "permalink": "https://www.instagram.com/reel/released-provider-media/",
        }

        with patch("installers.project_services.Notification.send"), patch(
            "installers.project_services.safe_project_email"
        ), self.captureOnCommitCallbacks(execute=True):
            moderate_project(project, ServicePortfolio.STATUS_APPROVED, reviewer)

        media.refresh_from_db()
        publication.refresh_from_db()
        self.assertEqual(media.approval_status, ServiceProjectMedia.STATUS_APPROVED)
        self.assertEqual(publication.status, PublicationStatus.PUBLISHED)
        self.assertEqual(publication.external_id, "released-provider-media")

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


class ArolanaOnlySocialPublicationDeletionTests(TestCase):
    def setUp(self):
        from products.models import Category, Product, ProductVideo
        from vendors.models import VendorProfile

        # API attributes support the remaining shared-endpoint regression
        # methods below; deletion fixtures use their own role-bound owner.
        self.user = get_user_model().objects.create_user(
            username="instagram-api-deletion-user",
            email="instagram-api-deletion@example.com",
            password="test-password",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.url = reverse("social_publishing:instagram_video_publish")
        self.Product = Product
        self.ProductVideo = ProductVideo
        self.vendor_user = get_user_model().objects.create_user(
            username="deletion-vendor", email="deletion-vendor@example.com"
        )
        self.vendor = VendorProfile.objects.create(
            user=self.vendor_user,
            store_name="Deletion Vendor",
            store_slug="deletion-vendor",
            description="Deletion lifecycle tests",
            approval_status="approved",
            is_verified=True,
            is_active=True,
            address_line_1="1 Audit Road",
            city="Ikeja",
            state="Lagos",
            country="Nigeria",
        )
        self.category = Category.objects.create(name="Deletion Products", slug="deletion-products")
        self.product = Product.objects.create(
            vendor=self.vendor_user,
            category=self.category,
            name="Deletion Product",
            slug="deletion-product",
            sku="DELETE-1",
            price="100.00",
            stock_quantity=1,
            approval_status="approved",
            is_active=True,
        )

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
            "social_publishing.api_views._resolve_publication_content", return_value=self.user
        ), patch(
            "social_publishing.api_views.publish_uploaded_video_to_instagram",
            return_value=publication,
        ) as mock_publish:
            response = self.client.post(self.url, self._payload(role), format="multipart")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(mock_publish.call_args.kwargs["owner_role"], role)
        return response

    def product_video(self, suffix="one"):
        return self.ProductVideo.objects.create(
            product=self.product,
            vendor=self.vendor,
            title=f"Deletion video {suffix}",
            source="youtube",
            youtube_url=f"https://www.youtube.com/watch?v=delete-{suffix}",
            youtube_video_id=f"delete-{suffix}",
            moderation_status="approved",
            is_active=True,
        )

    def publication(self, content, status=PublicationStatus.PUBLISHED, **overrides):
        values = {
            "owner_user": self.vendor_user,
            "owner_role": "vendor",
            "platform": SocialPlatform.INSTAGRAM,
            "content_object": content,
            "status": status,
            "external_id": "instagram-media-123",
            "external_url": "https://www.instagram.com/reel/preserved/",
            "attempt_count": 2,
            "error_code": "",
            "error_message": "",
        }
        values.update(overrides)
        return SocialPublication.objects.create(**values)

    @patch("social_publishing.publisher.publish_reel")
    @patch("core.youtube_service.requests.delete")
    def test_published_product_video_delete_archives_audit_without_external_delete(
        self, youtube_delete, instagram_publish
    ):
        from django.contrib import admin

        video = self.product_video()
        publication = self.publication(video)
        video_id = video.pk
        # Exercise the normal Django Admin object-delete path.
        admin.site._registry[self.ProductVideo].delete_model(SimpleNamespace(), video)

        self.assertFalse(self.ProductVideo.objects.filter(pk=video_id).exists())
        publication.refresh_from_db()
        self.assertEqual(publication.external_id, "instagram-media-123")
        self.assertEqual(publication.external_url, "https://www.instagram.com/reel/preserved/")
        self.assertEqual(publication.original_content_type_label, "products.ProductVideo")
        self.assertEqual(publication.original_object_id, video_id)
        self.assertIsNotNone(publication.archived_at)
        self.assertIsNone(publication.content_object)
        youtube_delete.assert_not_called()
        instagram_publish.assert_not_called()

    def test_product_cascade_archives_published_child_publication(self):
        video = self.product_video("cascade")
        publication = self.publication(video)
        product_id, video_id = self.product.pk, video.pk
        self.product.delete()

        self.assertFalse(self.Product.objects.filter(pk=product_id).exists())
        self.assertFalse(self.ProductVideo.objects.filter(pk=video_id).exists())
        publication.refresh_from_db()
        self.assertEqual(publication.status, PublicationStatus.PUBLISHED)
        self.assertEqual(publication.original_object_id, video_id)
        self.assertIsNotNone(publication.archived_at)

    def test_failed_terminal_and_bulk_video_delete_preserve_audits(self):
        from django.contrib import admin

        videos = [self.product_video("bulk-a"), self.product_video("bulk-b")]
        publications = [
            self.publication(
                video,
                status=PublicationStatus.FAILED,
                external_id="",
                external_url="",
                error_code="safe_failure",
                error_message="Safe failure detail",
            )
            for video in videos
        ]
        queryset = self.ProductVideo.objects.filter(pk__in=[video.pk for video in videos])
        # Exercise Django Admin's bulk delete implementation.
        admin.site._registry[self.ProductVideo].delete_queryset(SimpleNamespace(), queryset)
        self.assertFalse(self.ProductVideo.objects.filter(pk__in=[video.pk for video in videos]).exists())
        for publication in publications:
            publication.refresh_from_db()
            self.assertEqual(publication.status, PublicationStatus.FAILED)
            self.assertEqual(publication.error_code, "safe_failure")
            self.assertIsNotNone(publication.archived_at)

    @patch("social_publishing.video_staging.cleanup_video_lease")
    def test_active_publication_blocks_delete_and_keeps_lease(self, cleanup):
        video = self.product_video("pending")
        lease = TemporaryVideoLease.objects.create(
            owner_user=self.vendor_user,
            owner_role="vendor",
            storage_key="deletion/pending-source.mp4",
            expires_at=timezone.now() + timedelta(days=1),
        )
        publication = self.publication(
            video,
            status=PublicationStatus.PENDING,
            external_id="",
            external_url="",
            deferred_video_lease=lease,
        )
        with self.assertRaises(ActiveSocialPublicationError):
            with transaction.atomic():
                video.delete()
        self.assertTrue(self.ProductVideo.objects.filter(pk=video.pk).exists())
        publication.refresh_from_db()
        self.assertEqual(publication.status, PublicationStatus.PENDING)
        self.assertEqual(publication.deferred_video_lease, lease)
        cleanup.assert_not_called()

    def test_provider_media_and_project_cascade_follow_same_lifecycle(self):
        from datetime import date
        from installers.models import (
            ServiceCategory,
            ServicePortfolio,
            ServiceProjectMedia,
            ServiceProviderProfile,
        )

        provider_user = get_user_model().objects.create_user(
            username="deletion-provider", email="deletion-provider@example.com"
        )
        provider = ServiceProviderProfile.objects.create(
            user=provider_user,
            business_name="Deletion Provider",
            contact_person="Owner",
            provider_type="installer",
            phone_number="+2348000000777",
            email="deletion-provider@example.com",
            country="Nigeria",
            state="Lagos",
            city="Ikeja",
            address="2 Audit Road",
            description="Provider",
            verification_status=ServiceProviderProfile.STATUS_APPROVED,
            subscription_status="active",
            subscription_plan="Plus",
            is_active=True,
        )
        category = ServiceCategory.objects.create(name="Deletion Services")
        project = ServicePortfolio.objects.create(
            provider=provider,
            title="Deletion project",
            short_summary="Summary",
            description="Description",
            service_category=category,
            city="Ikeja",
            state="Lagos",
            country="Nigeria",
            completed_at=date.today(),
            project_result="Complete",
            approval_status=ServicePortfolio.STATUS_APPROVED,
        )
        media = ServiceProjectMedia.objects.create(
            project=project,
            media_type=ServiceProjectMedia.TYPE_VIDEO,
            external_video_url="https://youtu.be/provider-delete",
            approval_status=ServiceProjectMedia.STATUS_APPROVED,
        )
        publication = SocialPublication.objects.create(
            owner_user=provider_user,
            owner_role="provider",
            platform=SocialPlatform.INSTAGRAM,
            content_object=media,
            status=PublicationStatus.PUBLISHED,
            external_id="provider-instagram-id",
            external_url="https://www.instagram.com/reel/provider-preserved/",
        )
        project_publication = SocialPublication.objects.create(
            owner_user=provider_user,
            owner_role="provider",
            platform=SocialPlatform.INSTAGRAM,
            content_object=project,
            status=PublicationStatus.FAILED,
            error_code="safe_project_failure",
            error_message="Safe project failure",
        )
        media_id = media.pk
        project_id = project.pk
        project.delete()
        self.assertFalse(ServiceProjectMedia.objects.filter(pk=media_id).exists())
        publication.refresh_from_db()
        self.assertEqual(publication.external_id, "provider-instagram-id")
        self.assertEqual(publication.original_content_type_label, "installers.ServiceProjectMedia")
        self.assertEqual(publication.original_object_id, media_id)
        self.assertIsNotNone(publication.archived_at)
        project_publication.refresh_from_db()
        self.assertEqual(
            project_publication.original_content_type_label,
            "installers.ServicePortfolio",
        )
        self.assertEqual(project_publication.original_object_id, project_id)
        self.assertIsNotNone(project_publication.archived_at)
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


@override_settings(
    SOCIAL_PUBLISHING_ENABLED=True,
    SOCIAL_PUBLISHING_FACEBOOK_PUBLISHING_ENABLED=True,
)
class FacebookDeferredPublicationTests(TestCase):
    def setUp(self):
        from products.models import Category, Product, ProductVideo

        self.vendor = get_user_model().objects.create_user(
            username="facebook-publisher", email="facebook-publisher@example.com"
        )
        category = Category.objects.create(
            name="Facebook publishing", slug="facebook-publishing", is_active=True
        )
        product = Product.objects.create(
            vendor=self.vendor, category=category, sku="FACEBOOK-1",
            name="Facebook Product", slug="facebook-product", description="Video",
            price="100.00", stock_quantity=1, approval_status="pending", is_active=False,
        )
        self.video = ProductVideo.objects.create(
            product=product, title="Facebook video", source="youtube",
            youtube_video_id="facebook-video", moderation_status="pending", is_active=True,
        )
        self.account = SocialAccount.objects.create(
            user=self.vendor, owner_role="vendor", platform=SocialPlatform.FACEBOOK,
            status=SocialConnectionStatus.CONNECTED, external_account_id="facebook-page-1",
            account_name="Vendor Facebook Page", access_token_encrypted="encrypted-page-token",
            scopes=["pages_show_list", "pages_read_engagement", "pages_manage_posts"],
        )
        self.upload = SimpleUploadedFile("facebook.mp4", b"video", content_type="video/mp4")
        self.lease = TemporaryVideoLease.objects.create(
            owner_user=self.vendor, owner_role="vendor", storage_key="facebook/test.mp4",
            original_filename="facebook.mp4", expires_at=timezone.now() + timedelta(days=1),
        )

    @patch("social_publishing.publisher.stage_video_for_social")
    @patch("social_publishing.publisher.social_publishing_access")
    def test_selection_creates_one_pending_audit_record_without_facebook_call(self, mock_access, mock_stage):
        mock_access.return_value = SimpleNamespace(allowed=True, reason="")
        mock_stage.return_value = self.lease
        with patch("social_publishing.publisher.publish_page_video") as mock_publish:
            publication = prepare_uploaded_video_for_facebook(
                user=self.vendor, owner_role="vendor", content_object=self.video,
                uploaded_file=self.upload, caption="Approved product video",
            )
            duplicate = prepare_uploaded_video_for_facebook(
                user=self.vendor, owner_role="vendor", content_object=self.video,
                uploaded_file=self.upload, caption="Approved product video",
            )
        self.assertEqual(publication.pk, duplicate.pk)
        self.assertEqual(publication.status, PublicationStatus.PENDING)
        self.assertEqual(publication.platform, SocialPlatform.FACEBOOK)
        self.assertEqual(publication.social_account, self.account)
        self.assertEqual(SocialPublication.objects.filter(platform=SocialPlatform.FACEBOOK).count(), 1)
        self.assertEqual(mock_stage.call_count, 1)
        mock_publish.assert_not_called()

    def test_mobile_publication_summary_is_owned_and_credential_free(self):
        publication = SocialPublication.objects.create(
            owner_user=self.vendor, owner_role="vendor", social_account=self.account,
            platform=SocialPlatform.FACEBOOK, content_object=self.video,
            status=PublicationStatus.FAILED, external_id="facebook-video-91",
            external_url="https://www.facebook.com/vendor/videos/91",
            attempt_count=2, error_message="raw Graph detail access_token=never-return",
        )
        summary = publication_summary_for_content(
            self.video, platform=SocialPlatform.FACEBOOK,
            owner_user_id=self.vendor.pk, owner_role="vendor",
        )
        self.assertEqual(summary["publication_id"], publication.pk)
        self.assertEqual(summary["facebook_video_id"], "facebook-video-91")
        self.assertEqual(summary["facebook_permalink"], publication.external_url)
        self.assertEqual(summary["attempt_count"], 2)
        self.assertEqual(summary["error_message"], "Facebook publication could not be completed.")
        self.assertNotIn("access_token", str(summary))
        self.assertIsNone(publication_summary_for_content(
            self.video, platform=SocialPlatform.FACEBOOK,
            owner_user_id=self.vendor.pk + 100, owner_role="vendor",
        ))

    @patch("social_publishing.publisher.cleanup_video_lease")
    @patch("social_publishing.publisher.publish_page_video")
    @patch("social_publishing.publisher.get_video_delivery_url", return_value="https://media.example/facebook.mp4")
    @patch("social_publishing.publisher.social_publishing_access")
    def test_approved_video_releases_once_and_records_facebook_video_id(
        self, mock_access, _mock_url, mock_publish, mock_cleanup
    ):
        mock_access.return_value = SimpleNamespace(allowed=True, reason="")
        mock_publish.return_value = {"video_id": "facebook-video-91", "post_id": "page_91"}
        self.video.moderation_status = "approved"
        self.video.save(update_fields=["moderation_status"])
        publication = SocialPublication.objects.create(
            owner_user=self.vendor, owner_role="vendor", social_account=self.account,
            platform=SocialPlatform.FACEBOOK, content_object=self.video,
            status=PublicationStatus.PENDING, deferred_video_lease=self.lease,
            request_metadata={"caption": "Approved product video", "awaiting_moderation": True},
        )
        result = continue_deferred_facebook_publication(publication)
        duplicate = continue_deferred_facebook_publication(result)
        self.assertEqual(result.status, PublicationStatus.PUBLISHED)
        self.assertEqual(result.external_id, "facebook-video-91")
        self.assertEqual(result.response_metadata["facebook_post_id"], "page_91")
        self.assertEqual(duplicate.pk, result.pk)
        mock_publish.assert_called_once()
        mock_cleanup.assert_called_once_with(self.lease)

    @patch("social_publishing.publisher.publish_page_video", side_effect=RuntimeError("provider token=secret"))
    @patch("social_publishing.publisher.get_video_delivery_url", return_value="https://media.example/facebook.mp4")
    @patch("social_publishing.publisher.social_publishing_access")
    def test_facebook_failure_marks_only_publication_failed_not_approval(self, mock_access, _mock_url, _mock_publish):
        mock_access.return_value = SimpleNamespace(allowed=True, reason="")
        self.video.moderation_status = "approved"
        self.video.save(update_fields=["moderation_status"])
        publication = SocialPublication.objects.create(
            owner_user=self.vendor, owner_role="vendor", social_account=self.account,
            platform=SocialPlatform.FACEBOOK, content_object=self.video,
            status=PublicationStatus.PENDING, deferred_video_lease=self.lease,
        )
        results = release_pending_facebook_publications([self.video])
        publication.refresh_from_db()
        self.video.refresh_from_db()
        self.assertEqual(results[0].status, PublicationStatus.FAILED)
        self.assertEqual(self.video.moderation_status, "approved")
        self.assertNotIn("secret", publication.error_message)

    def test_vendor_templates_expose_connected_facebook_destination_not_coming_soon(self):
        for name in ("vendor_add_product.html", "vendor_product_detail.html"):
            template = Path(settings.BASE_DIR, "templates/dashboard", name).read_text()
            self.assertIn("Facebook", template)
            self.assertIn("facebook/videos/prepare/", template)
            self.assertIn("accounts/facebook/connect/", template)
            self.assertIn("Facebook publishing is currently not enabled.", template)
            self.assertIn("account_publishing_ready", template)
        self.assertNotIn("<strong>Facebook</strong><span class=\"text-xs font-black\">Coming soon", Path(settings.BASE_DIR, "templates/dashboard/vendor_add_product.html").read_text())

    @patch("social_publishing.publisher.social_publishing_access")
    def test_unconnected_facebook_page_is_rejected_with_safe_audit_state(self, mock_access):
        mock_access.return_value = SimpleNamespace(allowed=True, reason="")
        self.account.delete()
        with self.assertRaises(FacebookPublicationError) as caught:
            prepare_uploaded_video_for_facebook(
                user=self.vendor, owner_role="vendor", content_object=self.video,
                uploaded_file=self.upload,
            )
        self.assertEqual(caught.exception.code, "facebook_not_connected")
        publication = SocialPublication.objects.get(platform=SocialPlatform.FACEBOOK)
        self.assertEqual(publication.status, PublicationStatus.FAILED)
        self.assertNotIn("token", publication.error_message.lower())

    @patch("social_publishing.publisher.social_publishing_access")
    def test_connected_page_without_posting_scope_requires_reconnect(self, mock_access):
        mock_access.return_value = SimpleNamespace(allowed=True, reason="")
        self.account.scopes = ["pages_show_list", "pages_read_engagement"]
        self.account.save(update_fields=["scopes"])
        with self.assertRaises(FacebookPublicationError) as caught:
            prepare_uploaded_video_for_facebook(
                user=self.vendor, owner_role="vendor", content_object=self.video,
                uploaded_file=self.upload,
            )
        self.assertEqual(caught.exception.code, "facebook_publish_permission_required")

    @patch("social_publishing.publisher.stage_video_for_social")
    @patch("social_publishing.publisher.social_publishing_access")
    @patch("social_publishing.api_views._role_available", return_value=True)
    def test_api_persists_one_pending_facebook_selection_and_returns_safe_status(
        self, _mock_role_available, mock_access, mock_stage
    ):
        mock_access.return_value = SimpleNamespace(allowed=True, reason="")
        mock_stage.return_value = self.lease
        client = APIClient()
        client.force_authenticate(user=self.vendor)
        url = reverse("social_publishing:facebook_video_prepare")
        request_data = {
            "role": "vendor",
            "content_type": "products.productvideo",
            "object_id": str(self.video.pk),
            "video": SimpleUploadedFile("facebook.mp4", b"video", content_type="video/mp4"),
            "caption": "Facebook caption",
        }
        response = client.post(url, request_data, format="multipart")
        duplicate = client.post(
            url,
            {
                **request_data,
                "video": SimpleUploadedFile("facebook-again.mp4", b"video", content_type="video/mp4"),
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, 202, response.data)
        self.assertEqual(duplicate.status_code, 202, duplicate.data)
        self.assertEqual(response.data["status"], PublicationStatus.PENDING)
        self.assertTrue(response.data["awaiting_moderation"])
        self.assertNotIn("access_token", response.data)
        self.assertEqual(
            SocialPublication.objects.filter(platform=SocialPlatform.FACEBOOK).count(), 1
        )
        self.assertEqual(mock_stage.call_count, 1)

    @patch("social_publishing.api_views._role_available", return_value=True)
    @patch("social_publishing.publisher.social_publishing_access")
    def test_api_rejects_unconnected_facebook_page_with_safe_error(
        self, mock_access, _mock_role_available
    ):
        mock_access.return_value = SimpleNamespace(allowed=True, reason="")
        self.account.delete()
        client = APIClient()
        client.force_authenticate(user=self.vendor)
        response = client.post(
            reverse("social_publishing:facebook_video_prepare"),
            {
                "role": "vendor",
                "content_type": "products.productvideo",
                "object_id": str(self.video.pk),
                "video": SimpleUploadedFile("facebook.mp4", b"video", content_type="video/mp4"),
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["error_code"], "facebook_not_connected")
        self.assertNotIn("token", str(response.data).lower())

    @patch("social_publishing.publisher.release_pending_facebook_publications")
    def test_product_video_approval_schedules_facebook_release(self, mock_release):
        from social_publishing.moderation import approve_product_video

        reviewer = get_user_model().objects.create_user(
            username="facebook-reviewer", email="facebook-reviewer@example.com", is_staff=True
        )
        with self.captureOnCommitCallbacks(execute=True):
            approve_product_video(self.video, reviewer)
        mock_release.assert_called_once()
