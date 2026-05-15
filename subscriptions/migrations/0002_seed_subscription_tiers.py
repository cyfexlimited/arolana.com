from django.db import migrations
from django.utils import timezone


PLAN_DATA = [
    {
        'name': 'free',
        'display_name': 'Free',
        'description': 'Starter plan for testing the marketplace.',
        'price_monthly': 0,
        'price_yearly': 0,
        'max_products': 10,
        'featured_products': 0,
        'commission_rate': 12,
        'priority_support': False,
        'analytics_access': False,
        'promotion_opportunities': False,
        'dedicated_account_manager': False,
        'icon': 'fas fa-user',
        'color': 'gray',
        'is_popular': False,
        'order': 1,
    },
    {
        'name': 'basic',
        'display_name': 'Basic',
        'description': 'Paid seller tools with customer product chat enabled.',
        'price_monthly': 29,
        'price_yearly': 290,
        'max_products': 50,
        'featured_products': 1,
        'commission_rate': 10,
        'priority_support': False,
        'analytics_access': False,
        'promotion_opportunities': True,
        'dedicated_account_manager': False,
        'icon': 'fas fa-chart-line',
        'color': 'blue',
        'is_popular': False,
        'order': 2,
    },
    {
        'name': 'plus',
        'display_name': 'Plus',
        'description': 'More products, variants, images, and manufacturer tools.',
        'price_monthly': 79,
        'price_yearly': 790,
        'max_products': 150,
        'featured_products': 3,
        'commission_rate': 8,
        'priority_support': True,
        'analytics_access': True,
        'promotion_opportunities': True,
        'dedicated_account_manager': False,
        'icon': 'fas fa-layer-group',
        'color': 'cyan',
        'is_popular': True,
        'order': 3,
    },
    {
        'name': 'pro',
        'display_name': 'Pro',
        'description': 'Professional seller plan for large catalogs.',
        'price_monthly': 199,
        'price_yearly': 1990,
        'max_products': 500,
        'featured_products': 8,
        'commission_rate': 6,
        'priority_support': True,
        'analytics_access': True,
        'promotion_opportunities': True,
        'dedicated_account_manager': False,
        'icon': 'fas fa-gem',
        'color': 'purple',
        'is_popular': False,
        'order': 4,
    },
    {
        'name': 'special',
        'display_name': 'Special',
        'description': 'High-visibility plan for strategic sellers and manufacturers.',
        'price_monthly': 499,
        'price_yearly': 4990,
        'max_products': 1000,
        'featured_products': 20,
        'commission_rate': 4,
        'priority_support': True,
        'analytics_access': True,
        'promotion_opportunities': True,
        'dedicated_account_manager': True,
        'icon': 'fas fa-crown',
        'color': 'yellow',
        'is_popular': False,
        'order': 5,
    },
    {
        'name': 'enterprise',
        'display_name': 'Enterprise',
        'description': 'Unlimited marketplace access with account management.',
        'price_monthly': 999,
        'price_yearly': 9990,
        'max_products': -1,
        'featured_products': -1,
        'commission_rate': 2,
        'priority_support': True,
        'analytics_access': True,
        'promotion_opportunities': True,
        'dedicated_account_manager': True,
        'icon': 'fas fa-building',
        'color': 'indigo',
        'is_popular': False,
        'order': 6,
    },
]


def seed_subscription_tiers(apps, schema_editor):
    SubscriptionPlan = apps.get_model('subscriptions', 'SubscriptionPlan')
    VendorProfile = apps.get_model('vendors', 'VendorProfile')
    VendorSubscriptionPlan = apps.get_model('vendors', 'VendorSubscriptionPlan')

    for plan_data in PLAN_DATA:
        SubscriptionPlan.objects.update_or_create(
            name=plan_data['name'],
            defaults={**plan_data, 'is_active': True},
        )

    legacy_map = {'premium': 'pro', 'featured': 'special'}
    for old, new in legacy_map.items():
        VendorProfile.objects.filter(subscription_tier=old).update(subscription_tier=new)
        VendorSubscriptionPlan.objects.filter(tier=old).update(tier=new)

    score_map = {
        'free': 0,
        'basic': 20,
        'plus': 40,
        'pro': 65,
        'special': 85,
        'enterprise': 100,
    }
    now = timezone.now()
    for profile in VendorProfile.objects.all():
        tier = legacy_map.get(profile.subscription_tier, profile.subscription_tier)
        if profile.subscription_expiry and profile.subscription_expiry <= now:
            tier = 'free'
        profile.subscription_tier = tier if tier in score_map else 'free'
        profile.priority_score = score_map[profile.subscription_tier]
        profile.save(update_fields=['subscription_tier', 'priority_score', 'updated_at'])


def unseed_subscription_tiers(apps, schema_editor):
    SubscriptionPlan = apps.get_model('subscriptions', 'SubscriptionPlan')
    SubscriptionPlan.objects.filter(name__in=[plan['name'] for plan in PLAN_DATA]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('vendors', '0002_alter_vendorprofile_subscription_tier_and_more'),
        ('manufacturers', '0003_manufacturer_priority_score_and_more'),
        ('subscriptions', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_subscription_tiers, unseed_subscription_tiers),
    ]
