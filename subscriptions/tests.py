from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from subscriptions.admin import sync_vendor_subscription_profile
from subscriptions.entitlements import can_create_vendor_offer
from subscriptions.models import SubscriptionPlan, VendorSubscription
from vendors.models import VendorProfile


class VendorSubscriptionVisibilityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="visibility-vendor",
            email="visibility@example.org",
            password="StrongPass1!",
            user_type="vendor",
        )
        self.profile = VendorProfile.objects.create(
            user=self.user,
            store_name="Visibility Store",
            store_slug="visibility-store",
            description="Subscription visibility test",
            approval_status="approved",
        )
        self.plan, _ = SubscriptionPlan.objects.update_or_create(
            name="enterprise",
            defaults={
                "display_name": "Enterprise Vendor",
                "priority_score": 125,
                "can_show_on_homepage": True,
                "max_products": -1,
                "is_active": True,
            },
        )

    def test_admin_subscription_sync_applies_plan_visibility(self):
        subscription = VendorSubscription.objects.create(
            vendor=self.user,
            plan=self.plan,
            start_date=timezone.now(),
            end_date=timezone.now() + timedelta(days=30),
            is_active=True,
        )

        sync_vendor_subscription_profile(self.user)

        self.profile.refresh_from_db()
        self.assertTrue(self.profile.subscription_active)
        self.assertEqual(self.profile.subscription_tier, "enterprise")
        self.assertEqual(self.profile.priority_score, 125)
        self.assertTrue(self.profile.can_show_on_homepage)
        self.assertEqual(self.profile.subscription_expires_at, subscription.end_date)

    def test_expired_subscription_does_not_keep_paid_priority(self):
        VendorSubscription.objects.create(
            vendor=self.user,
            plan=self.plan,
            start_date=timezone.now() - timedelta(days=60),
            end_date=timezone.now() - timedelta(days=1),
            is_active=True,
        )

        sync_vendor_subscription_profile(self.user)

        self.profile.refresh_from_db()
        self.assertFalse(self.profile.subscription_active)
        self.assertEqual(self.profile.subscription_tier, "free")
        self.assertEqual(self.profile.priority_score, 0)
        self.assertFalse(self.profile.can_show_on_homepage)

    def test_vendor_offer_entitlement_uses_subscription_tier_label(self):
        VendorSubscription.objects.create(
            vendor=self.user,
            plan=self.plan,
            start_date=timezone.now(),
            end_date=timezone.now() + timedelta(days=30),
            is_active=True,
        )

        access = can_create_vendor_offer(self.user)

        self.assertEqual(access["plan_label"], "Enterprise Vendor")
        self.assertTrue(access["allowed"])
