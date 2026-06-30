import json
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from accounts.models import User, UserOTP
from installers.models import ServiceProviderProfile
from notifications.models import Notification
from products.models import Category, Product
from staff_mobile.models import StaffMobileToken
from vendors.models import VendorProfile


class StaffMobileAuthenticationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="admin@arolana.com",
            username="arolana_admin",
            password="StrongPassword123!",
            is_staff=True,
            email_verified=True,
        )

    def post_json(self, path, payload):
        return self.client.post(
            path,
            data=json.dumps(payload),
            content_type="application/json",
        )

    @patch("accounts.utils.otp_utils.send_otp_email", return_value=True)
    def test_login_normalizes_email_and_requires_otp_before_token(self, _send_email):
        response = self.post_json(
            "/api/staff/auth/login/",
            {
                "role": "admin",
                "username": "  ADMIN@AROLANA.COM ",
                "password": "StrongPassword123!",
                "device_name": "Test device",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["otp_required"])
        self.assertNotIn("session", payload)
        self.assertEqual(StaffMobileToken.objects.count(), 0)

        otp = UserOTP.objects.get(user=self.user, otp_type="login", is_used=False)
        verified = self.post_json(
            "/api/staff/auth/verify-otp/",
            {
                "challenge_token": payload["challenge_token"],
                "otp_code": otp.otp_code,
            },
        )

        self.assertEqual(verified.status_code, 200, verified.content)
        verified_payload = verified.json()
        self.assertFalse(verified_payload["otp_required"])
        self.assertEqual(verified_payload["role"], "admin")
        self.assertEqual(verified_payload["approval_status"], "approved")
        self.assertEqual(verified_payload["kyc_status"], "approved")
        self.assertEqual(verified_payload["subscription_status"], "active")
        self.assertEqual(verified_payload["user"]["email"], "admin@arolana.com")
        self.assertEqual(verified_payload["token"], verified_payload["session"]["token"])
        self.assertEqual(verified_payload["session"]["role"], "admin")
        self.assertTrue(verified_payload["session"]["token"])
        self.assertEqual(StaffMobileToken.objects.count(), 1)

        auth_header = {"HTTP_AUTHORIZATION": f"Bearer {verified_payload['token']}"}
        me = self.client.get("/api/staff/auth/me/", **auth_header)
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["user"]["id"], self.user.id)

        logout = self.client.post(
            "/api/staff/auth/logout/",
            data="{}",
            content_type="application/json",
            **auth_header,
        )
        self.assertEqual(logout.status_code, 200)
        self.assertFalse(StaffMobileToken.objects.get().is_active)

    def test_invalid_password_returns_helpful_message(self):
        response = self.post_json(
            "/api/staff/auth/login/",
            {
                "role": "admin",
                "username": "admin@arolana.com",
                "password": "wrong-password",
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json()["message"],
            "Invalid login details. Please check your email/phone and password.",
        )

    def test_staff_auth_compatibility_route_uses_same_login_flow(self):
        response = self.post_json(
            "/api/staff/auth/login/",
            {
                "role": "admin",
                "username": "admin@arolana.com",
                "password": "wrong-password",
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json()["message"],
            "Invalid login details. Please check your email/phone and password.",
        )

    def test_tampered_challenge_does_not_issue_token(self):
        response = self.post_json(
            "/api/staff/auth/verify-otp/",
            {"challenge_token": "tampered", "otp_code": "123456"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(StaffMobileToken.objects.count(), 0)

    @patch("accounts.utils.otp_utils.send_otp_email", return_value=True)
    def test_existing_user_logs_in_then_sets_up_optional_provider_profile(self, _send_email):
        login = self.post_json(
            "/api/staff/auth/login/",
            {
                "role": "provider",
                "username": " ADMIN@AROLANA.COM ",
                "password": "StrongPassword123!",
            },
        )
        self.assertEqual(login.status_code, 200)
        otp = UserOTP.objects.get(user=self.user, otp_type="login", is_used=False)
        verified = self.post_json(
            "/api/staff/auth/verify-otp/",
            {
                "challenge_token": login.json()["challenge_token"],
                "otp_code": otp.otp_code,
            },
        )
        self.assertEqual(verified.status_code, 200, verified.content)
        self.assertTrue(verified.json()["profile_required"])
        token = verified.json()["token"]
        auth_header = {"HTTP_AUTHORIZATION": f"Bearer {token}"}

        before_setup = self.client.get("/api/provider/me/", **auth_header)
        self.assertEqual(before_setup.status_code, 200)
        self.assertTrue(before_setup.json()["profile_required"])
        self.assertIsNone(before_setup.json()["provider"])

        response = self.client.post(
            "/api/provider/register/",
            data=json.dumps({
                "business_name": "Arolana Technical Services",
                "contact_person": "Arolana Admin",
                "provider_type": "installer",
                "phone_number": "+2348000000000",
                "email": "admin@arolana.com",
                "country": "Nigeria",
                "state": "Lagos",
                "city": "Ikeja",
                "address": "11 Test Street",
                "service_coverage": "Lagos",
                "description": "Installation and maintenance services.",
            }),
            content_type="application/json",
            **auth_header,
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(User.objects.filter(email__iexact="admin@arolana.com").count(), 1)
        provider = ServiceProviderProfile.objects.get(user=self.user)
        self.assertEqual(provider.verification_status, ServiceProviderProfile.STATUS_PENDING)

        provider.verification_status = ServiceProviderProfile.STATUS_VERIFIED
        provider.is_verified = True
        provider.is_active = True
        provider.kyc_status = ServiceProviderProfile.KYC_APPROVED
        provider.subscription_status = "active"
        provider.save()

        provider_me = self.client.get("/api/provider/me/", **auth_header)
        self.assertEqual(provider_me.status_code, 200)
        provider_payload = provider_me.json()["provider"]
        self.assertTrue(provider_payload["is_active"])
        self.assertTrue(provider_payload["approval_allows_dashboard"])
        self.assertEqual(provider_payload["verification_status"], "verified")
        self.assertEqual(provider_me.json()["next_action"], "provider_dashboard")

        Notification.send(
            self.user,
            "system",
            "Provider KYC approved",
            "Your provider KYC is approved.",
            metadata={"service_provider_id": provider.id},
        )
        Notification.send(
            self.user,
            "vendor",
            "Vendor product callback",
            "This belongs only in the vendor workspace.",
            metadata={"product_id": 99},
        )
        notices = self.client.get("/api/provider/notifications/", **auth_header)
        self.assertEqual(notices.status_code, 200)
        notice_titles = [item["title"] for item in notices.json()["notifications"]]
        self.assertIn("Provider KYC approved", notice_titles)
        self.assertNotIn("Vendor product callback", notice_titles)

        provider.last_sensitive_update_approved_at = timezone.now()
        provider.save(update_fields=["last_sensitive_update_approved_at", "updated_at"])
        settings = self.client.get("/api/provider/settings/", **auth_header)
        self.assertEqual(settings.status_code, 200)
        self.assertTrue(settings.json()["sensitive_update_locked"])
        self.assertEqual(settings.json()["provider"]["business_name"], provider.business_name)

    @patch("accounts.utils.otp_utils.send_otp_email", return_value=True)
    def test_password_reset_uses_otp_and_revokes_mobile_sessions(self, _send_email):
        session = StaffMobileToken.issue(role="admin", user=self.user, device_name="Old phone")
        started = self.post_json(
            "/api/staff/auth/forgot-password/",
            {"identifier": " ADMIN@AROLANA.COM "},
        )
        self.assertEqual(started.status_code, 200)
        otp = UserOTP.objects.get(user=self.user, otp_type="password_reset", is_used=False)

        reset = self.post_json(
            "/api/staff/auth/reset-password/",
            {
                "challenge_token": started.json()["challenge_token"],
                "otp_code": otp.otp_code,
                "new_password": "NewStrongPassword456!",
            },
        )

        self.assertEqual(reset.status_code, 200)
        self.user.refresh_from_db()
        session.refresh_from_db()
        self.assertTrue(self.user.check_password("NewStrongPassword456!"))
        self.assertFalse(session.is_active)


class VendorProductSubscriptionFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="vendor-limit@arolana.com",
            username="vendor-limit",
            password="StrongPassword123!",
            user_type="vendor",
            email_verified=True,
        )
        self.profile = VendorProfile.objects.create(
            user=self.user,
            store_name="Limit Test Vendor",
            store_slug="limit-test-vendor",
            description="Vendor subscription test",
            approval_status="approved",
            is_verified=True,
            is_active=True,
            address_line_1="1 Arolana Way",
            city="Ikeja",
            state="Lagos",
            country="Nigeria",
            product_limit=1,
        )
        self.category = Category.objects.create(
            name="Vendor API Category",
            slug="vendor-api-category",
        )
        Product.objects.create(
            vendor=self.user,
            category=self.category,
            name="Existing Vendor Product",
            sku="LIMIT-EXISTING",
            description="Existing",
            price=Decimal("100.00"),
            stock_quantity=1,
            approval_status="approved",
            is_active=True,
        )
        self.session = StaffMobileToken.issue(role="vendor", user=self.user)

    def test_product_limit_saves_draft_instead_of_discarding_form(self):
        response = self.client.post(
            "/api/staff/vendor/products/create/",
            data=json.dumps({
                "name": "Preserved Vendor Draft",
                "category_id": self.category.id,
                "description": "The completed product form must be preserved.",
                "price": "250.00",
                "stock_quantity": 4,
            }),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.session.token}",
        )

        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertTrue(payload["draft_saved"])
        self.assertFalse(payload["allowed"])
        self.assertEqual(payload["reason"], "product_limit_reached")
        product = Product.objects.get(name="Preserved Vendor Draft")
        self.assertEqual(product.approval_status, "draft")
        self.assertFalse(product.is_active)
