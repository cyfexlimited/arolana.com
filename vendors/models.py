from decimal import Decimal

from django.db import models
from django.db.models import Avg
from django.utils import timezone
from accounts.models import User
from core.models import BaseModel

class VendorProfile(BaseModel):
    SUBSCRIPTION_TIERS = [
        ('free', 'Free Vendor'),
        ('basic', 'Basic Vendor'),
        ('plus', 'Plus Vendor'),
        ('pro', 'Pro Vendor'),
        ('special', 'Special Vendor'),
        ('enterprise', 'Enterprise Vendor'),
    ]

    VENDOR_TYPE_CHOICES = [
        ('manufacturer', 'Manufacturer'),
        ('distributor', 'Distributor'),
        ('wholesaler', 'Wholesaler'),
        ('retailer', 'Retailer'),
        ('service_provider', 'Service Provider'),
    ]

    APPROVAL_STATUS_CHOICES = [
        ('pending', 'Pending Admin Review'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('suspended', 'Suspended'),
    ]
    
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='vendor_profile')
    store_name = models.CharField(max_length=200)
    store_slug = models.SlugField(unique=True)
    store_logo = models.ImageField(upload_to='vendors/logos/', null=True, blank=True)
    store_banner = models.ImageField(upload_to='vendors/banners/', null=True, blank=True)
    description = models.TextField()
    company_name = models.CharField(max_length=220, blank=True)
    vendor_type = models.CharField(max_length=30, choices=VENDOR_TYPE_CHOICES, default='retailer', db_index=True)
    country = models.CharField(max_length=100, blank=True, default='Nigeria')
    address_line_1 = models.CharField(max_length=255, blank=True, default='')
    city = models.CharField(max_length=120, blank=True, default='')
    state = models.CharField(max_length=120, blank=True, default='')
    business_address = models.TextField(blank=True)
    manufacturer_address = models.TextField(blank=True)
    warehouse_address = models.TextField(blank=True)
    support_email = models.EmailField(blank=True)
    support_phone = models.CharField(max_length=50, blank=True)
    business_phone = models.CharField(
        max_length=50,
        blank=True,
        help_text="Customer-facing business phone. Exposed only when vendor and subscription permissions allow it."
    )
    whatsapp_number = models.CharField(
        max_length=50,
        blank=True,
        help_text="Customer-facing WhatsApp number. Exposed only when vendor and subscription permissions allow it."
    )
    allow_phone_display = models.BooleanField(default=False)
    allow_whatsapp_display = models.BooleanField(default=False)
    allow_callback_requests = models.BooleanField(default=True)
    website = models.URLField(blank=True)
    preferred_language = models.CharField(max_length=20, default='english', blank=True)
    preferred_currency = models.CharField(max_length=10, default='NGN', blank=True)
    is_verified = models.BooleanField(default=False)
    verification_documents = models.FileField(upload_to='vendors/documents/', null=True, blank=True)
    approval_status = models.CharField(max_length=20, choices=APPROVAL_STATUS_CHOICES, default='pending', db_index=True)
    approval_note = models.TextField(blank=True)
    rejection_reason = models.TextField(blank=True)
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_vendor_profiles')
    approved_at = models.DateTimeField(null=True, blank=True)
    
    # Subscription tier for priority sorting
    subscription_tier = models.CharField(max_length=20, choices=SUBSCRIPTION_TIERS, default='free')
    subscription_active = models.BooleanField(default=False, db_index=True)
    subscription_started_at = models.DateTimeField(null=True, blank=True)
    subscription_expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    subscription_expiry = models.DateTimeField(null=True, blank=True)
    product_limit = models.IntegerField(default=1)
    image_limit = models.IntegerField(default=3)
    variant_limit = models.IntegerField(default=0)
    can_upload_video = models.BooleanField(default=False)
    can_upload_pdf = models.BooleanField(default=False)
    can_upload_certificates = models.BooleanField(default=False)
    can_access_rfq = models.BooleanField(default=False)
    can_receive_direct_enquiries = models.BooleanField(default=False)
    can_use_boosting = models.BooleanField(default=False)
    can_show_on_homepage = models.BooleanField(default=False)
    can_access_analytics = models.BooleanField(default=False)
    can_access_advanced_analytics = models.BooleanField(default=False)
    can_access_ads = models.BooleanField(default=False)
    support_level = models.CharField(max_length=40, default='basic')
    badge_level = models.CharField(max_length=80, default='Free Vendor')
    priority_score = models.IntegerField(default=0, help_text="Higher score = better placement")

    # Storefront customization
    store_slogan = models.CharField(max_length=180, blank=True, default='')
    storefront_accent_color = models.CharField(
        max_length=20,
        blank=True,
        default='#FF7A00',
        help_text="Storefront accent color. Example: #FF7A00."
    )
    store_video_url = models.URLField(blank=True)
    store_gallery_notes = models.TextField(
        blank=True,
        help_text="Optional storefront gallery image URLs or notes, one per line."
    )
    featured_categories = models.TextField(blank=True, help_text="Featured storefront categories, one per line.")
    featured_products_note = models.TextField(blank=True, help_text="Optional featured product notes for the storefront.")
    business_hours = models.TextField(blank=True)
    return_policy = models.TextField(blank=True)
    warranty_note = models.TextField(blank=True)
    delivery_note = models.TextField(blank=True)
    
    # Ratings and sales
    rating_avg = models.DecimalField(max_digits=3, decimal_places=2, default=0)
    total_sales = models.IntegerField(default=0)
    total_reviews = models.IntegerField(default=0)
    
    # Subscription/Followers
    followers_count = models.IntegerField(default=0)
    
    # Vendor performance metrics
    response_time = models.CharField(max_length=50, default='< 1 hour', blank=True)
    fulfillment_rate = models.DecimalField(max_digits=5, decimal_places=2, default=99.5)
    return_rate = models.DecimalField(max_digits=5, decimal_places=2, default=2.5)

    # Delivery pickup location
    pickup_contact_name = models.CharField(
        max_length=160,
        blank=True,
        help_text="Name riders should ask for at pickup. Defaults to store name when blank."
    )
    pickup_phone = models.CharField(
        max_length=50,
        blank=True,
        help_text="Phone number riders should call at pickup."
    )
    pickup_address = models.TextField(
        blank=True,
        help_text="Exact store/warehouse pickup address used for checkout delivery pricing."
    )
    pickup_latitude = models.DecimalField(
        max_digits=10,
        decimal_places=7,
        null=True,
        blank=True,
        help_text="Pickup map latitude for exact rider distance pricing."
    )
    pickup_longitude = models.DecimalField(
        max_digits=10,
        decimal_places=7,
        null=True,
        blank=True,
        help_text="Pickup map longitude for exact rider distance pricing."
    )
    
    # Badges
    is_top_rated = models.BooleanField(default=False)
    is_best_seller = models.BooleanField(default=False)
    is_trusted = models.BooleanField(default=False)
    manufacturer_verified = models.BooleanField(default=False, db_index=True)
    manufacturer_badge_label = models.CharField(max_length=80, blank=True, default='Verified Manufacturer')

    # Manufacturer / factory profile
    factory_name = models.CharField(max_length=220, blank=True)
    factory_video_url = models.URLField(blank=True)
    years_in_business = models.PositiveIntegerField(null=True, blank=True)
    number_of_employees = models.PositiveIntegerField(null=True, blank=True)
    production_capacity = models.CharField(max_length=220, blank=True)
    quality_control_details = models.TextField(blank=True)
    export_countries = models.TextField(blank=True, help_text="Comma-separated export countries or regions.")
    main_product_categories = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-priority_score', '-subscription_tier', '-rating_avg', '-total_sales']
        indexes = [
            models.Index(fields=['vendor_type', 'approval_status']),
            models.Index(fields=['manufacturer_verified', '-priority_score']),
        ]
    
    def __str__(self):
        return self.store_name

    @property
    def display_name(self):
        user_name = ''
        if self.user_id:
            user_name = self.user.get_full_name() or self.user.username or self.user.email
        return self.company_name or self.store_name or user_name or "Arolana Vendor"

    @property
    def active_plan_name(self):
        try:
            return self.get_subscription_display().get('text') or self.badge_level or "Free Vendor"
        except Exception:
            return self.badge_level or "Free Vendor"

    @property
    def location_label(self):
        parts = [self.city, self.state]
        location = ", ".join([str(part).strip() for part in parts if str(part or "").strip()])
        if location:
            return location
        parts = [self.state, self.country]
        return ", ".join([str(part).strip() for part in parts if str(part or "").strip()])

    @property
    def storefront_accent(self):
        value = (self.storefront_accent_color or '').strip()
        if value.startswith('#') and len(value) in (4, 7):
            return value
        return '#FF7A00'

    @property
    def featured_category_list(self):
        return [item.strip() for item in (self.featured_categories or '').splitlines() if item.strip()]

    @property
    def store_gallery_list(self):
        return [item.strip() for item in (self.store_gallery_notes or '').splitlines() if item.strip()]

    @property
    def address_is_complete(self):
        return bool(
            (self.address_line_1 or self.business_address or self.pickup_address)
            and self.city
            and self.state
            and self.country
        )

    @property
    def pickup_location_is_ready(self):
        return bool(self.pickup_address and self.pickup_latitude and self.pickup_longitude)
    
    def get_absolute_url(self):
        from django.urls import reverse
        return reverse('vendors:detail', args=[self.store_slug])
    
    def get_subscription_display(self):
        """Get formatted subscription display"""
        displays = {
            'free': {'color': 'gray', 'icon': 'fa-user', 'text': 'Free Vendor', 'badge_class': 'bg-gray-500'},
            'basic': {'color': 'blue', 'icon': 'fa-chart-line', 'text': 'Basic Vendor', 'badge_class': 'bg-blue-500'},
            'plus': {'color': 'cyan', 'icon': 'fa-layer-group', 'text': 'Plus Vendor', 'badge_class': 'bg-cyan-500'},
            'pro': {'color': 'purple', 'icon': 'fa-gem', 'text': 'Pro Vendor', 'badge_class': 'bg-purple-500'},
            'special': {'color': 'yellow', 'icon': 'fa-crown', 'text': 'Special Vendor', 'badge_class': 'bg-yellow-500'},
            'enterprise': {'color': 'indigo', 'icon': 'fa-building', 'text': 'Enterprise Vendor', 'badge_class': 'bg-indigo-600'},
        }
        try:
            from subscriptions.models import normalize_subscription_tier
            tier = normalize_subscription_tier(self.subscription_tier)
        except Exception:
            tier = self.subscription_tier
        return displays.get(tier, displays['free'])
    
    def get_priority_multiplier(self):
        """Get multiplier for display priority based on subscription"""
        multipliers = {
            'free': 1,
            'basic': 2,
            'plus': 3,
            'pro': 4,
            'special': 5,
            'enterprise': 6,
        }
        try:
            from subscriptions.models import normalize_subscription_tier
            tier = normalize_subscription_tier(self.subscription_tier)
        except Exception:
            tier = self.subscription_tier
        return multipliers.get(tier, 1)
    
    def has_active_subscription(self):
        """Check if vendor has an active paid subscription"""
        try:
            from subscriptions.models import user_has_paid_subscription
            return user_has_paid_subscription(self.user)
        except Exception:
            expiry = self.subscription_expires_at or self.subscription_expiry
            if expiry:
                return expiry > timezone.now() and self.subscription_tier != 'free'
            return self.subscription_tier != 'free'

    @property
    def subscription_end_at(self):
        return self.subscription_expires_at or self.subscription_expiry

    @property
    def kyc_status(self):
        try:
            return self.kyc_record.kyc_status
        except Exception:
            return 'not_started'

    def get_kyc_status_display(self):
        try:
            return self.kyc_record.get_kyc_status_display()
        except Exception:
            return 'Not Started'

    def has_verified_kyc(self):
        return self.is_verified and self.kyc_status in ['approved', 'verified']

    @property
    def direct_contact_eligible(self):
        return bool(
            self.is_active
            and self.approval_status == 'approved'
            and (self.is_verified or self.manufacturer_verified or self.has_verified_kyc())
        )

    @property
    def profile_completion_percent(self):
        checks = [
            bool(self.store_name),
            bool(self.company_name),
            bool(self.description),
            bool(self.store_logo),
            bool(self.store_banner),
            bool(self.country),
            bool(self.business_address),
            bool(self.support_email or self.user.email),
            bool(self.support_phone or self.pickup_phone),
            bool(self.pickup_address),
            self.has_verified_kyc(),
            self.bank_accounts.exists(),
            self.subscription_tier != 'free' or bool(self.subscription_active),
        ]
        return int((sum(1 for item in checks if item) / len(checks)) * 100)

    @property
    def can_upload_products(self):
        return bool(
            self.is_active
            and self.approval_status == 'approved'
            and (self.has_verified_kyc() or self.is_verified)
        )

    @property
    def subscription_plan_label(self):
        try:
            from subscriptions.models import subscription_label
            return subscription_label(self.subscription_tier)
        except Exception:
            return self.get_subscription_display()['text']
    
    def update_rating(self):
        """Update vendor rating based on product and storefront reviews."""
        from products.models import ProductReview
        reviews = ProductReview.objects.filter(product__vendor=self.user, is_active=True)
        store_reviews = self.store_reviews.filter(is_active=True)
        product_count = reviews.count()
        store_count = store_reviews.count()
        total_count = product_count + store_count
        if total_count:
            product_total = sum(reviews.values_list('rating', flat=True))
            store_total = sum(store_reviews.values_list('rating', flat=True))
            self.rating_avg = round((product_total + store_total) / total_count, 2)
            self.total_reviews = total_count
        else:
            self.rating_avg = 0
            self.total_reviews = 0
        self.save(update_fields=['rating_avg', 'total_reviews', 'updated_at'])
    
    def update_followers_count(self):
        """Update followers count"""
        self.followers_count = self.followers.count()
        self.save()
    
    def get_badges(self):
        """Get all applicable badges for this vendor"""
        badges = []
        if self.is_verified:
            badges.append({'text': f'Verified {self.get_vendor_type_display()}', 'color': 'green', 'icon': 'fa-check-circle'})
        if self.is_top_rated:
            badges.append({'text': 'Top Rated', 'color': 'yellow', 'icon': 'fa-star'})
        if self.is_best_seller:
            badges.append({'text': 'Best Seller', 'color': 'orange', 'icon': 'fa-trophy'})
        if self.is_trusted:
            badges.append({'text': 'Trusted', 'color': 'blue', 'icon': 'fa-shield-alt'})
        if self.vendor_type == 'manufacturer' and self.manufacturer_verified:
            badges.append({'text': self.manufacturer_badge_label or 'Verified Manufacturer', 'color': 'indigo', 'icon': 'fa-industry'})
        badge = self.get_subscription_display()
        badges.append({'text': self.badge_level or badge['text'], 'color': badge['color'], 'icon': badge['icon']})
        return badges


