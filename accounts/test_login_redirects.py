import time
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlencode

from allauth.account.models import EmailAddress
from allauth.core import context as allauth_context
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.models import SocialAccount, SocialLogin
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpResponse, HttpResponseRedirect
from django.template.defaultfilters import urlencode as template_urlencode
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from accounts.adapters import CustomAccountAdapter, CustomSocialAccountAdapter
from accounts.models import User
from accounts.redirects import (
    AUTH_HANDOFF_SESSION_KEYS,
    PENDING_LOGIN_REDIRECT_CREATED_AT_SESSION_KEY,
    PENDING_LOGIN_REDIRECT_SESSION_KEY,
    role_login_redirect_url,
    safe_login_redirect_url,
)
from accounts.views import (
    EMAIL_VERIFICATION_NEXT_SESSION_KEY,
    EMAIL_VERIFICATION_USER_SESSION_KEY,
)


class SafeLoginRedirectTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.secure_request = self.factory.get("/", secure=True)

    def test_public_page_destinations_and_query_fragment_are_preserved(self):
        destinations = (
            "/products/logitech-rally-bar/?variant=graphite",
            "/projects/boardroom-installation/?view=gallery#quote-request",
            "/vendors/acme-av/?tab=reviews",
            "/installers/bright-systems/#contact-provider",
            "/orders/checkout/?step=delivery",
        )

        for destination in destinations:
            with self.subTest(destination=destination):
                self.assertEqual(
                    safe_login_redirect_url(self.secure_request, destination),
                    destination,
                )

    def test_external_protocol_relative_and_malformed_destinations_are_rejected(self):
        destinations = (
            "https://malicious-site.example/phish",
            "//malicious-site.example/phish",
            "https:///missing-host",
            "javascript:alert(1)",
            "relative/path",
            "///malicious-site.example",
            "https://[broken-host",
            "/bad\x00path",
        )

        for destination in destinations:
            with self.subTest(destination=destination):
                self.assertIsNone(
                    safe_login_redirect_url(self.secure_request, destination)
                )

    def test_same_host_https_and_explicit_arolana_host_are_accepted(self):
        same_host = "https://testserver/products/camera/?variant=black"
        canonical_host = "https://arolana.com/projects/example/"

        self.assertEqual(
            safe_login_redirect_url(self.secure_request, same_host),
            same_host,
        )
        self.assertEqual(
            safe_login_redirect_url(self.secure_request, canonical_host),
            canonical_host,
        )
        self.assertIsNone(
            safe_login_redirect_url(
                self.secure_request,
                "http://testserver/products/camera/",
            )
        )

    @override_settings(
        ALLOWED_HOSTS=["testserver", ".railway.app"],
        LOGIN_REDIRECT_ALLOWED_HOSTS=["arolana.com"],
    )
    def test_allauth_adapter_does_not_trust_wildcard_allowed_hosts(self):
        with allauth_context.request_context(self.secure_request):
            adapter = CustomAccountAdapter()
            self.assertFalse(
                adapter.is_safe_url(
                    "https://attacker-controlled.up.railway.app/phish"
                )
            )
            self.assertTrue(adapter.is_safe_url("/products/safe/"))

    def test_authentication_handoff_destinations_are_rejected_without_loops(self):
        destinations = (
            reverse("accounts:login"),
            reverse("accounts:login").rstrip("/"),
            f"{reverse('accounts:login')}?next=/products/safe/",
            reverse("accounts:verify_2fa"),
            reverse("accounts:verify_email"),
            reverse("accounts:logout"),
        )

        for destination in destinations:
            with self.subTest(destination=destination):
                self.assertIsNone(
                    safe_login_redirect_url(self.secure_request, destination)
                )


