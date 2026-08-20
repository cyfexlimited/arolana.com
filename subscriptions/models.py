from django.conf import settings
from django.db import models
from core.models import BaseModel
from accounts.models import User
from django.utils import timezone

SUBSCRIPTION_TIERS = [
    ('free', 'Free Vendor'),
    ('basic', 'Basic Vendor'),
    ('plus', 'Plus Vendor'),
    ('pro', 'Pro Vendor'),
    ('special', 'Special Vendor'),
    ('enterprise', 'Enterprise Vendor'),
]

LEGACY_TIER_MAP = {
    'premium': 'pro',
    'featured': 'special',
}

TIER_LIMITS = {
    'free': {
        'max_products': 1,
        'featured_products': 0,
        'max_images_per_product': 3,
        'max_variants_per_product': 0,
        'chat_enabled': False,
        'store_reviews_enabled': False,
        'manufacturer_access': False,
        'can_upload_video': False,
        'social_publishing': False,
        'can_upload_pdf': False,
        'can_upload_certificates': False,
        'can_access_rfq': False,
        'max_quote_responses_per_month': 3,
        'quote_responses_per_month': 3,
        'quote_priority': 0,
        'admin_assisted_quotes': True,
        'quote_chat_enabled': False,
        'can_receive_direct_enquiries': False,
        'can_show_phone': False,
        'can_show_whatsapp': False,
        'can_receive_callback_requests': False,
        'can_show_direct_contact_badge': False,
        'lead_tracking_enabled': False,
        'hide_phone_until_click': True,
        'can_use_boosting': False,
        'can_show_on_homepage': False,
        'can_access_analytics': True,
        'can_access_advanced_analytics': False,
        'can_access_ads': False,
        'priority_score': 0,
        'commission_rate': 12,
        'support_level': 'basic',
        'badge_level': 'Free Vendor',
    },
    'basic': {
        'max_products': 5,
        'featured_products': 1,
        'max_images_per_product': 5,
        'max_variants_per_product': 2,
        'chat_enabled': True,
        'store_reviews_enabled': True,
        'manufacturer_access': False,
        'can_upload_video': False,
        'social_publishing': False,
        'can_upload_pdf': False,
        'can_upload_certificates': False,
        'can_access_rfq': False,
        'max_quote_responses_per_month': 20,
        'quote_responses_per_month': 20,
        'quote_priority': 20,
        'admin_assisted_quotes': True,
        'quote_chat_enabled': True,
        'can_receive_direct_enquiries': True,
        'can_show_phone': False,
        'can_show_whatsapp': False,
        'can_receive_callback_requests': False,
        'can_show_direct_contact_badge': False,
        'lead_tracking_enabled': False,
        'hide_phone_until_click': True,
        'can_use_boosting': False,
        'can_show_on_homepage': False,
        'can_access_analytics': True,
        'can_access_advanced_analytics': False,
        'can_access_ads': False,
        'priority_score': 20,
        'commission_rate': 10,
        'support_level': 'basic',
        'badge_level': 'Basic Vendor',
    },
    'plus': {
        'max_products': 20,
        'featured_products': 3,
        'max_images_per_product': 10,
        'max_variants_per_product': 5,
        'chat_enabled': True,
        'store_reviews_enabled': True,
        'manufacturer_access': True,
        'can_upload_video': False,
        'social_publishing': False,
        'can_upload_pdf': True,
        'can_upload_certificates': False,
        'can_access_rfq': True,
        'max_quote_responses_per_month': 100,
        'quote_responses_per_month': 100,
        'quote_priority': 40,
        'admin_assisted_quotes': True,
        'quote_chat_enabled': True,
        'can_receive_direct_enquiries': True,
        'can_show_phone': False,
        'can_show_whatsapp': False,
        'can_receive_callback_requests': True,
        'can_show_direct_contact_badge': False,
        'lead_tracking_enabled': True,
        'hide_phone_until_click': True,
        'can_use_boosting': False,
        'can_show_on_homepage': True,
        'can_access_analytics': True,
        'can_access_advanced_analytics': False,
        'can_access_ads': False,
        'priority_score': 40,
        'commission_rate': 8,
        'support_level': 'standard',
        'badge_level': 'Plus Vendor',
    },
    'pro': {
        'max_products': 100,
        'featured_products': 8,
        'max_images_per_product': 10,
        'max_variants_per_product': 20,
        'chat_enabled': True,
        'store_reviews_enabled': True,
        'manufacturer_access': True,
        'can_upload_video': True,
        'social_publishing': True,
        'can_upload_pdf': True,
        'can_upload_certificates': True,
        'can_access_rfq': True,
        'max_quote_responses_per_month': -1,
        'quote_responses_per_month': -1,
        'quote_priority': 65,
        'admin_assisted_quotes': True,
        'quote_chat_enabled': True,
        'can_receive_direct_enquiries': True,
        'can_show_phone': False,
        'can_show_whatsapp': False,
        'can_receive_callback_requests': True,
        'can_show_direct_contact_badge': False,
        'lead_tracking_enabled': True,
        'hide_phone_until_click': True,
        'can_use_boosting': True,
        'can_show_on_homepage': True,
        'can_access_analytics': True,
        'can_access_advanced_analytics': True,
        'can_access_ads': True,
        'priority_score': 65,
        'commission_rate': 6,
        'support_level': 'priority',
        'badge_level': 'Pro Vendor',
    },
    'special': {
        'max_products': 300,
        'featured_products': 20,
        'max_images_per_product': 10,
        'max_variants_per_product': 50,
        'chat_enabled': True,
        'store_reviews_enabled': True,
        'manufacturer_access': True,
        'can_upload_video': True,
        'social_publishing': True,
        'can_upload_pdf': True,
        'can_upload_certificates': True,
        'can_access_rfq': True,
        'max_quote_responses_per_month': -1,
        'quote_responses_per_month': -1,
        'quote_priority': 85,
        'admin_assisted_quotes': True,
        'quote_chat_enabled': True,
        'can_receive_direct_enquiries': True,
        'can_show_phone': True,
        'can_show_whatsapp': True,
        'can_receive_callback_requests': True,
        'can_show_direct_contact_badge': True,
        'lead_tracking_enabled': True,
        'hide_phone_until_click': False,
        'can_use_boosting': True,
        'can_show_on_homepage': True,
        'can_access_analytics': True,
        'can_access_advanced_analytics': True,
        'can_access_ads': True,
        'priority_score': 85,
        'commission_rate': 4,
        'support_level': 'priority',
        'badge_level': 'Special Vendor',
    },
    'enterprise': {
        'max_products': -1,
        'featured_products': -1,
        'max_images_per_product': 30,
        'max_variants_per_product': -1,
        'chat_enabled': True,
        'store_reviews_enabled': True,
        'manufacturer_access': True,
        'can_upload_video': True,
        'social_publishing': True,
        'can_upload_pdf': True,
        'can_upload_certificates': True,
        'can_access_rfq': True,
        'max_quote_responses_per_month': -1,
        'quote_responses_per_month': -1,
        'quote_priority': 100,
        'admin_assisted_quotes': True,
        'quote_chat_enabled': True,
        'can_receive_direct_enquiries': True,
        'can_show_phone': True,
        'can_show_whatsapp': True,
        'can_receive_callback_requests': True,
        'can_show_direct_contact_badge': True,
        'lead_tracking_enabled': True,
        'hide_phone_until_click': False,
        'can_use_boosting': True,
        'can_show_on_homepage': True,
        'can_access_analytics': True,
        'can_access_advanced_analytics': True,
        'can_access_ads': True,
        'priority_score': 100,
        'commission_rate': 2,
        'support_level': 'dedicated',
        'badge_level': 'Enterprise Vendor',
    },
}