class VendorFactoryPhoto(BaseModel):
    vendor = models.ForeignKey(VendorProfile, on_delete=models.CASCADE, related_name='factory_photos')
    image = models.ImageField(upload_to='vendors/factory/')
    caption = models.CharField(max_length=180, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['sort_order', '-created_at']

    def __str__(self):
        return f"{self.vendor.store_name} factory photo"


class VendorBankAccount(BaseModel):
    BANK_COUNTRY_CHOICES = [
        ('nigeria', 'Nigeria'),
        ('china', 'China'),
        ('usa', 'USA'),
        ('uk', 'UK'),
        ('canada', 'Canada'),
        ('other', 'Other'),
    ]

    vendor = models.ForeignKey(VendorProfile, on_delete=models.CASCADE, related_name='bank_accounts')
    bank_name = models.CharField(max_length=180)
    account_name = models.CharField(max_length=180)
    account_number = models.CharField(max_length=80)
    bank_country = models.CharField(max_length=30, choices=BANK_COUNTRY_CHOICES, default='nigeria')
    swift_code = models.CharField(max_length=40, blank=True)
    iban = models.CharField(max_length=80, blank=True)
    routing_number = models.CharField(max_length=80, blank=True)
    sort_code = models.CharField(max_length=80, blank=True)
    bank_address = models.TextField(blank=True)
    preferred_currency = models.CharField(max_length=10, default='NGN')
    is_default = models.BooleanField(default=True, db_index=True)
    is_verified = models.BooleanField(default=False, db_index=True)
    verified_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='verified_vendor_bank_accounts')
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-is_default', '-created_at']
        indexes = [
            models.Index(fields=['vendor', 'is_default']),
            models.Index(fields=['vendor', 'is_verified']),
        ]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_default:
            VendorBankAccount.objects.filter(vendor=self.vendor, is_default=True).exclude(pk=self.pk).update(is_default=False)

    def __str__(self):
        return f"{self.vendor.store_name} - {self.bank_name}"