@override_settings(AROLANA_RATE_LIMIT_ENABLED=False)
class LoginRedirectFlowTests(TestCase):
    password = "StrongPass1!"

    def create_user(self, **overrides):
        values = {
            "username": "redirect-user",
            "email": "redirect@example.org",
            "password": self.password,
            "email_verified": True,
        }
        values.update(overrides)
        return User.objects.create_user(**values)

    def complete_password_and_otp_login(
        self,
        user,
        *,
        post_next=None,
        get_next=None,
    ):
        login_url = reverse("accounts:login")
        if get_next:
            login_url = f"{login_url}?{urlencode({'next': get_next})}"

        data = {
            "identifier": user.email,
            "password": self.password,
        }
        if post_next is not None:
            data["next"] = post_next

        with patch("accounts.views.create_otp", return_value=object()):
            response = self.client.post(login_url, data, secure=True)
        self.assertRedirects(
            response,
            reverse("accounts:verify_2fa"),
            fetch_redirect_response=False,
        )

        with (
            patch("accounts.views.verify_otp", return_value=(True, "Verified")),
            patch("accounts.views.create_notification"),
            patch("accounts.views.log_user_activity"),
        ):
            return self.client.post(
                reverse("accounts:verify_2fa"),
                {"otp_code": "123456"},
                secure=True,
            )

    def test_post_next_has_priority_over_get_and_session(self):
        user = self.create_user()
        session = self.client.session
        session[PENDING_LOGIN_REDIRECT_SESSION_KEY] = "/from-session/"
        session.save()

        response = self.complete_password_and_otp_login(
            user,
            post_next="/from-post/?tab=quotes",
            get_next="/from-get/",
        )

        self.assertRedirects(
            response,
            "/from-post/?tab=quotes",
            fetch_redirect_response=False,
        )
        self.assertNotIn(
            PENDING_LOGIN_REDIRECT_SESSION_KEY,
            self.client.session,
        )

    def test_get_next_is_retained_in_session_when_post_omits_hidden_field(self):
        user = self.create_user()
        destination = "/products/projector/?variant=white"
        session = self.client.session
        session[PENDING_LOGIN_REDIRECT_SESSION_KEY] = "/stale-session-page/"
        session.save()
        response = self.client.get(
            f"{reverse('accounts:login')}?{urlencode({'next': destination})}",
            secure=True,
        )
        self.assertEqual(response.status_code, 200)

        response = self.complete_password_and_otp_login(user)
        self.assertRedirects(
            response,
            destination,
            fetch_redirect_response=False,
        )

    def test_invalid_credentials_preserve_destination(self):
        user = self.create_user()
        destination = "/orders/checkout/?step=payment"
        self.client.get(
            f"{reverse('accounts:login')}?{urlencode({'next': destination})}",
            secure=True,
        )

        response = self.client.post(
            reverse("accounts:login"),
            {
                "identifier": user.email,
                "password": "WrongPass1!",
            },
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.client.session[PENDING_LOGIN_REDIRECT_SESSION_KEY],
            destination,
        )
        self.assertContains(response, f'value="{destination}"', html=False)

    def test_login_template_carries_next_to_auth_handoffs_and_social_login(self):
        destination = "/products/camera/?variant=black"
        login_url = (
            f"{reverse('accounts:login')}?"
            f"{urlencode({'next': destination})}"
        )
        provider = SimpleNamespace(
            get_login_url=lambda _request, **query: (
                f"/accounts/google/login/?{urlencode(query)}"
            )
        )

        with (
            patch(
                "accounts.views.get_social_apps_context",
                return_value={
                    "google_app_exists": True,
                    "facebook_app_exists": False,
                },
            ),
            patch(
                "accounts.adapters.CustomSocialAccountAdapter.get_provider",
                return_value=provider,
            ),
        ):
            response = self.client.get(login_url, secure=True)

        self.assertContains(response, f'name="next" value="{destination}"')
        template_encoded_next = template_urlencode(destination)
        self.assertContains(
            response,
            f'{reverse("accounts:register")}?next={template_encoded_next}',
        )
        self.assertContains(
            response,
            f'{reverse("accounts:forgot_password")}?next={template_encoded_next}',
        )
        self.assertContains(
            response,
            "process=login&amp;next=%2Fproducts%2Fcamera%2F%3Fvariant%3Dblack",
        )

    def test_allauth_signup_and_password_reset_aliases_preserve_next_query(self):
        destination = "/orders/checkout/?step=payment"
        query = urlencode({"next": destination})

        signup_response = self.client.get(
            f"{reverse('account_signup')}?{query}",
            secure=True,
        )
        reset_response = self.client.get(
            f"{reverse('account_reset_password')}?{query}",
            secure=True,
        )

        self.assertRedirects(
            signup_response,
            f"{reverse('accounts:register')}?{query}",
            fetch_redirect_response=False,
        )
        self.assertRedirects(
            reset_response,
            f"{reverse('accounts:forgot_password')}?{query}",
            fetch_redirect_response=False,
        )

    def test_external_next_is_rejected_and_direct_staff_login_uses_admin_fallback(
        self,
    ):
        staff = self.create_user(
            username="staff-user",
            email="staff@example.org",
            is_staff=True,
        )

        response = self.complete_password_and_otp_login(
            staff,
            post_next="https://malicious-site.example/phish",
        )

        self.assertRedirects(
            response,
            reverse("dashboard:admin_home"),
            fetch_redirect_response=False,
        )

    def test_valid_next_overrides_vendor_fallback(self):
        vendor = self.create_user(
            username="vendor-user",
            email="vendor@example.org",
            user_type="vendor",
        )
        destination = "/projects/original-project/#quote-request"

        response = self.complete_password_and_otp_login(
            vendor,
            post_next=destination,
        )

        self.assertRedirects(
            response,
            destination,
            fetch_redirect_response=False,
        )

    def test_direct_vendor_login_uses_vendor_dashboard(self):
        vendor = self.create_user(
            username="direct-vendor",
            email="direct-vendor@example.org",
            user_type="vendor",
        )

        response = self.complete_password_and_otp_login(vendor)

        self.assertRedirects(
            response,
            reverse("dashboard:vendor_home"),
            fetch_redirect_response=False,
        )

    def test_provider_and_rider_role_fallbacks(self):
        provider = SimpleNamespace(
            is_authenticated=True,
            is_staff=False,
            user_type="customer",
            service_provider_profile=object(),
        )
        rider = SimpleNamespace(
            is_authenticated=True,
            is_staff=False,
            user_type="customer",
            rider_profile=object(),
        )

        self.assertEqual(
            role_login_redirect_url(provider),
            reverse("provider_workspace:dashboard"),
        )
        self.assertEqual(
            role_login_redirect_url(rider),
            reverse("deliveries:rider_dashboard"),
        )

    def test_expired_otp_session_keeps_destination_for_fresh_login(self):
        destination = "/accounts/wishlist/?filter=saved"
        session = self.client.session
        session[PENDING_LOGIN_REDIRECT_SESSION_KEY] = destination
        session.save()

        response = self.client.get(reverse("accounts:verify_2fa"), secure=True)

        self.assertRedirects(
            response,
            (
                f"{reverse('accounts:login')}?"
                f"{urlencode({'next': destination})}"
            ),
            fetch_redirect_response=False,
        )
        self.assertEqual(
            self.client.session[PENDING_LOGIN_REDIRECT_SESSION_KEY],
            destination,
        )

    def test_successful_2fa_post_redirects_without_server_error(self):
        user = self.create_user(
            username="otp-success-user",
            email="otp-success@example.org",
        )
        destination = "/dashboard/vendor/quote-requests/"
        session = self.client.session
        session["pre_2fa_user_id"] = user.pk
        session["pre_2fa_remember"] = False
        session[PENDING_LOGIN_REDIRECT_SESSION_KEY] = destination
        session.save()

        with patch("accounts.views.verify_otp", return_value=(True, "Verified")):
            response = self.client.post(
                reverse("accounts:verify_2fa"),
                {"otp_code": "123456"},
                secure=True,
            )

        self.assertRedirects(
            response,
            destination,
            fetch_redirect_response=False,
        )
        self.assertNotIn("pre_2fa_user_id", self.client.session)
        self.assertNotIn("pre_2fa_remember", self.client.session)

    def test_standalone_login_clears_an_abandoned_destination(self):
        user = self.create_user()
        session = self.client.session
        for key in AUTH_HANDOFF_SESSION_KEYS:
            session[key] = "abandoned"
        session[PENDING_LOGIN_REDIRECT_SESSION_KEY] = "/products/abandoned/"
        session.save()

        response = self.client.get(reverse("accounts:login"), secure=True)

        self.assertEqual(response.status_code, 200)
        for key in AUTH_HANDOFF_SESSION_KEYS:
            self.assertNotIn(key, self.client.session)

        response = self.complete_password_and_otp_login(user)
        self.assertRedirects(
            response,
            reverse("home"),
            fetch_redirect_response=False,
        )

    def test_explicit_login_cancellation_clears_partial_auth_but_keeps_next(self):
        destination = "/products/original/?variant=black"
        session = self.client.session
        session[PENDING_LOGIN_REDIRECT_SESSION_KEY] = destination
        session["pre_2fa_user_id"] = 999
        session["pre_2fa_remember"] = True
        session["reset_user_id"] = 999
        session["pending_email_verification_user_id"] = 999
        session["socialaccount_states"] = {"stale": "state"}
        session.save()

        response = self.client.get(
            (
                f"{reverse('accounts:login')}?cancel_auth=1&"
                f"{urlencode({'next': destination})}"
            ),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        session = self.client.session
        self.assertEqual(
            session[PENDING_LOGIN_REDIRECT_SESSION_KEY],
            destination,
        )
        for key in (
            "pre_2fa_user_id",
            "pre_2fa_remember",
            "reset_user_id",
            "pending_email_verification_user_id",
            "socialaccount_states",
        ):
            self.assertNotIn(key, session)

    @override_settings(LOGIN_REDIRECT_SESSION_TTL=60)
    def test_expired_pending_destination_uses_role_fallback(self):
        user = self.create_user(
            username="expired-intent-user",
            email="expired-intent@example.org",
        )
        session = self.client.session
        session[PENDING_LOGIN_REDIRECT_SESSION_KEY] = "/products/expired/"
        session[PENDING_LOGIN_REDIRECT_CREATED_AT_SESSION_KEY] = (
            time.time() - 61
        )
        session.save()

        response = self.complete_password_and_otp_login(user)

        self.assertRedirects(
            response,
            reverse("home"),
            fetch_redirect_response=False,
        )

    def test_logout_clears_pending_destination_and_auth_handoff_state(self):
        session = self.client.session
        for key in AUTH_HANDOFF_SESSION_KEYS:
            session[key] = "/products/stale/" if key.endswith("next") else "stale"
        session.save()

        response = self.client.get(reverse("accounts:logout"), secure=True)

        self.assertEqual(response.status_code, 200)
        for key in AUTH_HANDOFF_SESSION_KEYS:
            self.assertNotIn(key, self.client.session)


@override_settings(AROLANA_RATE_LIMIT_ENABLED=False)
class MultiStepRedirectFlowTests(TestCase):
    password = "StrongPass1!"

    def create_user(self, **overrides):
        values = {
            "username": "handoff-user",
            "email": "handoff@example.org",
            "password": self.password,
            "email_verified": False,
        }
        values.update(overrides)
        return User.objects.create_user(**values)

    def test_email_verification_restores_and_consumes_safe_destination(self):
        user = self.create_user()
        destination = "/products/speaker/#reviews"
        session = self.client.session
        session[EMAIL_VERIFICATION_USER_SESSION_KEY] = user.pk
        session[EMAIL_VERIFICATION_NEXT_SESSION_KEY] = destination
        session[PENDING_LOGIN_REDIRECT_SESSION_KEY] = destination
        session.save()

        with (
            patch("accounts.views.verify_otp", return_value=(True, "Verified")),
            patch("accounts.views.send_registration_messages_once"),
            patch("accounts.views.create_notification"),
            patch("accounts.views.log_user_activity"),
        ):
            response = self.client.post(
                reverse("accounts:verify_email"),
                {
                    "otp_code": "123456",
                    "next": destination,
                },
                secure=True,
            )

        self.assertRedirects(
            response,
            destination,
            fetch_redirect_response=False,
        )
        session = self.client.session
        self.assertNotIn(PENDING_LOGIN_REDIRECT_SESSION_KEY, session)
        self.assertNotIn(EMAIL_VERIFICATION_NEXT_SESSION_KEY, session)
        self.assertNotIn(EMAIL_VERIFICATION_USER_SESSION_KEY, session)

    def test_email_verification_rejects_external_legacy_destination(self):
        user = self.create_user(
            username="unsafe-email-user",
            email="unsafe-email@example.org",
        )
        session = self.client.session
        session[EMAIL_VERIFICATION_USER_SESSION_KEY] = user.pk
        session[EMAIL_VERIFICATION_NEXT_SESSION_KEY] = (
            "https://malicious-site.example/phish"
        )
        session.save()

        with (
            patch("accounts.views.verify_otp", return_value=(True, "Verified")),
            patch("accounts.views.send_registration_messages_once"),
            patch("accounts.views.create_notification"),
            patch("accounts.views.log_user_activity"),
        ):
            response = self.client.post(
                reverse("accounts:verify_email"),
                {"otp_code": "123456"},
                secure=True,
            )

        self.assertRedirects(
            response,
            reverse("home"),
            fetch_redirect_response=False,
        )

    def test_password_reset_handoff_keeps_login_destination(self):
        user = self.create_user(
            username="reset-user",
            email="reset@example.org",
            email_verified=True,
        )
        destination = "/orders/checkout/?step=review"
        forgot_url = (
            f"{reverse('accounts:forgot_password')}?"
            f"{urlencode({'next': destination})}"
        )

        self.client.get(forgot_url, secure=True)
        with patch("accounts.views.create_otp", return_value=object()):
            response = self.client.post(
                reverse("accounts:forgot_password"),
                {"identifier": user.email},
                secure=True,
            )
        self.assertRedirects(
            response,
            reverse("accounts:reset_password_verify"),
            fetch_redirect_response=False,
        )

        with (
            patch("accounts.views.verify_otp", return_value=(True, "Verified")),
            patch("accounts.views.create_notification"),
        ):
            response = self.client.post(
                reverse("accounts:reset_password_verify"),
                {
                    "otp_code": "123456",
                    "new_password": "ChangedPass1!",
                    "confirm_password": "ChangedPass1!",
                },
                secure=True,
            )

        self.assertRedirects(
            response,
            (
                f"{reverse('accounts:login')}?"
                f"{urlencode({'next': destination})}"
            ),
            fetch_redirect_response=False,
        )
        self.assertEqual(
            self.client.session[PENDING_LOGIN_REDIRECT_SESSION_KEY],
            destination,
        )


class SocialLoginRedirectTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username="social-user",
            email="social@example.org",
            password="StrongPass1!",
            email_verified=True,
        )

    def request_with_session(self, next_url=None):
        callback_url = "/accounts/google/login/callback/"
        if next_url:
            callback_url = f"{callback_url}?{urlencode({'next': next_url})}"
        request = self.factory.get(
            callback_url,
            secure=True,
        )
        SessionMiddleware(lambda _request: HttpResponse()).process_request(request)
        request.session.save()
        request._messages = FallbackStorage(request)
        request.user = self.user
        return request

    def google_sociallogin(self, email=None, verified=True, uid="google-uid-1"):
        email = email or self.user.email
        return SocialLogin(
            user=User(email=email, username="google-social-user"),
            account=SocialAccount(
                provider="google",
                uid=uid,
                extra_data={
                    "email": email,
                    "email_verified": verified,
                },
            ),
            email_addresses=[
                EmailAddress(
                    email=email,
                    verified=verified,
                    primary=True,
                )
            ],
        )

    @patch("accounts.adapters.CustomAccountAdapter.add_message")
    @patch("allauth.account.adapter.signals.user_logged_in.send")
    def test_social_state_next_is_restored_and_session_value_is_cleared(
        self,
        _send_signal,
        _add_message,
    ):
        request = self.request_with_session()
        destination = "/vendors/social-vendor/?tab=products"
        sociallogin = SimpleNamespace(
            get_redirect_url=lambda _request: destination
        )

        CustomSocialAccountAdapter().pre_social_login(request, sociallogin)
        self.assertEqual(
            request.session[PENDING_LOGIN_REDIRECT_SESSION_KEY],
            destination,
        )

        response = CustomAccountAdapter().post_login(
            request,
            self.user,
            email_verification=None,
            signal_kwargs={},
            email=self.user.email,
            signup=False,
            redirect_url=destination,
        )

        self.assertEqual(response.url, destination)
        self.assertNotIn(PENDING_LOGIN_REDIRECT_SESSION_KEY, request.session)

    @patch("accounts.adapters.CustomAccountAdapter.add_message")
    @patch("allauth.account.adapter.signals.user_logged_in.send")
    def test_invalid_social_state_cannot_override_safe_stored_intent(
        self,
        _send_signal,
        _add_message,
    ):
        request = self.request_with_session()
        stored_destination = "/projects/original/"
        request.session[PENDING_LOGIN_REDIRECT_SESSION_KEY] = stored_destination
        sociallogin = SimpleNamespace(
            get_redirect_url=lambda _request: (
                "https://malicious-site.example/phish"
            )
        )

        CustomSocialAccountAdapter().pre_social_login(request, sociallogin)
        response = CustomAccountAdapter().post_login(
            request,
            self.user,
            email_verification=None,
            signal_kwargs={},
            email=self.user.email,
            signup=False,
            redirect_url="https://malicious-site.example/phish",
        )

        self.assertEqual(response.url, stored_destination)
        self.assertNotIn(PENDING_LOGIN_REDIRECT_SESSION_KEY, request.session)

    @patch("accounts.adapters.CustomAccountAdapter.add_message")
    @patch("allauth.account.adapter.signals.user_logged_in.send")
    def test_callback_request_next_wins_and_is_still_consumed(
        self,
        _send_signal,
        _add_message,
    ):
        callback_destination = "/orders/checkout/?step=payment"
        social_state_destination = "/products/from-social-state/"
        request = self.request_with_session(callback_destination)
        request.session["reset_user_id"] = self.user.pk
        request.session["pending_email_verification_user_id"] = self.user.pk

        response = CustomAccountAdapter().post_login(
            request,
            self.user,
            email_verification=None,
            signal_kwargs={},
            email=self.user.email,
            signup=False,
            redirect_url=social_state_destination,
        )

        self.assertEqual(response.url, callback_destination)
        self.assertNotIn(PENDING_LOGIN_REDIRECT_SESSION_KEY, request.session)
        self.assertNotIn("reset_user_id", request.session)
        self.assertNotIn(
            "pending_email_verification_user_id",
            request.session,
        )

    @patch("accounts.adapters.perform_login")
    def test_verified_google_email_connects_existing_account_instead_of_signup(
        self,
        perform_login_mock,
    ):
        destination = "/dashboard/vendor/quote-requests/"
        request = self.request_with_session(destination)
        sociallogin = self.google_sociallogin(uid="google-existing-user")
        perform_login_mock.return_value = HttpResponseRedirect(destination)

        with self.assertRaises(ImmediateHttpResponse) as captured:
            CustomSocialAccountAdapter().pre_social_login(request, sociallogin)

        self.assertEqual(captured.exception.response.url, destination)
        perform_login_mock.assert_called_once()

        social_account = SocialAccount.objects.get(
            user=self.user,
            provider="google",
            uid="google-existing-user",
        )
        self.assertEqual(social_account.user, self.user)

        self.user.refresh_from_db()
        self.assertEqual(self.user.google_id, "google-existing-user")
        self.assertTrue(self.user.email_verified)

    @patch("accounts.adapters.perform_login")
    def test_unverified_google_email_does_not_auto_connect_existing_account(
        self,
        perform_login_mock,
    ):
        request = self.request_with_session("/accounts/profile/")
        sociallogin = self.google_sociallogin(
            verified=False,
            uid="google-unverified-user",
        )

        CustomSocialAccountAdapter().pre_social_login(request, sociallogin)

        perform_login_mock.assert_not_called()
        self.assertFalse(
            SocialAccount.objects.filter(
                user=self.user,
                provider="google",
                uid="google-unverified-user",
            ).exists()
        )