def normalize_subscription_tier(tier):
    tier = (tier or 'free').lower()
    tier = LEGACY_TIER_MAP.get(tier, tier)
    return tier if tier in TIER_LIMITS else 'free'


def get_tier_limits(tier):
    tier = normalize_subscription_tier(tier)
    limits = TIER_LIMITS[tier].copy()
    try:
        plan = SubscriptionPlan.objects.filter(name__iexact=tier, is_active=True).first()
    except Exception:
        plan = None
    if not plan:
        return limits

    field_map = {
        'max_products': 'max_products',
        'featured_products': 'featured_products',
        'max_images_per_product': 'max_images_per_product',
        'max_variants_per_product': 'max_variants_per_product',
        'can_upload_video': 'can_upload_video',
        'can_upload_pdf': 'can_upload_pdf',
        'can_upload_certificates': 'can_upload_certificates',
        'can_access_rfq': 'can_access_rfq',
        'can_receive_direct_enquiries': 'can_receive_direct_enquiries',
        'can_show_phone': 'can_show_phone',
        'can_show_whatsapp': 'can_show_whatsapp',
        'can_receive_callback_requests': 'can_receive_callback_requests',
        'can_show_direct_contact_badge': 'can_show_direct_contact_badge',
        'lead_tracking_enabled': 'lead_tracking_enabled',
        'hide_phone_until_click': 'hide_phone_until_click',
        'can_use_boosting': 'can_use_boosting',
        'can_show_on_homepage': 'can_show_on_homepage',
        'can_access_analytics': 'can_access_analytics',
        'can_access_advanced_analytics': 'can_access_advanced_analytics',
        'can_access_ads': 'can_access_ads',
        'priority_score': 'priority_score',
        'support_level': 'support_level',
        'badge_level': 'badge_label',
    }
    for limit_key, plan_field in field_map.items():
        if hasattr(plan, plan_field):
            limits[limit_key] = getattr(plan, plan_field)
    limits['commission_rate'] = plan.commission_rate
    limits['chat_enabled'] = bool(plan.can_receive_direct_enquiries or limits.get('chat_enabled'))
    return limits


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
        expiry = getattr(vendor_profile, 'subscription_expires_at', None) or vendor_profile.subscription_expiry
        if expiry and expiry <= timezone.now():
            return 'free'
        return normalize_subscription_tier(vendor_profile.subscription_tier)

    return 'free'


