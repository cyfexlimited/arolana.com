from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import signing
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from .connection_security import SocialOAuthStateError, consume_oauth_state, create_oauth_state
from .crypto import decrypt_token, encrypt_token
from .models import SocialAccount, SocialConnectionAuditLog, SocialOAuthState, SocialPlatform
from .web_views import FACEBOOK_SELECTION_SALT, _signed_oauth_state


class DurableSocialOAuthStateTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("state-admin@example.com", password="x", is_staff=True, username="state-admin")

    def create_state(self, **overrides):
        values = {
            "user": self.user, "owner_role": "admin", "platform": "instagram",
            "session_identity": "browser-session", "mobile_identity": "",
        }
        values.update(overrides)
        return create_oauth_state(**values)

    def test_success_and_reuse_compare_and_set(self):
        state, token = self.create_state()
        consumed = consume_oauth_state(raw_token=token, user_id=self.user.pk, owner_role="admin",
                                       platform="instagram", session_identity="browser-session")
        self.assertIsNotNone(consumed.used_at)
        with self.assertRaises(SocialOAuthStateError):
            consume_oauth_state(raw_token=token, user_id=self.user.pk, owner_role="admin",
                                platform="instagram", session_identity="browser-session")

    def test_expiry_and_all_bindings_fail_closed(self):
        cases = [
            {"user_id": self.user.pk + 999}, {"owner_role": "vendor"},
            {"platform": "facebook"}, {"session_identity": "wrong-session"},
        ]
        for changes in cases:
            state, token = self.create_state()
            args = {"raw_token": token, "user_id": self.user.pk, "owner_role": "admin",
                    "platform": "instagram", "session_identity": "browser-session"}
            args.update(changes)
            with self.assertRaises(SocialOAuthStateError):
                consume_oauth_state(**args)
        state, token = self.create_state()
        SocialOAuthState.objects.filter(pk=state.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        with self.assertRaises(SocialOAuthStateError):
            consume_oauth_state(raw_token=token, user_id=self.user.pk, owner_role="admin",
                                platform="instagram", session_identity="browser-session")

    def test_mobile_launch_binding_mismatch(self):
        state, token = self.create_state(session_identity="", mobile_identity="signed-mobile-launch")
        with self.assertRaises(SocialOAuthStateError):
            consume_oauth_state(raw_token=token, user_id=self.user.pk, owner_role="admin",
                                platform="instagram", mobile_identity="different-launch")

    @patch("social_publishing.web_views.exchange_code", side_effect=RuntimeError("token exchange failed"))
    def test_downstream_failure_does_not_revive_state_or_leak_code(self, _exchange):
        self.client.force_login(self.user)
        session = self.client.session
        session.save()
        state, token = self.create_state(session_identity=session.session_key)
        signed = _signed_oauth_state(state, token, session.session_key, "")
        response = self.client.get(reverse("social_publishing_web:oauth_callback", kwargs={"platform": "instagram"}),
                                   {"state": signed, "code": "super-secret-code"})
        self.assertEqual(response.status_code, 302)
        state.refresh_from_db()
        self.assertIsNotNone(state.used_at)
        audit_text = " ".join(SocialConnectionAuditLog.objects.values_list("failure_reason", flat=True))
        self.assertNotIn("super-secret-code", audit_text)


@override_settings(
    SOCIAL_PUBLISHING_ENABLED=True,
    SOCIAL_PUBLISHING_FACEBOOK_CONNECTION_ENABLED=True,
    SOCIAL_PUBLISHING_FACEBOOK_PUBLISHING_ENABLED=False,
    SOCIAL_PUBLISHING_META_APP_ID="meta-app-id",
    SOCIAL_PUBLISHING_META_APP_SECRET="meta-app-secret",
)
class FacebookPageConnectionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("facebook-admin@example.com", password="x", is_staff=True, username="facebook-admin")
        self.client.force_login(self.user)

    def begin(self):
        response = self.client.get(reverse("social_publishing_web:connect", kwargs={"platform": "facebook"}),
                                   {"role": "admin"})
        self.assertEqual(response.status_code, 302)
        return parse_qs(urlparse(response.url).query)["state"][0]

    @patch("social_publishing.web_views.discover_facebook_pages")
    @patch("social_publishing.web_views.discover_facebook_granted_scopes")
    @patch("social_publishing.web_views.resolve_facebook_user_identity")
    @patch("social_publishing.web_views.exchange_facebook_long_lived_token")
    @patch("social_publishing.web_views.exchange_code")
    def callback(self, pages, exchange, long_lived, identity, granted_scopes, discovery):
        exchange.return_value = {"access_token": "user-token", "expires_in": 3600}
        long_lived.return_value = {"access_token": "long-user-token", "expires_in": 5184000}
        identity.return_value = {"id": "facebook-user-1", "name": "Founder"}
        granted_scopes.return_value = [
            "pages_show_list", "pages_read_engagement", "pages_manage_posts"
        ]
        discovery.return_value = pages
        state = self.begin()
        return self.client.get(reverse("social_publishing_web:oauth_callback", kwargs={"platform": "facebook"}),
                               {"state": state, "code": "provider-code"})

    def test_one_page_still_requires_explicit_selection_and_connects_selected_page(self):
        response = self.callback([{"id": "page-1", "name": "Arolana Page", "tasks": ["CREATE_CONTENT"],
                                   "access_token": "page-token"}])
        self.assertRedirects(response, response.url, fetch_redirect_response=False)
        self.assertIn("/facebook/select/", response.url)
        selection = parse_qs(urlparse(response.url).query)["selection"][0]
        get_page = self.client.get(response.url)
        self.assertContains(get_page, "Arolana Page")
        self.assertNotContains(get_page, "page-token")
        post = self.client.post(reverse("social_publishing_web:facebook_select"),
                                {"selection": selection, "page_id": "page-1"})
        self.assertEqual(post.status_code, 302)
        account = SocialAccount.objects.get(user=self.user, owner_role="admin", platform="facebook")
        self.assertEqual(account.external_account_id, "page-1")
        self.assertEqual(decrypt_token(account.access_token_encrypted), "page-token")
        self.assertIn("pages_manage_posts", account.scopes)

    def test_multiple_pages_never_silently_select_first_and_cross_selection_is_rejected(self):
        response = self.callback([
            {"id": "p1", "name": "One", "access_token": "token-1", "tasks": ["CREATE_CONTENT"]},
            {"id": "p2", "name": "Two", "access_token": "token-2", "tasks": ["CREATE_CONTENT"]},
        ])
        self.assertFalse(SocialAccount.objects.filter(platform="facebook").exists())
        selection = parse_qs(urlparse(response.url).query)["selection"][0]
        rejected = self.client.post(reverse("social_publishing_web:facebook_select"),
                                    {"selection": selection, "page_id": "unverified-page"})
        self.assertEqual(rejected.status_code, 400)

    def test_zero_pages_is_safe_and_creates_no_account(self):
        response = self.callback([])
        page = self.client.get(response.url)
        self.assertContains(page, "did not return any manageable Facebook Pages")
        self.assertFalse(SocialAccount.objects.filter(platform="facebook").exists())

    def test_page_selection_is_bound_to_original_web_user_and_role(self):
        response = self.callback([{"id": "page-bound", "name": "Bound Page", "tasks": ["CREATE_CONTENT"],
                                   "access_token": "bound-token"}])
        selection = parse_qs(urlparse(response.url).query)["selection"][0]
        other = get_user_model().objects.create_user("phase2a-other-admin@example.com", password="x", is_staff=True,
                                                     username="phase2a-other-admin")
        self.client.force_login(other)
        denied = self.client.post(reverse("social_publishing_web:facebook_select"),
                                  {"selection": selection, "page_id": "page-bound"})
        self.assertEqual(denied.status_code, 403)
        self.assertFalse(SocialAccount.objects.filter(user=other, platform="facebook").exists())

    def test_reconnect_updates_exact_existing_role_account(self):
        existing = SocialAccount.objects.create(
            user=self.user, owner_role="admin", platform="facebook", status="expired",
            external_account_id="old-page", access_token_encrypted=encrypt_token("old-token"),
        )
        response = self.callback([{"id": "new-page", "name": "Replacement Page", "tasks": ["CREATE_CONTENT"],
                                   "access_token": "replacement-token"}])
        selection = parse_qs(urlparse(response.url).query)["selection"][0]
        self.client.post(reverse("social_publishing_web:facebook_select"),
                         {"selection": selection, "page_id": "new-page"})
        existing.refresh_from_db()
        self.assertEqual(existing.external_account_id, "new-page")
        self.assertEqual(existing.status, "connected")
        self.assertEqual(SocialAccount.objects.filter(user=self.user, owner_role="admin", platform="facebook").count(), 1)

    @patch("social_publishing.web_views.exchange_code", side_effect=RuntimeError("Facebook token exchange failed (400)."))
    def test_token_exchange_failure_is_safe_and_audited(self, _exchange):
        state = self.begin()
        response = self.client.get(reverse("social_publishing_web:oauth_callback", kwargs={"platform": "facebook"}),
                                   {"state": state, "code": "never-log-this-code"})
        self.assertEqual(response.status_code, 302)
        audit = SocialConnectionAuditLog.objects.get(event="token_exchange_failed")
        self.assertEqual(audit.failure_reason, "RuntimeError")
        self.assertNotIn(b"never-log-this-code", response.content)

    @patch("social_publishing.api_views.revoke_facebook_access", side_effect=RuntimeError("secret provider detail"))
    def test_revoke_failure_is_audited_safely_and_local_disconnect_succeeds(self, _revoke):
        account = SocialAccount.objects.create(user=self.user, owner_role="admin", platform="facebook",
                                               external_account_id="page-9", access_token_encrypted=encrypt_token("secret-token"))
        response = self.client.delete(reverse("social_publishing:account_disconnect", kwargs={"platform": "facebook"}),
                                      {"role": "admin"}, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(SocialAccount.objects.filter(pk=account.pk).exists())
        audit = SocialConnectionAuditLog.objects.get(event="provider_revoke_failed")
        self.assertEqual(audit.failure_reason, "RuntimeError")
        self.assertNotIn("secret", audit.failure_reason)


class SocialTokenKeyCompatibilityTests(TestCase):
    def test_dedicated_key_can_read_existing_secret_key_ciphertext(self):
        with self.settings(SOCIAL_PUBLISHING_TOKEN_KEY=""):
            legacy = encrypt_token("existing-instagram-token")
        from cryptography.fernet import Fernet
        with self.settings(SOCIAL_PUBLISHING_TOKEN_KEY=Fernet.generate_key().decode("ascii")):
            self.assertEqual(decrypt_token(legacy), "existing-instagram-token")


@override_settings(
    SOCIAL_PUBLISHING_ENABLED=True,
    SOCIAL_PUBLISHING_FACEBOOK_CONNECTION_ENABLED=True,
    SOCIAL_PUBLISHING_FACEBOOK_PUBLISHING_ENABLED=True,
    SOCIAL_PUBLISHING_META_APP_ID="meta-app-id",
    SOCIAL_PUBLISHING_META_APP_SECRET="meta-app-secret",
)
class FacebookVendorReconnectReturnTests(TestCase):
    """Regression coverage for the OAuth -> Page selection return handoff."""

    def setUp(self):
        from vendors.models import VendorProfile

        self.user = get_user_model().objects.create_user(
            username="facebook-return-vendor", email="facebook-return@example.com"
        )
        VendorProfile.objects.create(
            user=self.user,
            store_name="Facebook Return Vendor",
            store_slug="facebook-return-vendor",
            description="OAuth return fixture",
            approval_status="approved",
            is_active=True,
        )
        self.client.force_login(self.user)

    def _selection_state(self, return_target, scopes=None):
        session = self.client.session
        session.save()
        state, _ = create_oauth_state(
            user=self.user,
            owner_role="vendor",
            platform="facebook",
            session_identity=session.session_key,
            return_target=return_target,
        )
        state.used_at = timezone.now()
        state.pending_scopes = scopes or [
            "pages_show_list", "pages_read_engagement", "pages_manage_posts"
        ]
        state.pending_destinations = [{
            "id": "page-6223", "name": "Ifexes.com", "tasks": ["CREATE_CONTENT"],
            "authorizing_user_id": "facebook-user-1",
            "access_token_encrypted": encrypt_token("page-token"),
        }]
        state.save(update_fields=["used_at", "pending_scopes", "pending_destinations"])
        return signing.dumps(
            {"state_id": state.pk, "user_id": self.user.pk}, salt=FACEBOOK_SELECTION_SALT
        )

    def _select_page(self, return_target, scopes=None):
        selection = self._selection_state(return_target, scopes=scopes)
        return self.client.post(
            reverse("social_publishing_web:facebook_select"),
            {"selection": selection, "page_id": "page-6223"},
        )

    @patch("social_publishing.api_views.social_publishing_access")
    def test_launch_preserves_same_origin_absolute_add_product_url_as_local_path(self, mock_access):
        mock_access.return_value = SimpleNamespace(allowed=True, tier="enterprise", reason="")
        response = self.client.post(
            reverse("social_publishing:account_connect_launch", kwargs={"platform": "facebook"}),
            {
                "role": "vendor",
                "return_url": "http://testserver/dashboard/vendor/product/add/",
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        launch = parse_qs(urlparse(response.data["authorization_url"]).query)["launch"][0]
        payload = signing.loads(launch, salt="arolana.social-publishing.launch.v1", max_age=600)
        self.assertEqual(payload["return_url"], "/dashboard/vendor/product/add/")

    @patch("social_publishing.web_views.discover_facebook_pages")
    @patch("social_publishing.web_views.discover_facebook_granted_scopes")
    @patch("social_publishing.web_views.resolve_facebook_user_identity")
    @patch("social_publishing.web_views.exchange_facebook_long_lived_token")
    @patch("social_publishing.web_views.exchange_code")
    @patch("social_publishing.web_views.social_publishing_access")
    @patch("social_publishing.api_views.social_publishing_access")
    def test_add_product_reconnect_returns_after_oauth_and_page_selection(
        self, api_access, web_access, exchange, long_lived, identity, granted_scopes, pages
    ):
        allowed = SimpleNamespace(allowed=True, tier="enterprise", reason="")
        api_access.return_value = allowed
        web_access.return_value = allowed
        exchange.return_value = {"access_token": "short-lived", "expires_in": 3600}
        long_lived.return_value = {"access_token": "long-lived", "expires_in": 5184000}
        identity.return_value = {"id": "facebook-user-1", "name": "Vendor"}
        granted_scopes.return_value = [
            "pages_show_list", "pages_read_engagement", "pages_manage_posts"
        ]
        pages.return_value = [{
            "id": "page-6223", "name": "Ifexes.com", "tasks": ["CREATE_CONTENT"],
            "access_token": "page-token",
        }]
        target = "/dashboard/vendor/product/add/"
        launch_response = self.client.post(
            reverse("social_publishing:account_connect_launch", kwargs={"platform": "facebook"}),
            {"role": "vendor", "return_url": f"http://testserver{target}"},
            content_type="application/json",
        )
        self.assertEqual(launch_response.status_code, 200)
        provider_redirect = self.client.get(launch_response.data["authorization_url"])
        state = parse_qs(urlparse(provider_redirect.url).query)["state"][0]
        callback = self.client.get(
            reverse("social_publishing_web:oauth_callback", kwargs={"platform": "facebook"}),
            {"state": state, "code": "provider-code"},
        )
        selection = parse_qs(urlparse(callback.url).query)["selection"][0]
        complete = self.client.post(
            reverse("social_publishing_web:facebook_select"),
            {"selection": selection, "page_id": "page-6223"},
        )
        self.assertRedirects(
            complete, f"{target}?status=connected&platform=facebook",
            fetch_redirect_response=False,
        )

    def test_add_and_edit_product_returns_survive_page_selection(self):
        for target in (
            "/dashboard/vendor/product/add/",
            "/dashboard/vendor/products/42/edit/",
        ):
            with self.subTest(target=target):
                response = self._select_page(target)
                self.assertRedirects(
                    response, f"{target}?status=connected&platform=facebook",
                    fetch_redirect_response=False,
                )

    def test_normal_social_accounts_connection_keeps_social_accounts_return(self):
        response = self._select_page("")
        self.assertRedirects(
            response,
            f"{reverse('social_publishing_web:accounts')}?role=vendor",
            fetch_redirect_response=False,
        )

    def test_external_return_target_is_rejected_by_page_selection(self):
        response = self._select_page("https://evil.example/steal")
        self.assertRedirects(
            response,
            f"{reverse('social_publishing_web:accounts')}?role=vendor",
            fetch_redirect_response=False,
        )

    def test_selected_page_persists_meta_granted_scopes_and_becomes_ready(self):
        response = self._select_page("/dashboard/vendor/product/add/")
        self.assertEqual(response.status_code, 302)
        account = SocialAccount.objects.get(
            user=self.user, owner_role="vendor", platform=SocialPlatform.FACEBOOK
        )
        self.assertEqual(
            account.scopes,
            ["pages_show_list", "pages_read_engagement", "pages_manage_posts"],
        )
        status = self.client.get(
            reverse("social_publishing:accounts_status"), {"role": "vendor"}
        )
        facebook = next(row for row in status.data["platforms"] if row["platform"] == "facebook")
        self.assertTrue(facebook["publishing_ready"])

    def test_connected_page_without_meta_posting_scope_remains_not_ready(self):
        self._select_page(
            "/dashboard/vendor/product/add/",
            scopes=["pages_show_list", "pages_read_engagement"],
        )
        status = self.client.get(
            reverse("social_publishing:accounts_status"), {"role": "vendor"}
        )
        facebook = next(row for row in status.data["platforms"] if row["platform"] == "facebook")
        self.assertTrue(facebook["connected"])
        self.assertFalse(facebook["publishing_ready"])