class VendorWallet(BaseModel):
    vendor = models.OneToOneField(VendorProfile, on_delete=models.CASCADE, related_name='wallet')
    available_balance = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    pending_balance = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    withdrawable_balance = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    total_earnings = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    total_withdrawn = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    currency = models.CharField(max_length=10, default='NGN')

    def __str__(self):
        return f"{self.vendor.store_name} wallet"


class VendorTransaction(BaseModel):
    TRANSACTION_TYPES = [
        ('order_earning', 'Order Earning'),
        ('commission_deduction', 'Commission Deduction'),
        ('withdrawal_request', 'Withdrawal Request'),
        ('withdrawal_approved', 'Withdrawal Approved'),
        ('withdrawal_rejected', 'Withdrawal Rejected'),
        ('refund', 'Refund'),
        ('adjustment', 'Adjustment'),
        ('subscription_payment', 'Subscription Payment'),
    ]

    vendor = models.ForeignKey(VendorProfile, on_delete=models.CASCADE, related_name='transactions')
    wallet = models.ForeignKey(VendorWallet, on_delete=models.CASCADE, related_name='transactions')
    transaction_type = models.CharField(max_length=40, choices=TRANSACTION_TYPES, db_index=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    balance_after = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    reference = models.CharField(max_length=120, blank=True, db_index=True)
    description = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['vendor', '-created_at']),
            models.Index(fields=['transaction_type', '-created_at']),
        ]

    def __str__(self):
        return f"{self.vendor.store_name} {self.transaction_type} {self.amount}"


