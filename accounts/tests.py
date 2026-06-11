from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.adapters import CustomAccountAdapter
from accounts.models import User
from accounts.utils.email_subjects import format_arolana_subject
from accounts.utils.messaging import send_registration_messages_once
from accounts.utils.otp_utils import send_otp_email
from accounts.views import (
    EMAIL_VERIFICATION_NEXT_SESSION_KEY,
    EMAIL_VERIFICATION_USER_SESSION_KEY,
)


class EmailSubjectTests(TestCase):
    def test_brand_prefix_is_normalized_to_one_copy(self):
        self.assertEqual(
            format_arolana_subject("[Arolana] [Arolana] Confirm Your Email"),
            "[Arolana] Confirm Your Email",
        )
        self.assertEqual(
            CustomAccountAdapter().format_email_subject("[Arolana] Welcome"),
            "[Arolana] Welcome",
        )

    @override_settings(
        EMAIL_CONFIGURED=True,
        DEFAULT_FROM_EMAIL="noreply@arolana.com",
    )
    @patch("accounts.utils.otp_utils.send_mail")
    def test_otp_email_uses_one_clean_brand_prefix(self, send_mail_mock):
        user = User.objects.create_user(
            username="subject-user",
            email="subject@example.org",
            password="StrongPass1!",
        )

        sent = send_otp_email(
            user.email,
            "123456",
            otp_type="email",
            user=user,
        )

        self.assertTrue(sent)
        self.assertEqual(
            send_mail_mock.call_args.args[0],
            "[Arolana] Email verification code",
        )


class RegistrationVerificationFlowTests(TestCase):
    @patch("accounts.views.send_registration_messages_once")
    @patch("accounts.views.create_otp", return_value=object())
    @patch(
        "accounts.views.normalize_and_validate_real_email",
        side_effect=lambda email: email,
    )
    def test_registration_waits_for_email_verification_before_welcome(
        self,
        _validate_email,
        _create_otp,
        send_welcome,
    ):
        response = self.client.post(
            reverse("accounts:register"),
            {
                "email": "new-user@example.org",
                "username": "new_user",
                "password": "StrongPass1!",
                "confirm_password": "StrongPass1!",
                "first_name": "New",
                "last_name": "User",
                "account_type": "customer",
                "terms": "on",
            },
            secure=True,
        )

        self.assertRedirects(
            response,
            reverse("accounts:verify_email"),
            fetch_redirect_response=False,
        )
        user = User.objects.get(email="new-user@example.org")
        self.assertFalse(user.email_verified)
        send_welcome.assert_not_called()

    @patch("accounts.views.create_notification")
    @patch("accounts.views.send_registration_messages_once")
    @patch("accounts.views.verify_otp", return_value=(True, "Verified"))
    def test_successful_verification_sends_welcome_after_marking_verified(
        self,
        _verify_otp,
        send_welcome,
        _create_notification,
    ):
        user = User.objects.create_user(
            username="pending-user",
            email="pending@example.org",
            password="StrongPass1!",
        )
        session = self.client.session
        session[EMAIL_VERIFICATION_USER_SESSION_KEY] = user.pk
        session[EMAIL_VERIFICATION_NEXT_SESSION_KEY] = "home"
        session.save()

        response = self.client.post(
            reverse("accounts:verify_email"),
            {"otp_code": "123456"},
            secure=True,
        )

        user.refresh_from_db()
        self.assertTrue(user.email_verified)
        send_welcome.assert_called_once()
        self.assertTrue(send_welcome.call_args.args[0].email_verified)
        self.assertRedirects(response, reverse("home"), fetch_redirect_response=False)

    @patch("accounts.utils.messaging.send_registration_messages", return_value=1)
    def test_registration_messages_are_claimed_only_once(self, send_messages):
        user = User.objects.create_user(
            username="once-user",
            email="once@example.org",
            password="StrongPass1!",
            email_verified=True,
        )

        self.assertEqual(send_registration_messages_once(user), 1)
        self.assertEqual(send_registration_messages_once(user), 0)

        user.refresh_from_db()
        self.assertIsNotNone(user.registration_messages_sent_at)
        send_messages.assert_called_once()
