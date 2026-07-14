from decimal import Decimal

from django.db import migrations
from django.utils import timezone


OFFICIAL_PLANS = {
    "free": ("Free Vendor", Decimal("0.00"), 10),
    "basic": ("Basic Vendor", Decimal("3000.00"), 20),
    "plus": ("Plus Vendor", Decimal("8000.00"), 30),
    "pro": ("Pro Vendor", Decimal("18000.00"), 40),
    "special": ("Special Vendor", Decimal("35000.00"), 50),
    "enterprise": ("Enterprise Vendor", Decimal("150000.00"), 60),
}

PROVIDER_ENTITLEMENTS = {
    "free": {
        "max_projects": 1,
        "max_project_media": 5,
        "max_project_videos": 1,
        "max_local_video_uploads": 0,
        "max_video_size_mb": 0,
        "project_analytics_enabled": False,
        "project_leads_enabled": True,
        "featured_project_slots": 0,
        "project_product_links_limit": 2,
        "can_receive_serious_jobs": False,
    },
    "basic": {
        "max_projects": 5,
        "max_project_media": 8,
        "max_project_videos": 2,
        "max_local_video_uploads": 1,
        "max_video_size_mb": 50,
        "project_analytics_enabled": True,
        "project_leads_enabled": True,
        "featured_project_slots": 0,
        "project_product_links_limit": 5,
        "can_receive_serious_jobs": False,
    },
    "plus": {
        "max_projects": 20,
        "max_project_media": 15,
        "max_project_videos": 5,
        "max_local_video_uploads": 5,
        "max_video_size_mb": 150,
        "project_analytics_enabled": True,
        "project_leads_enabled": True,
        "featured_project_slots": 2,
        "project_product_links_limit": 15,
        "can_receive_serious_jobs": False,
    },
    "pro": {
        "max_projects": 100,
        "max_project_media": 30,
        "max_project_videos": 15,
        "max_local_video_uploads": 20,
        "max_video_size_mb": 300,
        "project_analytics_enabled": True,
        "project_leads_enabled": True,
        "featured_project_slots": 8,
        "project_product_links_limit": 30,
        "can_receive_serious_jobs": True,
    },
    "special": {
        "max_projects": 300,
        "max_project_media": 45,
        "max_project_videos": 30,
        "max_local_video_uploads": 40,
        "max_video_size_mb": 400,
        "project_analytics_enabled": True,
        "project_leads_enabled": True,
        "featured_project_slots": 20,
        "project_product_links_limit": 50,
        "can_receive_serious_jobs": True,
    },
    "enterprise": {
        "max_projects": -1,
        "max_project_media": 60,
        "max_project_videos": -1,
        "max_local_video_uploads": -1,
        "max_video_size_mb": 500,
        "project_analytics_enabled": True,
        "project_leads_enabled": True,
        "featured_project_slots": -1,
        "project_product_links_limit": -1,
        "can_receive_serious_jobs": True,
    },
}

LEGACY_PROVIDER_PLAN_MAP = {
    "free / starter": "free",
    "free": "free",
    "starter": "free",
    "standard": "plus",
    "premium": "pro",
    "verified pro": "special",
    "enterprise": "enterprise",
}


def _legacy_provider_tier(value):
    normalized = str(value or "").strip().lower()
    if normalized in OFFICIAL_PLANS:
        return normalized
    return LEGACY_PROVIDER_PLAN_MAP.get(normalized, "free")