def user_subscription_limits(user):
    return get_tier_limits(user_subscription_tier(user))


def user_has_paid_subscription(user):
    limits = user_subscription_limits(user)
    return limits['chat_enabled'] and tier_is_paid(user_subscription_tier(user))


def subscription_label(tier):
    labels = {
        'free': 'Free Vendor',
        'basic': 'Basic Vendor',
        'plus': 'Plus Vendor',
        'pro': 'Pro Vendor',
        'special': 'Special Vendor',
        'enterprise': 'Enterprise Vendor',
    }
    return labels[normalize_subscription_tier(tier)]


def apply_vendor_subscription_benefits(vendor, plan):
    """Apply one subscription source of truth to a VendorProfile."""
    if hasattr(vendor, 'vendor_profile'):
        vendor = vendor.vendor_profile
    tier = normalize_subscription_tier(getattr(plan, 'tier_key', None) or getattr(plan, 'name', None) or plan)
    limits = get_tier_limits(tier)
    vendor.subscription_tier = tier
    vendor.product_limit = limits['max_products']
    vendor.image_limit = limits['max_images_per_product']
    vendor.variant_limit = limits['max_variants_per_product']
    vendor.can_upload_video = limits['can_upload_video']
    vendor.can_upload_pdf = limits['can_upload_pdf']
    vendor.can_upload_certificates = limits['can_upload_certificates']
    vendor.can_access_rfq = limits['can_access_rfq']
    vendor.can_receive_direct_enquiries = limits['can_receive_direct_enquiries']
    vendor.can_use_boosting = limits['can_use_boosting']
    vendor.can_show_on_homepage = limits['can_show_on_homepage']
    vendor.can_access_analytics = limits['can_access_analytics']
    vendor.can_access_advanced_analytics = limits['can_access_advanced_analytics']
    vendor.can_access_ads = limits['can_access_ads']
    vendor.priority_score = limits['priority_score']
    vendor.support_level = limits['support_level']
    vendor.badge_level = limits['badge_level']
    vendor.save(update_fields=[
        'subscription_tier',
        'product_limit',
        'image_limit',
        'variant_limit',
        'can_upload_video',
        'can_upload_pdf',
        'can_upload_certificates',
        'can_access_rfq',
        'can_receive_direct_enquiries',
        'can_use_boosting',
        'can_show_on_homepage',
        'can_access_analytics',
        'can_access_advanced_analytics',
        'can_access_ads',
        'priority_score',
        'support_level',
        'badge_level',
        'updated_at',
    ])
    return vendor

