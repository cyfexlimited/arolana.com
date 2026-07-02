import json

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from notifications.models import Notification
from vendors.models import VendorProfile

from .models import VendorQuoteMessage, VendorQuoteRequest
from .quote_services import (
    notify_new_quote,
    send_admin_customer_message,
    send_admin_vendor_message,
    send_vendor_message,
    serialize_quote,
)
from .views import send_vendor_quote_notifications


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    CONTACT_EMAIL="admin@arolana.test",
    DEFAULT_FROM_EMAIL="Arolana <noreply@arolana.test>",
    SECURE_SSL_REDIRECT=False,
)
class QuoteWorkflowTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username="customer",
            email="customer@example.com",
            password="pass12345",
            first_name="Ada",
        )
        self.vendor_user = User.objects.create_user(
            username="vendor",
            email="vendor@example.com",
            password="pass12345",
            user_type="vendor",
        )
        self.other_vendor_user = User.objects.create_user(
            username="other-vendor",
            email="other@example.com",
            password="pass12345",
            user_type="vendor",
        )
        self.admin = User.objects.create_user(
            username="admin",
            email="admin@example.com",
            password="pass12345",
            is_staff=True,
        )
        self.vendor = VendorProfile.objects.create(
            user=self.vendor_user,
            store_name="Trusted Store",
            store_slug="trusted-store",
            description="Trusted products",
            approval_status="approved",
            is_active=True,
        )
        self.other_vendor = VendorProfile.objects.create(
            user=self.other_vendor_user,
            store_name="Other Store",
            store_slug="other-store",
            description="Other products",
            approval_status="approved",
            is_active=True,
        )
        self.quote = VendorQuoteRequest.objects.create(
            customer=self.customer,
            vendor=self.vendor,
            name="Ada Customer",
            email=self.customer.email,
            phone="+2348000000000",
            subject="Boardroom quote",
            message="Please quote for a full boardroom setup.",
            product_name="Conference system",
        )

    def test_notification_destinations_are_role_specific_and_never_account(self):
        notify_new_quote(self.quote)

        vendor_notice = Notification.objects.get(user=self.vendor_user)
        customer_notice = Notification.objects.get(user=self.customer)
        admin_notice = Notification.objects.get(user=self.admin)

        self.assertEqual(vendor_notice.link, reverse("dashboard:vendor_quote_requests"))
        self.assertEqual(
            customer_notice.link,
            reverse("core:customer_quote_request_detail", args=[self.quote.id]),
        )
        self.assertEqual(
            admin_notice.link,
            reverse("admin:core_vendorquoterequest_change", args=[self.quote.id]),
        )
        self.assertNotIn("/account/", vendor_notice.link + customer_notice.link + admin_notice.link)
        self.assertEqual(customer_notice.metadata["target_screen"], "QuoteDetail")
        self.assertEqual(vendor_notice.metadata["target_screen"], "VendorQuoteDetail")
        self.assertEqual(admin_notice.metadata["target_screen"], "StaffQuoteDetail")

    def test_shared_thread_preserves_visibility_boundaries(self):
        send_admin_vendor_message(self.quote, self.admin, "Please confirm availability.")
        send_vendor_message(self.quote, self.vendor_user, "Available for delivery.", customer_visible=True)
        send_admin_customer_message(self.quote, self.admin, "The vendor confirmed availability.")
        VendorQuoteMessage.objects.create(
            quote_request=self.quote,
            sender=self.admin,
            sender_role="admin",
            message="Internal fraud check complete.",
            is_internal=True,
        )

        customer_payload = serialize_quote(self.quote, "customer")
        vendor_payload = serialize_quote(self.quote, "vendor")
        admin_payload = serialize_quote(self.quote, "admin")

        self.assertEqual([m["message"] for m in customer_payload["messages"]], [
            "Available for delivery.",
            "The vendor confirmed availability.",
        ])
        self.assertNotIn("Internal fraud check complete.", [m["message"] for m in vendor_payload["messages"]])
        self.assertIn("Internal fraud check complete.", [m["message"] for m in admin_payload["messages"]])

    def test_vendor_api_enforces_ownership(self):
        self.client.force_login(self.other_vendor_user)
        response = self.client.post(
            reverse("quotes_api:vendor_response", args=[self.quote.id]),
            data=json.dumps({"message": "I should not see this."}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)

    def test_quote_api_route_is_not_consumed_by_product_slug(self):
        self.client.force_login(self.customer)
        response = self.client.get("/api/quotes/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertTrue(response.json()["success"])

    def test_customer_detail_enforces_ownership(self):
        other_customer = User.objects.create_user(
            username="other-customer",
            email="other-customer@example.com",
            password="pass12345",
        )
        self.client.force_login(other_customer)
        response = self.client.get(
            reverse("core:customer_quote_request_detail", args=[self.quote.id])
        )
        self.assertEqual(response.status_code, 404)

    def test_vendor_web_response_uses_post_redirect_get_and_thread(self):
        self.client.force_login(self.vendor_user)
        response = self.client.post(
            reverse("dashboard:vendor_quote_response", args=[self.quote.id]),
            {"vendor_response": "Fresh response"},
        )
        self.assertRedirects(response, reverse("dashboard:vendor_quote_requests"))
        self.quote.refresh_from_db()
        self.assertEqual(self.quote.status, "vendor_replied")
        self.assertEqual(self.quote.vendor_response, "Fresh response")
        self.assertTrue(
            self.quote.messages.filter(sender_role="vendor", message="Fresh response").exists()
        )

    def test_new_quote_email_delivery_includes_customer_confirmation(self):
        result = send_vendor_quote_notifications(self.quote)
        self.assertTrue(result["admin_email_sent"])
        self.assertTrue(result["vendor_email_sent"])
        self.assertTrue(result["customer_email_sent"])
        self.assertEqual(len(mail.outbox), 3)