def consolidate_account_subscriptions(apps, schema_editor):
    SubscriptionPlan = apps.get_model("subscriptions", "SubscriptionPlan")
    VendorSubscription = apps.get_model("subscriptions", "VendorSubscription")
    ProviderSubscriptionPlan = apps.get_model("installers", "ProviderSubscriptionPlan")
    ServiceProviderProfile = apps.get_model("installers", "ServiceProviderProfile")
    now = timezone.now()

    plans = {}
    for tier, (display_name, monthly_price, order) in OFFICIAL_PLANS.items():
        plan = SubscriptionPlan.objects.filter(name__iexact=tier).order_by("id").first()
        if plan is None:
            plan = SubscriptionPlan(name=tier)
        entitlements = dict(plan.role_entitlements or {})
        entitlements["provider"] = PROVIDER_ENTITLEMENTS[tier]
        plan.name = tier
        plan.display_name = display_name
        plan.price_monthly = monthly_price
        if not plan.price_yearly or plan.price_yearly <= 0:
            plan.price_yearly = monthly_price * 12
        plan.role_entitlements = entitlements
        plan.order = order
        plan.is_active = True
        plan.save()
        plans[tier] = plan

    for legacy_plan in ProviderSubscriptionPlan.objects.all():
        legacy_plan.official_tier_key = _legacy_provider_tier(legacy_plan.name)
        legacy_plan.is_deprecated = True
        legacy_plan.save(update_fields=["official_tier_key", "is_deprecated", "updated_at"])

    for subscription in VendorSubscription.objects.select_related("plan").all():
        if subscription.end_date <= now:
            subscription.is_active = False
            subscription.status = "expired"
            subscription.auto_renew = False
        elif subscription.is_active:
            subscription.status = "active"
        elif subscription.status == "active":
            subscription.status = "inactive"
        subscription.billing_cycle = subscription.billing_cycle or "monthly"
        subscription.currency = subscription.currency or "NGN"
        subscription.payment_state = subscription.payment_state or (
            "free" if subscription.plan.price_monthly == 0 else "paid"
        )
        subscription.save(update_fields=[
            "is_active",
            "status",
            "auto_renew",
            "billing_cycle",
            "currency",
            "payment_state",
            "updated_at",
        ])

    user_ids = VendorSubscription.objects.values_list("vendor_id", flat=True).distinct()
    for user_id in user_ids.iterator():
        active = list(
            VendorSubscription.objects.filter(
                vendor_id=user_id,
                is_active=True,
                end_date__gt=now,
            ).select_related("plan")
        )
        if len(active) <= 1:
            continue
        active.sort(
            key=lambda item: (
                item.plan.price_monthly > 0,
                item.plan.price_monthly,
                item.end_date,
                item.created_at,
            ),
            reverse=True,
        )
        for duplicate in active[1:]:
            duplicate.is_active = False
            duplicate.status = "inactive"
            duplicate.auto_renew = False
            duplicate.save(update_fields=["is_active", "status", "auto_renew", "updated_at"])

    for provider in ServiceProviderProfile.objects.select_related("user").all():
        current = (
            VendorSubscription.objects.filter(
                vendor_id=provider.user_id,
                is_active=True,
                end_date__gt=now,
            )
            .select_related("plan")
            .order_by("-plan__price_monthly", "-end_date", "-created_at")
            .first()
        )
        legacy_active = provider.subscription_status in {"active", "trial"}
        legacy_current = bool(provider.subscription_expires_at and provider.subscription_expires_at > now)
        if current is None and legacy_active and legacy_current:
            tier = _legacy_provider_tier(provider.subscription_plan)
            current = VendorSubscription.objects.create(
                vendor_id=provider.user_id,
                plan=plans[tier],
                start_date=min(provider.created_at or now, now),
                end_date=provider.subscription_expires_at,
                is_active=True,
                auto_renew=False,
                status="trial" if provider.subscription_status == "trial" else "active",
                billing_cycle="monthly",
                currency="NGN",
                payment_state="legacy_migrated",
                source_platform="provider_legacy_migration",
            )

        if current is not None:
            provider.subscription_plan = current.plan.name
            provider.subscription_status = current.status
            provider.subscription_expires_at = current.end_date
        else:
            provider.subscription_plan = plans["free"].name
            provider.subscription_status = "inactive"
            provider.subscription_expires_at = None
        provider.save(update_fields=[
            "subscription_plan",
            "subscription_status",
            "subscription_expires_at",
            "updated_at",
        ])


class Migration(migrations.Migration):
    dependencies = [
        ("subscriptions", "0009_subscriptionhistory_subscriptionpayment_and_more"),
        ("installers", "0009_providersubscriptionplan_is_deprecated_and_more"),
    ]

    operations = [
        migrations.RunPython(consolidate_account_subscriptions, migrations.RunPython.noop),
    ]
