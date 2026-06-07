from django.db import migrations


PLAN_DATA = {
    "free": {
        "display_name": "Free Vendor",
        "description": "Free vendor account with one public product, basic visibility, and admin support.",
        "price_monthly": 0,
        "price_yearly": 0,
        "max_products": 1,
        "featured_products": 0,
        "commission_rate": 12,
        "priority_support": False,
        "analytics_access": True,
        "promotion_opportunities": False,
        "dedicated_account_manager": False,
        "icon": "fas fa-user",
        "color": "gray",
        "is_popular": False,
        "order": 1,
    },
    "basic": {
        "display_name": "Basic Vendor",
        "description": "Customer chat, five product uploads, five images per product, and basic seller visibility.",
        "price_monthly": 29,
        "price_yearly": 290,
        "max_products": 5,
        "featured_products": 0,
        "commission_rate": 10,
        "priority_support": False,
        "analytics_access": True,
        "promotion_opportunities": False,
        "dedicated_account_manager": False,
        "icon": "fas fa-chart-line",
        "color": "blue",
        "is_popular": False,
        "order": 2,
    },
    "plus": {
        "display_name": "Plus Vendor",
        "description": "Twenty products, ten images, PDF brochure upload, limited RFQ access, and better ranking.",
        "price_monthly": 79,
        "price_yearly": 790,
        "max_products": 20,
        "featured_products": 3,
        "commission_rate": 8,
        "priority_support": False,
        "analytics_access": True,
        "promotion_opportunities": True,
        "dedicated_account_manager": False,
        "icon": "fas fa-layer-group",
        "color": "cyan",
        "is_popular": True,
        "order": 3,
    },
    "pro": {
        "display_name": "Pro Vendor",
        "description": "One hundred products, video, PDF, certificates, RFQ, priority ranking, ads, and advanced analytics.",
        "price_monthly": 199,
        "price_yearly": 1990,
        "max_products": 100,
        "featured_products": 8,
        "commission_rate": 6,
        "priority_support": True,
        "analytics_access": True,
        "promotion_opportunities": True,
        "dedicated_account_manager": False,
        "icon": "fas fa-gem",
        "color": "purple",
        "is_popular": False,
        "order": 4,
    },
    "special": {
        "display_name": "Special Vendor",
        "description": "Three hundred products, homepage placement, priority RFQ, factory direct deals, ads, and premium visibility.",
        "price_monthly": 499,
        "price_yearly": 4990,
        "max_products": 300,
        "featured_products": 20,
        "commission_rate": 4,
        "priority_support": True,
        "analytics_access": True,
        "promotion_opportunities": True,
        "dedicated_account_manager": True,
        "icon": "fas fa-crown",
        "color": "yellow",
        "is_popular": False,
        "order": 5,
    },
    "enterprise": {
        "display_name": "Enterprise Vendor",
        "description": "Unlimited or admin-defined products, premium placement, full ads access, enterprise analytics, and dedicated support.",
        "price_monthly": 999,
        "price_yearly": 9990,
        "max_products": -1,
        "featured_products": -1,
        "commission_rate": 2,
        "priority_support": True,
        "analytics_access": True,
        "promotion_opportunities": True,
        "dedicated_account_manager": True,
        "icon": "fas fa-building",
        "color": "indigo",
        "is_popular": False,
        "order": 6,
    },
}


def update_plans(apps, schema_editor):
    SubscriptionPlan = apps.get_model("subscriptions", "SubscriptionPlan")
    for name, defaults in PLAN_DATA.items():
        SubscriptionPlan.objects.update_or_create(name=name, defaults={**defaults, "is_active": True})


def reverse_plans(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("subscriptions", "0002_seed_subscription_tiers"),
    ]

    operations = [
        migrations.RunPython(update_plans, reverse_plans),
    ]
