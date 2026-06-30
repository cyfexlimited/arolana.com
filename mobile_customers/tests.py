import json
from unittest.mock import patch

from django.test import TestCase

from accounts.models import User, UserOTP
from mobile_customers.models import MobileCustomer


class MobileCustomerWebAccountAuthenticationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="investor.customer@arolana.com",
            username="investor_customer",
            password="StrongPassword123!",
            first_name="Investor",
            last_name="Customer",
            phone_number="+2348012345678",
            email_verified=True,
        )

    def post_json(self, path, payload):
        return self.client.post(
            path,
            data=json.dumps(payload),
            content_type="application/json",
        )

    @patch("accounts.utils.otp_utils.send_otp_email", return_value=True)
    def test_web_account_login_requires_otp_and_links_mobile_profile(self, _send_email):
        login = self.post_json(
            "/api/mobile/customer/account-login/",
            {
                "identifier": " INVESTOR.CUSTOMER@AROLANA.COM ",
                "password": "StrongPassword123!",
            },
        )

        self.assertEqual(login.status_code, 200)
        self.assertTrue(login.json()["otp_required"])
        self.assertEqual(MobileCustomer.objects.count(), 0)

        otp = UserOTP.objects.get(user=self.user, otp_type="login", is_used=False)
        verified = self.post_json(
            "/api/mobile/customer/account-login/verify-otp/",
            {
                "challenge_token": login.json()["challenge_token"],
                "otp_code": otp.otp_code,
            },
        )

        self.assertEqual(verified.status_code, 200)
        self.assertFalse(verified.json()["otp_required"])
        self.assertTrue(verified.json()["api_token"])
        customer = MobileCustomer.objects.get(user=self.user)
        self.assertEqual(customer.email, self.user.email)
        self.assertEqual(customer.phone_number, str(self.user.phone_number))

    def test_invalid_web_password_does_not_create_mobile_profile(self):
        response = self.post_json(
            "/api/mobile/customer/account-login/",
            {
                "identifier": self.user.email,
                "password": "wrong-password",
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(MobileCustomer.objects.count(), 0)

    def test_profile_endpoint_accepts_bearer_mobile_token(self):
        customer = MobileCustomer.objects.create(
            user=self.user,
            full_name=self.user.get_full_name(),
            phone_number=str(self.user.phone_number),
            email=self.user.email,
            api_token="secure-bearer-token",
        )

        response = self.client.get(
            "/api/mobile/customer/profile/",
            HTTP_AUTHORIZATION=f"Bearer {customer.api_token}",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["customer"]["user_id"], self.user.id)

    def test_customer_language_setting_persists_and_is_returned(self):
        customer = MobileCustomer.objects.create(
            user=self.user,
            full_name=self.user.get_full_name(),
            phone_number=str(self.user.phone_number),
            email=self.user.email,
            api_token="investor-settings-token",
        )
        response = self.client.patch(
            "/api/mobile/settings/",
            data=json.dumps(
                {
                    "phone_number": customer.phone_number,
                    "api_token": customer.api_token,
                    "preferred_language": "yoruba",
                    "notification_preferences": {"orders": True},
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["preferred_language"], "yoruba")
        customer.refresh_from_db()
        self.assertEqual(customer.preferred_language, "yoruba")
        self.assertEqual(customer.notification_preferences, {"orders": True})

        fetched = self.client.get(
            "/api/mobile/settings/",
            {
                "phone_number": customer.phone_number,
                "api_token": customer.api_token,
            },
        )
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json()["preferred_language"], "yoruba")

    @patch("accounts.utils.otp_utils.send_otp_email", return_value=True)
    def test_native_registration_creates_real_user_then_verifies_otp(self, _send_email):
        registration = self.post_json(
            "/api/mobile/auth/register/",
            {
                "full_name": "Native Arolana Customer",
                "email": "native.arolana.customer@gmail.com",
                "phone_number": "+2348098765432",
                "password": "StrongNative123!",
                "confirm_password": "StrongNative123!",
                "terms_accepted": True,
            },
        )

        self.assertEqual(registration.status_code, 201)
        self.assertTrue(registration.json()["otp_required"])
        user = User.objects.get(email="native.arolana.customer@gmail.com")
        self.assertEqual(user.user_type, "customer")
        self.assertFalse(user.email_verified)
        self.assertEqual(MobileCustomer.objects.filter(user=user).count(), 0)

        otp = UserOTP.objects.get(user=user, otp_type="email", is_used=False)
        verified = self.post_json(
            "/api/mobile/auth/verify-otp/",
            {
                "challenge_token": registration.json()["challenge_token"],
                "otp_code": otp.otp_code,
            },
        )

        self.assertEqual(verified.status_code, 200)
        user.refresh_from_db()
        self.assertTrue(user.email_verified)
        self.assertTrue(verified.json()["api_token"])
        self.assertTrue(MobileCustomer.objects.filter(user=user).exists())
