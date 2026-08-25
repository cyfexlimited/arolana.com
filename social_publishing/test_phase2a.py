from datetime import timedelta
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import signing
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .connection_security import SocialOAuthStateError, consume_oauth_state, create_oauth_state
from .crypto import decrypt_token, encrypt_token
from .models import SocialAccount, SocialConnectionAuditLog, SocialOAuthState
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
    @patch("social_publishing.web_views.resolve_facebook_user_identity")
    @patch("social_publishing.web_views.exchange_facebook_long_lived_token")
    @patch("social_publishing.web_views.exchange_code")
    def callback(self, pages, exchange, long_lived, identity, discovery):
        exchange.return_value = {"access_token": "user-token", "expires_in": 3600}
        long_lived.return_value = {"access_token": "long-user-token", "expires_in": 5184000}
        identity.return_value = {"id": "facebook-user-1", "name": "Founder"}
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
