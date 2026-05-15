from django.db import models
from core.models import BaseModel
from accounts.models import User
from django.utils import timezone

SUBSCRIPTION_TIERS = [
    ('free', 'Free'),
    ('basic', 'Basic'),
    ('plus', 'Plus'),
    ('pro', 'Pro'),
    ('special', 'Special'),
    ('enterprise', 'Enterprise'),
]

LEGACY_TIER_MAP = {
    'premium': 'pro',
    'featured': 'special',
}

TIER_LIMITS = {
    'free': {
        'max_products': 10,
        'featured_products': 0,
        'max_images_per_product': 3,
        'max_variants_per_product': 0,
        'chat_enabled': False,
        'manufacturer_access': False,
        'priority_score': 0,
        'commission_rate': 12,
    },
    'basic': {
        'max_products': 50,
        'featured_products': 1,
        'max_images_per_product': 6,
        'max_variants_per_product': 10,
        'chat_enabled': True,
        'manufacturer_access': False,
        'priority_score': 20,
        'commission_rate': 10,
    },
    'plus': {
        'max_products': 150,
        'featured_products': 3,
        'max_images_per_product': 10,
        'max_variants_per_product': 30,
        'chat_enabled': True,
        'manufacturer_access': True,
        'priority_score': 40,
        'commission_rate': 8,
    },
    'pro': {
        'max_products': 500,
        'featured_products': 8,
        'max_images_per_product': 15,
        'max_variants_per_product': 75,
        'chat_enabled': True,
        'manufacturer_access': True,
        'priority_score': 65,
        'commission_rate': 6,
    },
    'special': {
        'max_products': 1000,
        'featured_products': 20,
        'max_images_per_product': 20,
        'max_variants_per_product': 150,
        'chat_enabled': True,
        'manufacturer_access': True,
        'priority_score': 85,
        'commission_rate': 4,
    },
    'enterprise': {
        'max_products': -1,
        'featured_products': -1,
        'max_images_per_product': 30,
        'max_variants_per_product': -1,
        'chat_enabled': True,
        'manufacturer_access': True,
        'priority_score': 100,
        'commission_rate': 2,
    },
}


def normalize_subscription_tier(tier):
    tier = (tier or 'free').lower()
    tier = LEGACY_TIER_MAP.get(tier, tier)
    return tier if tier in TIER_LIMITS else 'free'


def get_tier_limits(tier):
    return TIER_LIMITS[normalize_subscription_tier(tier)]


def tier_is_paid(tier):
    return normalize_subscription_tier(tier) != 'free'


def user_subscription_tier(user):
    if not user or not getattr(user, 'is_authenticated', True):
        return 'free'

    subscription = VendorSubscription.objects.filter(
        vendor=user,
        is_active=True,
        end_date__gt=timezone.now()
    ).select_related('plan').first()
    if subscription:
        return normalize_subscription_tier(subscription.plan.name)

    vendor_profile = getattr(user, 'vendor_profile', None)
    if vendor_profile:
        if vendor_profile.subscription_expiry and vendor_profile.subscription_expiry <= timezone.now():
            return 'free'
        return normalize_subscription_tier(vendor_profile.subscription_tier)

    return 'free'


def user_subscription_limits(user):
    return get_tier_limits(user_subscription_tier(user))


def user_has_paid_subscription(user):
    limits = user_subscription_limits(user)
    return limits['chat_enabled'] and tier_is_paid(user_subscription_tier(user))

class SubscriptionPlan(BaseModel):
    """Subscription plans for vendors"""
    name = models.CharField(max_length=50, unique=True)
    display_name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    
    # Pricing
    price_monthly = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    price_yearly = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    # Features
    max_products = models.IntegerField(default=10)
    featured_products = models.IntegerField(default=0)
    commission_rate = models.DecimalField(max_digits=5, decimal_places=2, default=10.00)
    
    # Benefits
    priority_support = models.BooleanField(default=False)
    analytics_access = models.BooleanField(default=False)
    promotion_opportunities = models.BooleanField(default=False)
    dedicated_account_manager = models.BooleanField(default=False)
    
    # Display
    icon = models.CharField(max_length=50, blank=True)
    color = models.CharField(max_length=20, default='gray')
    is_popular = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    order = models.IntegerField(default=0)
    
    class Meta:
        ordering = ['order', 'price_monthly']
    
    def __str__(self):
        return self.display_name

    @property
    def tier_key(self):
        return normalize_subscription_tier(self.name)

    @property
    def limits(self):
        return get_tier_limits(self.tier_key)

    @property
    def is_paid(self):
        return tier_is_paid(self.tier_key)

    def get_features_list(self):
        limits = self.limits
        products = 'Unlimited products' if limits['max_products'] == -1 else f"{limits['max_products']} products"
        featured = 'Unlimited featured products' if limits['featured_products'] == -1 else f"{limits['featured_products']} featured products"
        variants = 'Unlimited variants' if limits['max_variants_per_product'] == -1 else f"{limits['max_variants_per_product']} variants per product"
        features = [
            products,
            featured,
            f"{limits['max_images_per_product']} images per product",
            variants,
            f"{limits['commission_rate']}% commission",
        ]
        if limits['chat_enabled']:
            features.append("Product chat with customers")
        if limits['manufacturer_access']:
            features.append("Manufacturer tools")
        if self.priority_support:
            features.append("Priority support")
        if self.analytics_access:
            features.append("Analytics")
        if self.dedicated_account_manager:
            features.append("Dedicated account manager")
        return features

class VendorSubscription(BaseModel):
    """Vendor's active subscription"""
    vendor = models.ForeignKey(User, on_delete=models.CASCADE, related_name='subscriptions')
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.CASCADE)
    start_date = models.DateTimeField(default=timezone.now)
    end_date = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    auto_renew = models.BooleanField(default=True)
    payment_method = models.CharField(max_length=50, blank=True)
    transaction_id = models.CharField(max_length=200, blank=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.vendor.username} - {self.plan.display_name}"

    @property
    def is_current(self):
        return self.is_active and self.end_date > timezone.now()
