import json
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from arolana_payments.models import PaymentMethod, PaymentStatus, PaymentTransaction
from notifications.models import Notification
from mobile_customers.models import MobileCustomer
from staff_mobile.models import StaffMobileToken
from subscriptions.lifecycle import (
    activate_free_subscription,
    activate_subscription_from_payment,
    calculate_period_end,
    create_subscription_payment,
    get_effective_subscription,
    process_subscription_lifecycle,
    request_cancellation,
    schedule_downgrade,
    undo_cancellation,
)
from subscriptions.models import (
    SubscriptionHistory,
    SubscriptionPayment,
    SubscriptionPlan,
    SubscriptionReminderLog,
    VendorSubscription,
)
from subscriptions.views import _subscription_payload


class AccountSubscriptionLifecycleTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="shared-subscription-user",
            email="shared-subscription@example.org",
            password="StrongPass1!",
        )
        self.free = self._plan("free", "Free", "0.00", "0.00")
        self.basic = self._plan("basic", "Basic Vendor", "3000.00", "36000.00")
        self.pro = self._plan("pro", "Pro Vendor", "18000.00", "216000.00")

    def _plan(self, tier, label, monthly, yearly):
        plan, _ = SubscriptionPlan.objects.update_or_create(
            name=tier,
            defaults={
                "display_name": label,
                "price_monthly": Decimal(monthly),
                "price_yearly": Decimal(yearly),
                "is_active": True,
            },
        )
        return plan

    def _payment(self, plan=None, amount=None, reference="SUB-TEST-001"):
        plan = plan or self.basic
        return PaymentTransaction.objects.create(
            reference=reference,
            user=self.user,
            gateway=PaymentMethod.PAYSTACK,
            status=PaymentStatus.SUCCESS,
            amount=amount if amount is not None else plan.price_monthly,
            currency="NGN",
            customer_email=self.user.email,
            checkout_data={
                "purpose": "account_subscription",
                "user_id": self.user.id,
                "plan_id": plan.id,
                "tier": plan.tier_key,
                "billing_cycle": VendorSubscription.BILLING_MONTHLY,
                "source_platform": "test",
            },
            paid_at=timezone.now(),
        )

    def test_period_end_uses_calendar_months_and_years(self):
        start = timezone.now().replace(month=1, day=31, hour=12, minute=0, second=0, microsecond=0)
        self.assertEqual(calculate_period_end(start, "monthly"), start + relativedelta(months=1))
        self.assertEqual(calculate_period_end(start, "yearly"), start + relativedelta(years=1))

    def test_verified_payment_activation_is_server_priced_and_idempotent(self):
        payment = self._payment()

        with self.captureOnCommitCallbacks(execute=True):
            first = activate_subscription_from_payment(payment, source_platform="test")
        with self.captureOnCommitCallbacks(execute=True):
            second = activate_subscription_from_payment(payment, source_platform="test_retry")

        self.assertEqual(first.id, second.id)
        self.assertEqual(first.plan, self.basic)
        self.assertEqual(VendorSubscription.objects.filter(vendor=self.user, is_active=True).count(), 1)
        self.assertEqual(SubscriptionPayment.objects.filter(payment_transaction=payment).count(), 1)
        self.assertEqual(SubscriptionHistory.objects.filter(user=self.user, event_type="activated").count(), 1)
        self.assertTrue(Notification.objects.filter(user=self.user, title="Arolana subscription activated").exists())

    def test_payment_amount_tampering_is_rejected(self):
        payment = self._payment(amount=Decimal("1.00"), reference="SUB-TAMPERED")

        with self.assertRaisesMessage(ValidationError, "amount does not match"):
            activate_subscription_from_payment(payment, source_platform="test")

        self.assertFalse(VendorSubscription.objects.filter(vendor=self.user).exists())
        self.assertFalse(SubscriptionPayment.objects.filter(payment_transaction=payment).exists())

    def test_scheduled_cancellation_keeps_access_until_period_end(self):
        subscription = VendorSubscription.objects.create(
            vendor=self.user,
            plan=self.pro,
            start_date=timezone.now(),
            end_date=timezone.now() + relativedelta(months=1),
            status=VendorSubscription.STATUS_ACTIVE,
            payment_state="paid",
            is_active=True,
        )

        with self.captureOnCommitCallbacks(execute=True):
            request_cancellation(self.user, subscription.id, reason="No longer needed", source_platform="test")

        subscription.refresh_from_db()
        effective = get_effective_subscription(self.user)
        self.assertTrue(subscription.cancel_at_period_end)
        self.assertFalse(subscription.auto_renew)
        self.assertTrue(subscription.is_current)
        self.assertEqual(effective.tier, "pro")
        self.assertTrue(SubscriptionHistory.objects.filter(user=self.user, event_type="cancellation_scheduled").exists())
        self.assertTrue(Notification.objects.filter(user=self.user, title="Subscription cancellation scheduled").exists())

    def test_expiry_falls_back_to_free_without_deleting_history(self):
        subscription = VendorSubscription.objects.create(
            vendor=self.user,
            plan=self.basic,
            start_date=timezone.now() - relativedelta(months=1),
            end_date=timezone.now() - relativedelta(minutes=1),
            status=VendorSubscription.STATUS_ACTIVE,
            payment_state="paid",
            is_active=True,
            auto_renew=False,
        )

        with self.captureOnCommitCallbacks(execute=True):
            result = process_subscription_lifecycle()

        subscription.refresh_from_db()
        self.assertEqual(result["expired"], 1)
        self.assertEqual(subscription.status, VendorSubscription.STATUS_EXPIRED)
        self.assertFalse(subscription.is_active)
        self.assertEqual(get_effective_subscription(self.user).tier, "free")
        self.assertTrue(SubscriptionHistory.objects.filter(subscription=subscription, event_type="expired").exists())
        self.assertTrue(Notification.objects.filter(user=self.user, title="Subscription expired").exists())

    def test_api_payload_is_normalized_and_backward_compatible(self):
        VendorSubscription.objects.create(
            vendor=self.user,
            plan=self.basic,
            start_date=timezone.now(),
            end_date=timezone.now() + relativedelta(months=1),
            status=VendorSubscription.STATUS_ACTIVE,
            payment_state="paid",
            is_active=True,
        )

        payload = _subscription_payload(self.user, "vendor")
        subscription = payload["subscription"]
        self.assertEqual(subscription["tier"], "basic")
        self.assertEqual(subscription["tier_key"], "basic")
        self.assertEqual(subscription["end_date"], subscription["expires_at"])
        self.assertIn("entitlements", subscription)
        self.assertIn("role_entitlements", subscription)
        self.assertIn("actions", subscription)
        self.assertEqual(payload["effective_subscription"]["tier"], "basic")

    def test_shared_api_accepts_existing_customer_mobile_token(self):
        customer = MobileCustomer.objects.create(
            user=self.user,
            full_name="Shared Account",
            phone_number="+2348000000101",
            email=self.user.email,
            api_token="customer-shared-subscription-token",
        )

        response = self.client.get(
            reverse("subscriptions:api_current"),
            HTTP_AUTHORIZATION=f"Bearer {customer.api_token}",
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["subscription"]["account_id"], self.user.id)

    def test_shared_api_accepts_existing_staff_token_for_same_account(self):
        token = StaffMobileToken.issue(
            role=StaffMobileToken.ROLE_VENDOR,
            user=self.user,
            device_name="subscription-test",
        )

        response = self.client.get(
            reverse("subscriptions:api_current"),
            HTTP_AUTHORIZATION=f"Bearer {token.token}",
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["subscription"]["account_id"], self.user.id)

    def test_shared_api_rejects_invalid_bearer_without_html_redirect(self):
        response = self.client.get(
            reverse("subscriptions:api_current"),
            HTTP_AUTHORIZATION="Bearer invalid-subscription-token",
            secure=True,
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers["Content-Type"], "application/json")
        self.assertFalse(response.json()["success"])

    def test_shared_api_keeps_csrf_for_browser_session_posts(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)

        response = csrf_client.post(
            reverse("subscriptions:api_auto_renew"),
            data=json.dumps({"enabled": True}),
            content_type="application/json",
            secure=True,
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.headers["Content-Type"], "application/json")

    def test_checkout_uses_server_price_and_records_role_context(self):
        payment = create_subscription_payment(
            self.user,
            self.basic,
            VendorSubscription.BILLING_MONTHLY,
            PaymentMethod.PAYSTACK,
            source_platform="test",
            role_context="installer",
        )

        self.assertEqual(payment.amount, self.basic.price_monthly)
        self.assertEqual(payment.currency, "NGN")
        self.assertEqual(payment.checkout_data["role_context"], "provider")
        self.assertEqual(payment.checkout_data["purpose"], "account_subscription")
        self.assertTrue(payment.checkout_data["server_priced"])

    def test_web_subscribe_endpoint_rejects_get(self):
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("subscriptions:subscribe", args=[self.basic.id]),
            secure=True,
        )

        self.assertEqual(response.status_code, 405)
        self.assertFalse(PaymentTransaction.objects.filter(user=self.user).exists())

    def test_cancellation_can_be_undone_without_losing_access(self):
        subscription = VendorSubscription.objects.create(
            vendor=self.user,
            plan=self.pro,
            start_date=timezone.now(),
            end_date=timezone.now() + relativedelta(months=1),
            status=VendorSubscription.STATUS_ACTIVE,
            payment_state="paid",
            is_active=True,
        )
        with self.captureOnCommitCallbacks(execute=True):
            request_cancellation(self.user, subscription.id, source_platform="test")
        with self.captureOnCommitCallbacks(execute=True):
            undo_cancellation(self.user, subscription.id, source_platform="test")

        subscription.refresh_from_db()
        self.assertFalse(subscription.cancel_at_period_end)
        self.assertTrue(subscription.auto_renew)
        self.assertEqual(get_effective_subscription(self.user).tier, "pro")
        self.assertTrue(SubscriptionHistory.objects.filter(
            subscription=subscription,
            event_type="cancellation_undone",
        ).exists())

    def test_expiry_reminder_is_idempotent(self):
        now = timezone.now()
        subscription = VendorSubscription.objects.create(
            vendor=self.user,
            plan=self.basic,
            start_date=now,
            end_date=now + relativedelta(days=7),
            status=VendorSubscription.STATUS_ACTIVE,
            payment_state="paid",
            is_active=True,
        )

        first = process_subscription_lifecycle(now=now)
        second = process_subscription_lifecycle(now=now)

        self.assertEqual(first["reminders"], 1)
        self.assertEqual(second["reminders"], 0)
        self.assertEqual(SubscriptionReminderLog.objects.filter(
            subscription=subscription,
            event_key="expiry_7_days",
        ).count(), 1)

    def test_paid_downgrade_requires_payment_and_uses_free_fallback(self):
        now = timezone.now()
        subscription = VendorSubscription.objects.create(
            vendor=self.user,
            plan=self.pro,
            start_date=now - relativedelta(months=1),
            end_date=now + relativedelta(minutes=1),
            status=VendorSubscription.STATUS_ACTIVE,
            payment_state="paid",
            is_active=True,
        )
        with self.captureOnCommitCallbacks(execute=True):
            schedule_downgrade(self.user, self.basic, source_platform="test")

        with self.captureOnCommitCallbacks(execute=True):
            result = process_subscription_lifecycle(now=now + relativedelta(minutes=2))

        subscription.refresh_from_db()
        pending = VendorSubscription.objects.get(
            vendor=self.user,
            plan=self.basic,
            status=VendorSubscription.STATUS_PENDING_PAYMENT,
        )
        self.assertEqual(result["downgrades"], 1)
        self.assertFalse(subscription.is_active)
        self.assertFalse(pending.is_active)
        self.assertEqual(get_effective_subscription(self.user).tier, "free")
        self.assertTrue(SubscriptionHistory.objects.filter(
            subscription=pending,
            event_type="downgrade_payment_required",
        ).exists())
        self.assertTrue(Notification.objects.filter(
            user=self.user,
            title="Subscription payment required",
            message__icontains="using Free access",
        ).exists())

    def test_free_activation_is_shared_and_audit_idempotent(self):
        with self.captureOnCommitCallbacks(execute=True):
            first = activate_free_subscription(self.user, source_platform="provider_app")
        with self.captureOnCommitCallbacks(execute=True):
            second = activate_free_subscription(self.user, source_platform="vendor_web")

        self.assertEqual(first.id, second.id)
        self.assertEqual(VendorSubscription.objects.filter(vendor=self.user, is_active=True).count(), 1)
        self.assertEqual(SubscriptionHistory.objects.filter(
            user=self.user,
            event_type="free_plan_activated",
        ).count(), 1)
        self.assertEqual(get_effective_subscription(self.user, "vendor").subscription_id, first.id)
        self.assertEqual(get_effective_subscription(self.user, "provider").subscription_id, first.id)

    def test_payment_result_is_scoped_to_the_signed_in_account(self):
        payment = self._payment(reference="SUB-PRIVATE-RESULT")
        other_user = User.objects.create_user(
            username="other-subscription-user",
            email="other-subscription@example.org",
            password="StrongPass1!",
        )
        self.client.force_login(other_user)

        response = self.client.get(
            reverse("subscriptions:api_payment_result", args=[payment.reference]),
            secure=True,
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(VendorSubscription.objects.filter(vendor=other_user).exists())