class SubscriptionPlan(BaseModel):
    """One account plan shared by every approved Arolana role."""
    name = models.CharField(max_length=50, unique=True)
    display_name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    
    # Pricing
    price_monthly = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    price_yearly = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    # Features
    max_products = models.IntegerField(default=10)
    featured_products = models.IntegerField(default=0)
    max_images_per_product = models.IntegerField(default=3, help_text="-1 means unlimited.")
    max_variants_per_product = models.IntegerField(default=0, help_text="-1 means unlimited.")
    commission_rate = models.DecimalField(max_digits=5, decimal_places=2, default=10.00)
    
    # Benefits
    priority_support = models.BooleanField(default=False)
    analytics_access = models.BooleanField(default=False)
    promotion_opportunities = models.BooleanField(default=False)
    dedicated_account_manager = models.BooleanField(default=False)
    can_upload_video = models.BooleanField(default=False)
    can_upload_pdf = models.BooleanField(default=False)
    can_upload_certificates = models.BooleanField(default=False)
    can_access_rfq = models.BooleanField(default=False)
    can_receive_direct_enquiries = models.BooleanField(default=False)
    can_show_phone = models.BooleanField(default=False, help_text="Allow approved vendors on this plan to expose a direct phone number when the vendor also opts in.")
    can_show_whatsapp = models.BooleanField(default=False, help_text="Allow approved vendors on this plan to expose WhatsApp when the vendor also opts in.")
    can_receive_callback_requests = models.BooleanField(default=False, help_text="Allow customers to request a callback without exposing the vendor phone.")
    can_show_direct_contact_badge = models.BooleanField(default=False, help_text="Show premium direct-contact badge on storefronts and mobile.")
    lead_tracking_enabled = models.BooleanField(default=False, help_text="Record phone/WhatsApp/callback leads for this plan.")
    hide_phone_until_click = models.BooleanField(default=True, help_text="Mask phone in listing payloads and reveal only through a tracked backend action.")
    can_use_boosting = models.BooleanField(default=False)
    can_show_on_homepage = models.BooleanField(default=False)
    can_access_analytics = models.BooleanField(default=True)
    can_access_advanced_analytics = models.BooleanField(default=False)
    can_access_ads = models.BooleanField(default=False)
    priority_score = models.IntegerField(default=0)
    support_level = models.CharField(max_length=40, default='basic')
    badge_label = models.CharField(max_length=80, default='Free Vendor')
    feature_bullets = models.JSONField(default=list, blank=True)
    role_entitlements = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Optional role-specific overrides keyed by vendor, manufacturer, or provider. "
            "The shared entitlement resolver merges these with Arolana's safe defaults."
        ),
    )
    
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
    def vendor_label(self):
        return subscription_label(self.tier_key)

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
        if limits.get('store_reviews_enabled'):
            features.append("Vendor store reviews and comments")
        if limits['manufacturer_access']:
            features.append("Manufacturer tools")
        if isinstance(self.feature_bullets, list) and self.feature_bullets:
            return [str(item) for item in self.feature_bullets if str(item).strip()]
        if self.priority_support:
            features.append("Priority support")
        if self.analytics_access:
            features.append("Analytics")
        if self.dedicated_account_manager:
            features.append("Dedicated account manager")
        return features

class VendorSubscription(BaseModel):
    """Account-level subscription (legacy model name retained for API compatibility)."""

    STATUS_INACTIVE = "inactive"
    STATUS_PENDING_PAYMENT = "pending_payment"
    STATUS_TRIAL = "trial"
    STATUS_ACTIVE = "active"
    STATUS_PAST_DUE = "past_due"
    STATUS_GRACE_PERIOD = "grace_period"
    STATUS_EXPIRED = "expired"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_INACTIVE, "Inactive"),
        (STATUS_PENDING_PAYMENT, "Pending payment"),
        (STATUS_TRIAL, "Trial"),
        (STATUS_ACTIVE, "Active"),
        (STATUS_PAST_DUE, "Past due"),
        (STATUS_GRACE_PERIOD, "Grace period"),
        (STATUS_EXPIRED, "Expired"),
        (STATUS_CANCELLED, "Cancelled"),
    ]
    BILLING_MONTHLY = "monthly"
    BILLING_YEARLY = "yearly"
    BILLING_CYCLE_CHOICES = [
        (BILLING_MONTHLY, "Monthly"),
        (BILLING_YEARLY, "Yearly"),
    ]
    CHANGE_UPGRADE = "upgrade"
    CHANGE_DOWNGRADE = "downgrade"
    CHANGE_CHOICES = [
        (CHANGE_UPGRADE, "Upgrade"),
        (CHANGE_DOWNGRADE, "Downgrade"),
    ]

    vendor = models.ForeignKey(User, on_delete=models.CASCADE, related_name='subscriptions')
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.CASCADE)
    start_date = models.DateTimeField(default=timezone.now)
    end_date = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    auto_renew = models.BooleanField(default=True)
    payment_method = models.CharField(max_length=50, blank=True)
    transaction_id = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default=STATUS_ACTIVE, db_index=True)
    billing_cycle = models.CharField(
        max_length=12,
        choices=BILLING_CYCLE_CHOICES,
        default=BILLING_MONTHLY,
    )
    currency = models.CharField(max_length=10, default="NGN")
    payment_state = models.CharField(max_length=24, default="paid", db_index=True)
    trial_ends_at = models.DateTimeField(blank=True, null=True)
    grace_period_ends_at = models.DateTimeField(blank=True, null=True)
    cancel_at_period_end = models.BooleanField(default=False)
    cancellation_requested_at = models.DateTimeField(blank=True, null=True)
    cancelled_at = models.DateTimeField(blank=True, null=True)
    cancellation_reason = models.TextField(blank=True)
    pending_plan = models.ForeignKey(
        SubscriptionPlan,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="pending_account_subscriptions",
    )
    pending_change_type = models.CharField(max_length=16, choices=CHANGE_CHOICES, blank=True)
    pending_change_effective_at = models.DateTimeField(blank=True, null=True)
    source_platform = models.CharField(max_length=30, blank=True)
    
    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=["transaction_id"],
                condition=~models.Q(transaction_id=""),
                name="uniq_vendor_subscription_transaction_nonblank",
            ),
        ]
        indexes = [
            models.Index(fields=["vendor", "is_active", "status", "end_date"]),
            models.Index(fields=["status", "end_date"]),
        ]
    
    def __str__(self):
        return f"{self.vendor.username} - {self.plan.display_name}"

    @property
    def is_current(self):
        now = timezone.now()
        if not self.is_active:
            return False
        if self.status in {self.STATUS_ACTIVE, self.STATUS_TRIAL}:
            return self.end_date > now
        return bool(
            self.status in {self.STATUS_PAST_DUE, self.STATUS_GRACE_PERIOD}
            and self.grace_period_ends_at
            and self.grace_period_ends_at > now
        )


