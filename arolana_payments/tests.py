import json
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from notifications.models import Notification
from orders.models import Order

from .models import PayPalWebhookLog, PaymentMethod, PaymentRefund, PaymentStatus, PaymentTransaction
from .services import process_paypal_webhook


def capture_event(event_id="WH-CAPTURE-1"):
    return {
        "id": event_id,
        "event_type": "PAYMENT.CAPTURE.COMPLETED",
        "resource": {
            "id": "CAPTURE-123",
            "status": "COMPLETED",
            "amount": {"value": "10.00", "currency_code": "USD"},
            "supplementary_data": {
                "related_ids": {"order_id": "PAYPAL-ORDER-123"}
            },
        },
    }


class PayPalWebhookTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.customer = User.objects.create_user(
            email="customer@example.com",
            username="customer",
            password="test-pass-123",
        )
        self.admin = User.objects.create_user(
            email="admin@example.com",
            username="admin",
            password="test-pass-123",
            is_staff=True,
        )
        self.order = Order.objects.create(
            user=self.customer,
            subtotal=Decimal("15000.00"),
            shipping_cost=Decimal("0.00"),
            tax=Decimal("0.00"),
            total=Decimal("15000.00"),
            shipping_address="Lagos",
            billing_address="Lagos",
        )
        self.payment = PaymentTransaction.objects.create(
            user=self.customer,
            order_id=self.order.order_number,
            gateway=PaymentMethod.PAYPAL,
            status=PaymentStatus.PROCESSING,
            amount=Decimal("15000.00"),
            currency="NGN",
            customer_email=self.customer.email,
            gateway_reference="PAYPAL-ORDER-123",
            gateway_response={
                "arolana_settlement": {
                    "settlement_amount": "10.00",
                    "settlement_currency": "USD",
                }
            },
        )

    def test_completed_capture_is_idempotent_and_marks_order_paid(self):
        event = capture_event()
        log = PayPalWebhookLog.objects.create(
            event_id=event["id"],
            event_type=event["event_type"],
            resource_id=event["resource"]["id"],
            signature_verified=True,
            status=PayPalWebhookLog.STATUS_VERIFIED,
            payload=event,
        )

        process_paypal_webhook(log.pk)
        process_paypal_webhook(log.pk)

        self.payment.refresh_from_db()
        self.order.refresh_from_db()
        log.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatus.SUCCESS)
        self.assertEqual(self.payment.gateway_capture_id, "CAPTURE-123")
        self.assertEqual(self.order.payment_status, "paid")
        self.assertEqual(log.status, PayPalWebhookLog.STATUS_PROCESSED)
        self.assertEqual(
            Notification.objects.filter(
                user=self.customer,
                metadata__paypal_event_id=event["id"],
            ).count(),
            1,
        )

    def test_refund_creates_one_refund_record(self):
        self.payment.status = PaymentStatus.SUCCESS
        self.payment.gateway_capture_id = "CAPTURE-123"
        self.payment.save(update_fields=["status", "gateway_capture_id", "updated_at"])
        event = {
            "id": "WH-REFUND-1",
            "event_type": "PAYMENT.CAPTURE.REFUNDED",
            "resource": {
                "id": "REFUND-123",
                "status": "COMPLETED",
                "amount": {"value": "10.00", "currency_code": "USD"},
                "supplementary_data": {
                    "related_ids": {"capture_id": "CAPTURE-123"}
                },
            },
        }
        log = PayPalWebhookLog.objects.create(
            event_id=event["id"],
            event_type=event["event_type"],
            resource_id=event["resource"]["id"],
            signature_verified=True,
            status=PayPalWebhookLog.STATUS_VERIFIED,
            payload=event,
        )

        process_paypal_webhook(log.pk)
        process_paypal_webhook(log.pk)

        self.payment.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatus.REFUNDED)
        self.assertEqual(self.order.payment_status, "refunded")
        self.assertEqual(PaymentRefund.objects.filter(gateway_refund_id="REFUND-123").count(), 1)

    @override_settings(PAYPAL_WEBHOOK_ID="WH-ID")
    @patch("arolana_payments.views.process_paypal_webhook")
    @patch("arolana_payments.views.verify_paypal_webhook_signature")
    def test_webhook_endpoint_verifies_signature_before_processing(
        self,
        verify_signature,
        process_webhook,
    ):
        verify_signature.return_value = (True, {"verification_status": "SUCCESS"})
        process_webhook.side_effect = lambda log_id: PayPalWebhookLog.objects.get(pk=log_id)
        event = capture_event("WH-ENDPOINT-1")

        response = self.client.post(
            reverse("arolana_payments:paypal_webhook"),
            data=json.dumps(event),
            content_type="application/json",
            HTTP_PAYPAL_AUTH_ALGO="SHA256withRSA",
            HTTP_PAYPAL_CERT_URL="https://api.paypal.com/cert",
            HTTP_PAYPAL_TRANSMISSION_ID="transmission-1",
            HTTP_PAYPAL_TRANSMISSION_SIG="signature",
            HTTP_PAYPAL_TRANSMISSION_TIME="2026-06-07T12:00:00Z",
        )

        self.assertEqual(response.status_code, 200)
        verify_signature.assert_called_once()
        process_webhook.assert_called_once()
        self.assertTrue(
            PayPalWebhookLog.objects.get(event_id=event["id"]).signature_verified
        )