class VendorWithdrawal(BaseModel):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('under_review', 'Under Review'),
        ('approved', 'Approved'),
        ('paid', 'Paid'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
    ]

    vendor = models.ForeignKey(VendorProfile, on_delete=models.CASCADE, related_name='withdrawals')
    bank_account = models.ForeignKey(VendorBankAccount, on_delete=models.SET_NULL, null=True, blank=True, related_name='withdrawals')
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=10, default='NGN')
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='pending', db_index=True)
    admin_note = models.TextField(blank=True)
    rejection_reason = models.TextField(blank=True)
    requested_at = models.DateTimeField(default=timezone.now)
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_vendor_withdrawals')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-requested_at']
        indexes = [
            models.Index(fields=['vendor', 'status']),
            models.Index(fields=['status', '-requested_at']),
        ]

    def __str__(self):
        return f"{self.vendor.store_name} withdrawal {self.amount} {self.status}"


class VendorRFQ(BaseModel):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('quoted', 'Quoted'),
        ('accepted', 'Accepted'),
        ('rejected', 'Rejected'),
        ('expired', 'Expired'),
        ('closed', 'Closed'),
    ]

    vendor = models.ForeignKey(VendorProfile, on_delete=models.CASCADE, related_name='rfqs')
    customer = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='vendor_rfqs')
    product = models.ForeignKey('products.Product', on_delete=models.SET_NULL, null=True, blank=True, related_name='rfqs')
    quantity = models.PositiveIntegerField(default=1)
    budget = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    country = models.CharField(max_length=100, blank=True)
    delivery_location = models.TextField(blank=True)
    message = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', db_index=True)
    quote_price = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    quote_lead_time_days = models.PositiveIntegerField(null=True, blank=True)
    vendor_note = models.TextField(blank=True)
    quoted_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['vendor', 'status']),
            models.Index(fields=['status', '-created_at']),
        ]

    def __str__(self):
        return f"RFQ #{self.id} - {self.vendor.store_name}"