class SubscriptionPayment(BaseModel):
    """Immutable subscription receipt linked to a server-verified payment."""

    STATUS_PENDING = "pending"
    STATUS_SUCCESS = "success"
    STATUS_FAILED = "failed"
    STATUS_REFUNDED = "refunded"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_SUCCESS, "Success"),
        (STATUS_FAILED, "Failed"),
        (STATUS_REFUNDED, "Refunded"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="subscription_payments")
    subscription = models.ForeignKey(
        VendorSubscription,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="subscription_payments",
    )
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.PROTECT, related_name="subscription_payments")
    payment_transaction = models.OneToOneField(
        "arolana_payments.PaymentTransaction",
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        related_name="subscription_payment_record",
    )
    billing_cycle = models.CharField(max_length=12, choices=VendorSubscription.BILLING_CYCLE_CHOICES)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=10, default="NGN")
    gateway = models.CharField(max_length=40, blank=True)
    reference = models.CharField(max_length=200, unique=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    verified_at = models.DateTimeField(blank=True, null=True)
    activated_at = models.DateTimeField(blank=True, null=True)
    source_platform = models.CharField(max_length=30, blank=True)
    verification_summary = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "status", "-created_at"]),
            models.Index(fields=["plan", "billing_cycle", "status"]),
        ]

    def __str__(self):
        return f"{self.reference} - {self.plan.tier_key} - {self.status}"


class SubscriptionHistory(models.Model):
    """Append-only lifecycle audit trail."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="subscription_history_events")
    subscription = models.ForeignKey(
        VendorSubscription,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="history_events",
    )
    event_type = models.CharField(max_length=50, db_index=True)
    previous_plan = models.ForeignKey(
        SubscriptionPlan,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="subscription_history_previous",
    )
    new_plan = models.ForeignKey(
        SubscriptionPlan,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="subscription_history_new",
    )
    previous_status = models.CharField(max_length=24, blank=True)
    new_status = models.CharField(max_length=24, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="subscription_changes_made",
    )
    source_platform = models.CharField(max_length=30, blank=True)
    payment_reference = models.CharField(max_length=200, blank=True, db_index=True)
    effective_at = models.DateTimeField(default=timezone.now)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "event_type", "-created_at"])]

    def __str__(self):
        return f"{self.user} - {self.event_type}"


class SubscriptionReminderLog(models.Model):
    """Idempotency guard for lifecycle reminders across all delivery channels."""

    subscription = models.ForeignKey(VendorSubscription, on_delete=models.CASCADE, related_name="reminder_logs")
    event_key = models.CharField(max_length=100)
    channel = models.CharField(max_length=20, default="in_app")
    sent_at = models.DateTimeField(default=timezone.now)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-sent_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["subscription", "event_key", "channel"],
                name="unique_subscription_reminder_event_channel",
            )
        ]

    def __str__(self):
        return f"{self.subscription_id} - {self.event_key} - {self.channel}"