class VendorFollow(BaseModel):
    """Track users who follow vendors"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='following_vendors')
    vendor = models.ForeignKey(VendorProfile, on_delete=models.CASCADE, related_name='followers')
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['user', 'vendor']
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.user.username} follows {self.vendor.store_name}"


class VendorReview(BaseModel):
    """Customer reviews for a vendor storefront."""
    vendor = models.ForeignKey(VendorProfile, on_delete=models.CASCADE, related_name='store_reviews')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='vendor_store_reviews')
    rating = models.PositiveSmallIntegerField(default=5)
    title = models.CharField(max_length=160, blank=True)
    comment = models.TextField()
    is_active = models.BooleanField(default=True)
    is_verified_customer = models.BooleanField(default=False)
    helpful_count = models.IntegerField(default=0)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['vendor', 'is_active', '-created_at']),
            models.Index(fields=['rating']),
        ]

    def __str__(self):
        return f"{self.vendor.store_name} review by {self.user.username}"

    def save(self, *args, **kwargs):
        self.rating = max(1, min(5, int(self.rating or 5)))
        super().save(*args, **kwargs)
        self.vendor.update_rating()

    def delete(self, *args, **kwargs):
        vendor = self.vendor
        super().delete(*args, **kwargs)
        vendor.update_rating()


class VendorCallbackRequest(BaseModel):
    STATUS_CHOICES = [
        ('new', 'New'),
        ('assigned', 'Assigned'),
        ('contacted', 'Contacted'),
        ('resolved', 'Resolved'),
        ('closed', 'Closed'),
    ]
    URGENCY_CHOICES = [
        ('normal', 'Normal'),
        ('high', 'High'),
        ('urgent', 'Urgent'),
    ]

    vendor = models.ForeignKey(VendorProfile, on_delete=models.CASCADE, related_name='callback_requests')
    product = models.ForeignKey('products.Product', on_delete=models.SET_NULL, null=True, blank=True, related_name='vendor_callback_requests')
    customer_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='vendor_callback_requests')
    customer_name = models.CharField(max_length=180, blank=True)
    customer_phone = models.CharField(max_length=50, blank=True)
    customer_email = models.EmailField(blank=True)
    message = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new', db_index=True)
    urgency = models.CharField(max_length=20, choices=URGENCY_CHOICES, default='normal', db_index=True)
    assigned_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_vendor_callback_requests')
    contacted_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    admin_note = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['vendor', 'status', '-created_at']),
            models.Index(fields=['customer_phone', '-created_at']),
        ]

    def __str__(self):
        return f"Callback for {self.vendor.store_name} - {self.customer_name or self.customer_phone or 'Customer'}"


class VendorLead(BaseModel):
    ACTION_CHOICES = [
        ('callback_request', 'Callback request'),
        ('phone_reveal', 'Phone reveal'),
        ('phone_call', 'Phone call'),
        ('call_click', 'Call click'),
        ('whatsapp_click', 'WhatsApp click'),
        ('product_link_shared_to_whatsapp', 'Product link shared to WhatsApp'),
        ('chat_started', 'Chat started'),
        ('chat_message_sent', 'Chat message sent'),
        ('chat_click', 'Chat click'),
        ('add_to_cart', 'Add to cart'),
        ('buy_now_click', 'Buy now click'),
        ('checkout_started', 'Checkout started'),
        ('order_created', 'Order created'),
    ]

    vendor = models.ForeignKey(VendorProfile, on_delete=models.CASCADE, related_name='contact_leads')
    product = models.ForeignKey('products.Product', on_delete=models.SET_NULL, null=True, blank=True, related_name='vendor_contact_leads')
    customer_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='vendor_contact_leads')
    guest_session_key = models.CharField(max_length=80, blank=True, db_index=True)
    action_type = models.CharField(max_length=40, choices=ACTION_CHOICES, db_index=True)
    customer_name = models.CharField(max_length=180, blank=True)
    customer_phone = models.CharField(max_length=50, blank=True)
    customer_email = models.EmailField(blank=True)
    source = models.CharField(max_length=40, blank=True, db_index=True)
    page_url = models.URLField(max_length=800, blank=True)
    product_url = models.URLField(max_length=800, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    country = models.CharField(max_length=8, blank=True, db_index=True)
    currency = models.CharField(max_length=10, blank=True, db_index=True)
    user_agent = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    extra_data = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['vendor', 'action_type', '-created_at']),
            models.Index(fields=['product', '-created_at']),
        ]

    def __str__(self):
        return f"{self.get_action_type_display()} - {self.vendor.store_name}"


class VendorSubscriptionPlan(BaseModel):
    """Vendor subscription plans for premium features"""
    TIER_CHOICES = [
        ('free', 'Free Vendor'),
        ('basic', 'Basic Vendor'),
        ('plus', 'Plus Vendor'),
        ('pro', 'Pro Vendor'),
        ('special', 'Special Vendor'),
        ('enterprise', 'Enterprise Vendor'),
    ]
    
    tier = models.CharField(max_length=20, choices=TIER_CHOICES, unique=True)
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    price_monthly = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    price_yearly = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    # Features
    product_limit = models.IntegerField(default=10)
    featured_products = models.IntegerField(default=0)
    priority_support = models.BooleanField(default=False)
    analytics_access = models.BooleanField(default=False)
    promoted_listing = models.BooleanField(default=False)
    dedicated_account_manager = models.BooleanField(default=False)
    
    # Display
    icon = models.CharField(max_length=50, default='fa-store')
    color = models.CharField(max_length=50, default='blue')
    is_popular = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    order = models.IntegerField(default=0)
    
    class Meta:
        ordering = ['order', 'price_monthly']
    
    def __str__(self):
        return f"{self.name} - ${self.price_monthly}/mo"
    
    def get_features_list(self):
        features = []
        if self.product_limit:
            features.append(f"Up to {self.product_limit} products")
        if self.featured_products:
            features.append(f"{self.featured_products} featured product slots")
        if self.priority_support:
            features.append("Priority support")
        if self.analytics_access:
            features.append("Advanced analytics")
        if self.promoted_listing:
            features.append("Promoted listing")
        if self.dedicated_account_manager:
            features.append("Dedicated account manager")
        return features

class VendorSubscription(BaseModel):
    """Active vendor subscriptions"""
    vendor = models.ForeignKey(User, on_delete=models.CASCADE, related_name='active_subscriptions')
    plan = models.ForeignKey(VendorSubscriptionPlan, on_delete=models.CASCADE)
    start_date = models.DateTimeField(default=timezone.now)
    end_date = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    auto_renew = models.BooleanField(default=False)
    payment_method = models.CharField(max_length=50, blank=True)
    transaction_id = models.CharField(max_length=200, blank=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.vendor.username} - {self.plan.name}"
    
    def is_valid(self):
        return self.is_active and self.end_date >= timezone.now()
    
    def days_remaining(self):
        delta = self.end_date - timezone.now()
        return delta.days
    
    def activate(self):
        """Activate this subscription and update vendor profile"""
        self.is_active = True
        self.save()
        
        # Update vendor profile with subscription tier
        profile = self.vendor.vendor_profile
        profile.subscription_tier = self.plan.tier
        profile.subscription_expiry = self.end_date
        profile.priority_score = self.get_priority_score()
        profile.save()
    
    def get_priority_score(self):
        """Calculate priority score based on plan"""
        scores = {
            'free': 0,
            'basic': 20,
            'plus': 40,
            'pro': 65,
            'special': 85,
            'enterprise': 100,
        }
        try:
            from subscriptions.models import normalize_subscription_tier
            tier = normalize_subscription_tier(self.plan.tier)
        except Exception:
            tier = self.plan.tier
        return scores.get(tier, 0)


from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender=VendorProfile)
def ensure_vendor_wallet(sender, instance, created=False, **kwargs):
    try:
        VendorWallet.objects.get_or_create(vendor=instance, defaults={'currency': 'NGN'})
    except Exception:
        return
