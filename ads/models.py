from django.db import models
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from django.utils.text import slugify
from core.models import BaseModel
from accounts.models import User
import uuid
import json

class AdPlacement(BaseModel):
    """Advanced ad placements with targeting rules"""
    PLACEMENT_TYPES = [
        ('sidebar', 'Sidebar'),
        ('banner', 'Banner'),
        ('footer', 'Footer'),
        ('homepage', 'Homepage'),
        ('popup', 'Popup Modal'),
        ('interstitial', 'Interstitial'),
        ('native', 'Native Ad'),
        ('video', 'Video Ad'),
        ('carousel', 'Carousel'),
        ('sticky', 'Sticky Bottom'),
    ]
    
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    placement_type = models.CharField(max_length=20, choices=PLACEMENT_TYPES, default='sidebar')
    width = models.IntegerField(default=300)
    height = models.IntegerField(default=250)
    is_active = models.BooleanField(default=True)
    priority = models.IntegerField(default=0)
    
    # Advanced targeting
    allowed_devices = models.JSONField(default=list, blank=True,
        help_text="['mobile', 'tablet', 'desktop']")
    allowed_countries = models.JSONField(default=list, blank=True)
    min_visit_count = models.IntegerField(default=0)
    requires_login = models.BooleanField(default=False)
    
    # Rotation settings
    rotation_weight = models.IntegerField(default=1)
    max_impressions_per_session = models.IntegerField(default=0)
    
    class Meta:
        ordering = ['-priority', 'name']

    def __str__(self):
        return f"{self.name} ({self.width}x{self.height})"


class AdCampaign(BaseModel):
    """Enterprise campaign management"""
    CAMPAIGN_TYPES = [
        ('cpc', 'Cost Per Click'),
        ('cpm', 'Cost Per Mille'),
        ('cpa', 'Cost Per Action'),
        ('sponsored', 'Sponsored Product'),
        ('display', 'Display Banner'),
        ('video', 'Video Ad'),
        ('native', 'Native Ad'),
        ('retargeting', 'Retargeting'),
    ]
    
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('pending', 'Pending Approval'),
        ('scheduled', 'Scheduled'),
        ('active', 'Active'),
        ('paused', 'Paused'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
        ('rejected', 'Rejected'),
        ('failed', 'Failed'),
    ]

    OBJECTIVE_SALES = 'sales'
    OBJECTIVE_PRODUCT_VISITS = 'product_visits'
    OBJECTIVE_VIDEO_VIEWS = 'video_views'
    OBJECTIVE_LEADS = 'leads'
    OBJECTIVE_QUOTE_REQUESTS = 'quote_requests'
    OBJECTIVE_MESSAGES = 'messages'
    OBJECTIVE_STORE_VISITS = 'store_visits'
    OBJECTIVE_BRAND_AWARENESS = 'brand_awareness'
    OBJECTIVE_ENGAGEMENT = 'engagement'

    OBJECTIVE_CHOICES = [
        (OBJECTIVE_SALES, 'Sales'),
        (OBJECTIVE_PRODUCT_VISITS, 'Product Visits'),
        (OBJECTIVE_VIDEO_VIEWS, 'Video Views'),
        (OBJECTIVE_LEADS, 'Leads'),
        (OBJECTIVE_QUOTE_REQUESTS, 'Quote Requests'),
        (OBJECTIVE_MESSAGES, 'Messages'),
        (OBJECTIVE_STORE_VISITS, 'Store Visits'),
        (OBJECTIVE_BRAND_AWARENESS, 'Brand Awareness'),
        (OBJECTIVE_ENGAGEMENT, 'Engagement'),
    ]
    
    BUDGET_TYPE = [
        ('daily', 'Daily Budget'),
        ('total', 'Total Budget'),
        ('lifetime', 'Lifetime Budget'),
    ]
    
    name = models.CharField(max_length=200)
    campaign_id = models.CharField(max_length=50, unique=True, blank=True)
    campaign_type = models.CharField(max_length=20, choices=CAMPAIGN_TYPES, default='display')
    objective = models.CharField(max_length=40, choices=OBJECTIVE_CHOICES, null=True, blank=True)
    
    # Budget & Billing
    budget_type = models.CharField(max_length=10, choices=BUDGET_TYPE, default='total')
    daily_budget = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    total_budget = models.DecimalField(max_digits=10, decimal_places=2, default=100.00)
    spent = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    channel_budget_allocations = models.JSONField(
        default=dict,
        blank=True,
        help_text="Optional per-channel intended external budget allocation metadata. Does not move money.",
    )
    
    # Pricing
    bid_strategy = models.CharField(max_length=20, default='auto',
        choices=[('auto', 'Automatic'), ('manual', 'Manual'), ('target', 'Target CPA')])
    target_cpa = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    max_bid = models.DecimalField(max_digits=10, decimal_places=2, default=0.50)
    
    # Scheduling
    start_date = models.DateTimeField(default=timezone.now)
    end_date = models.DateTimeField(null=True, blank=True)
    timezone = models.CharField(max_length=50, default='UTC')
    dayparting = models.JSONField(default=dict, blank=True,
        help_text="Schedule for specific hours/days")
    
    # Targeting
    TARGETING_CHOICES = [
        ('all', 'All Visitors'),
        ('logged_in', 'Logged In Users'),
        ('new', 'New Visitors'),
        ('returning', 'Returning Visitors'),
        ('high_value', 'High Value Customers'),
    ]
    targeting = models.CharField(max_length=20, choices=TARGETING_CHOICES, default='all')
    
    # Advanced Targeting
    geo_targeting = models.JSONField(default=list, blank=True)
    device_targeting = models.JSONField(default=list, blank=True)
    browser_targeting = models.JSONField(default=list, blank=True)
    os_targeting = models.JSONField(default=list, blank=True)
    interest_targeting = models.JSONField(default=list, blank=True)
    custom_segments = models.JSONField(default=list, blank=True)
    
    # Frequency Capping
    impressions_per_user = models.IntegerField(default=0, help_text="Max impressions per user")
    clicks_per_user = models.IntegerField(default=0, help_text="Max clicks per user")
    frequency_cap = models.IntegerField(default=0, help_text="Frequency cap per day")
    
    # Conversion Tracking
    conversion_value = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    conversion_rate = models.FloatField(default=0.0)
    roas = models.FloatField(default=0.0, help_text="Return on Ad Spend")
    
    # Performance Metrics
    impressions = models.IntegerField(default=0)
    clicks = models.IntegerField(default=0)
    ctr = models.FloatField(default=0.0)
    avg_position = models.FloatField(default=0.0)
    quality_score = models.IntegerField(default=0)
    
    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    approved = models.BooleanField(default=False)
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='approved_campaigns')
    approved_at = models.DateTimeField(null=True, blank=True)
    advertiser_identity = models.ForeignKey(
        'AdvertiserIdentity',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='campaigns',
        help_text="Optional V2 advertiser owner. Legacy campaigns may be blank.",
    )
    
    # Tracking
    utm_source = models.CharField(max_length=100, blank=True)
    utm_medium = models.CharField(max_length=100, blank=True)
    utm_campaign = models.CharField(max_length=100, blank=True)
    
    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} - {self.status}"

    def save(self, *args, **kwargs):
        if not self.campaign_id:
            self.campaign_id = f"AD-{uuid.uuid4().hex[:8].upper()}"
        super().save(*args, **kwargs)
    
    @property
    def remaining_budget(self):
        return self.total_budget - self.spent
    
    @property
    def budget_used_percentage(self):
        if self.total_budget > 0:
            return (self.spent / self.total_budget) * 100
        return 0


class AdCreative(BaseModel):
    """Rich ad creatives with multiple formats"""
    CREATIVE_TYPES = [
        ('image', 'Image'),
        ('video', 'Video'),
        ('html5', 'HTML5'),
        ('native', 'Native'),
        ('carousel', 'Carousel'),
        ('dynamic', 'Dynamic'),
    ]
    
    campaign = models.ForeignKey(AdCampaign, on_delete=models.CASCADE, related_name='creatives')
    name = models.CharField(max_length=200)
    creative_type = models.CharField(max_length=20, choices=CREATIVE_TYPES, default='image')
    
    # Content
    headline = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    cta_text = models.CharField(max_length=50, default='Learn More')
    cta_background_color = models.CharField(max_length=20, blank=True, default='', help_text="Optional CTA button background color.")
    cta_text_color = models.CharField(max_length=20, blank=True, default='', help_text="Optional CTA button text color.")
    
    # Media
    image = models.ImageField(upload_to='ads/creatives/', null=True, blank=True)
    image_mobile = models.ImageField(upload_to='ads/creatives/mobile/', null=True, blank=True)
    video_url = models.URLField(blank=True)
    html_content = models.TextField(blank=True, help_text="HTML5 creative content")
    
    # Carousel
    carousel_items = models.JSONField(default=list, blank=True)
    
    # Dynamic Content
    dynamic_fields = models.JSONField(default=dict, blank=True)
    
    # Tracking URLs
    clickthrough_url = models.URLField()
    tracking_url = models.URLField(blank=True)
    
    # A/B Testing
    ab_variant = models.CharField(max_length=20, blank=True)
    ab_weight = models.IntegerField(default=100)
    
    # Performance
    impressions = models.IntegerField(default=0)
    clicks = models.IntegerField(default=0)
    ctr = models.FloatField(default=0.0)
    
    is_active = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['-ab_weight', '-created_at']


class AdBanner(BaseModel):
    """Enhanced banner with advanced features"""
    IMAGE_FIT_CHOICES = [
        ('cover', 'Fill frame (crop if needed)'),
        ('contain', 'Fit whole image'),
        ('fill', 'Stretch to frame'),
        ('scale-down', 'Scale down only'),
    ]

    OPEN_BEHAVIOR_CHOICES = [
        ('same_page', 'Open in same page'),
        ('new_page', 'Open in new tab'),
        ('popup', 'Open in popup modal'),
    ]

    campaign = models.ForeignKey(AdCampaign, on_delete=models.CASCADE, related_name='banners')
    creative = models.ForeignKey(AdCreative, on_delete=models.SET_NULL, null=True, related_name='banners')
    placement = models.ForeignKey(AdPlacement, on_delete=models.SET_NULL, null=True, related_name='banners')
    
    # Content
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    
    # Media
    image = models.ImageField(upload_to='ads/banners/', null=True, blank=True)
    image_mobile = models.ImageField(upload_to='ads/banners/mobile/', null=True, blank=True)
    video_url = models.URLField(blank=True)
    width_override = models.PositiveIntegerField(null=True, blank=True, validators=[MinValueValidator(80), MaxValueValidator(3000)], help_text="Optional desktop width override in pixels. Falls back to placement width.")
    height_override = models.PositiveIntegerField(null=True, blank=True, validators=[MinValueValidator(40), MaxValueValidator(2000)], help_text="Optional desktop height override in pixels. Falls back to placement height.")
    mobile_width_override = models.PositiveIntegerField(null=True, blank=True, validators=[MinValueValidator(80), MaxValueValidator(1600)], help_text="Optional mobile width override in pixels.")
    mobile_height_override = models.PositiveIntegerField(null=True, blank=True, validators=[MinValueValidator(40), MaxValueValidator(1600)], help_text="Optional mobile height override in pixels.")
    image_fit = models.CharField(max_length=20, choices=IMAGE_FIT_CHOICES, default='cover')
    image_position = models.CharField(max_length=50, default='center center', help_text="CSS object-position for desktop/tablet.")
    mobile_image_fit = models.CharField(max_length=20, choices=IMAGE_FIT_CHOICES, default='cover')
    mobile_image_position = models.CharField(max_length=50, default='center center', help_text="CSS object-position for mobile.")
    
    # Interactive Elements
    cta_text = models.CharField(max_length=50, default='Learn More')
    cta_url = models.URLField(blank=True)
    cta_background_color = models.CharField(max_length=20, blank=True, default='', help_text="Optional CTA button background color.")
    cta_text_color = models.CharField(max_length=20, blank=True, default='', help_text="Optional CTA button text color.")
    alt_text = models.CharField(max_length=200, blank=True)
    linked_article = models.ForeignKey(
        'blog.BlogPost',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ad_banners',
        help_text="Optional article target. If set, it is used before the CTA URL."
    )
    article_open_behavior = models.CharField(max_length=20, choices=OPEN_BEHAVIOR_CHOICES, default='same_page')
    
    # Animation & Effects
    animation = models.CharField(max_length=50, blank=True,
        choices=[('fade', 'Fade'), ('slide', 'Slide'), ('zoom', 'Zoom'), ('none', 'None')])
    hover_effect = models.CharField(max_length=50, blank=True)
    
    # Priority & Scheduling
    priority = models.IntegerField(default=0)
    start_date = models.DateTimeField(default=timezone.now)
    end_date = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    
    # Performance
    impressions = models.IntegerField(default=0)
    clicks = models.IntegerField(default=0)
    ctr = models.FloatField(default=0.0)
    conversion_rate = models.FloatField(default=0.0)
    
    class Meta:
        ordering = ['-priority', '-created_at']

    @property
    def target_url(self):
        if self.linked_article:
            return self.linked_article.get_absolute_url()
        return self.cta_url

    @property
    def target_open_behavior(self):
        return self.article_open_behavior if self.linked_article else 'new_page'


class AdImpression(BaseModel):
    """Advanced impression tracking"""
    banner = models.ForeignKey(AdBanner, on_delete=models.CASCADE, related_name='impression_records')
    campaign = models.ForeignKey(AdCampaign, on_delete=models.CASCADE)
    adCreative = models.ForeignKey(AdCreative, on_delete=models.SET_NULL, null=True)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    
    # Session tracking
    session_id = models.CharField(max_length=200, blank=True)
    impression_id = models.UUIDField(default=uuid.uuid4, unique=True)
    
    # Technical data
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    referer = models.URLField(blank=True)
    
    # Device info
    device_type = models.CharField(max_length=20, blank=True)
    browser = models.CharField(max_length=50, blank=True)
    os = models.CharField(max_length=50, blank=True)
    screen_resolution = models.CharField(max_length=20, blank=True)
    
    # Location
    country = models.CharField(max_length=2, blank=True)
    city = models.CharField(max_length=100, blank=True)
    
    # Viewability
    view_duration = models.IntegerField(default=0, help_text="View duration in seconds")
    visible_percentage = models.IntegerField(default=0)
    was_visible = models.BooleanField(default=False)
    
    timestamp = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['session_id', 'timestamp']),
            models.Index(fields=['campaign', 'timestamp']),
        ]


class AdClick(BaseModel):
    """Enhanced click tracking with conversion data"""
    banner = models.ForeignKey(AdBanner, on_delete=models.CASCADE, related_name='click_records')
    campaign = models.ForeignKey(AdCampaign, on_delete=models.CASCADE)
    creative = models.ForeignKey(AdCreative, on_delete=models.SET_NULL, null=True)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    
    # Session tracking
    session_id = models.CharField(max_length=200, blank=True)
    click_id = models.UUIDField(default=uuid.uuid4, unique=True)
    
    # Technical data
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    referer = models.URLField(blank=True)
    
    # Device info
    device_type = models.CharField(max_length=20, blank=True)
    browser = models.CharField(max_length=50, blank=True)
    
    # Conversion tracking
    converted = models.BooleanField(default=False)
    conversion_value = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    conversion_time = models.DateTimeField(null=True, blank=True)
    
    # Quality
    is_bot = models.BooleanField(default=False)
    is_duplicate = models.BooleanField(default=False)
    
    timestamp = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-timestamp']


class AdConversion(BaseModel):
    """Conversion tracking for ROI analysis"""
    click = models.ForeignKey(AdClick, on_delete=models.CASCADE, related_name='conversions')
    campaign = models.ForeignKey(AdCampaign, on_delete=models.CASCADE)
    
    conversion_type = models.CharField(max_length=50,
        choices=[
            ('purchase', 'Purchase'),
            ('signup', 'Signup'),
            ('lead', 'Lead'),
            ('download', 'Download'),
            ('view', 'View'),
            ('custom', 'Custom'),
        ])
    
    value = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.IntegerField(default=1)
    
    order_id = models.CharField(max_length=100, blank=True)
    product_id = models.IntegerField(null=True, blank=True)
    
    timestamp = models.DateTimeField(auto_now_add=True)


class AdAnalytics(BaseModel):
    """Real-time analytics dashboard data"""
    campaign = models.ForeignKey(AdCampaign, on_delete=models.CASCADE, related_name='analytics')
    date = models.DateField()
    
    # Metrics
    impressions = models.IntegerField(default=0)
    unique_impressions = models.IntegerField(default=0)
    clicks = models.IntegerField(default=0)
    unique_clicks = models.IntegerField(default=0)
    conversions = models.IntegerField(default=0)
    
    # Value metrics
    revenue = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    # Calculated metrics
    ctr = models.FloatField(default=0.0)
    conversion_rate = models.FloatField(default=0.0)
    cpc = models.FloatField(default=0.0)
    cpm = models.FloatField(default=0.0)
    roas = models.FloatField(default=0.0)
    roi = models.FloatField(default=0.0)
    
    class Meta:
        unique_together = ['campaign', 'date']
        ordering = ['-date']


class Advertisement(BaseModel):
    """Simple ad model for quick placements"""
    PLACEMENT_CHOICES = [
        ('sidebar', 'Sidebar'),
        ('banner', 'Banner'),
        ('footer', 'Footer'),
        ('homepage', 'Homepage'),
        ('popup', 'Popup'),
    ]
    
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to='advertisements/', null=True, blank=True)
    url = models.URLField(blank=True)
    button_text = models.CharField(max_length=100, default='Learn More')
    button_background_color = models.CharField(max_length=20, blank=True, default='', help_text="Optional button background color.")
    button_text_color = models.CharField(max_length=20, blank=True, default='', help_text="Optional button text color.")
    linked_article = models.ForeignKey(
        'blog.BlogPost',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='simple_ads',
        help_text="Optional article target. If set, it is used before the URL."
    )
    article_open_behavior = models.CharField(max_length=20, choices=AdBanner.OPEN_BEHAVIOR_CHOICES, default='same_page')
    placement = models.CharField(max_length=20, choices=PLACEMENT_CHOICES, default='sidebar')
    is_featured = models.BooleanField(default=False)
    
    # Enhanced metrics
    views = models.IntegerField(default=0)
    clicks = models.IntegerField(default=0)
    ctr = models.FloatField(default=0.0)
    
    # Scheduling
    start_date = models.DateTimeField(default=timezone.now)
    end_date = models.DateTimeField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    
    # Targeting
    target_audience = models.CharField(max_length=100, blank=True)
    show_to_logged_in = models.BooleanField(default=True)
    show_to_guests = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['-is_featured', '-created_at']
        verbose_name = 'Advertisement'
        verbose_name_plural = 'Advertisements'

    def __str__(self):
        return self.title

    @property
    def target_url(self):
        if self.linked_article:
            return self.linked_article.get_absolute_url()
        return self.url

    @property
    def target_open_behavior(self):
        return self.article_open_behavior if self.linked_article else 'new_page'


class AdvertiserIdentity(BaseModel):
    """Stable Ads-side owner identity for vendor, provider, or platform advertisers."""

    OWNER_VENDOR = 'vendor'
    OWNER_PROVIDER = 'provider'
    OWNER_PLATFORM = 'platform'

    OWNER_TYPE_CHOICES = [
        (OWNER_VENDOR, 'Vendor'),
        (OWNER_PROVIDER, 'Service Provider'),
        (OWNER_PLATFORM, 'Platform'),
    ]

    owner_type = models.CharField(max_length=20, choices=OWNER_TYPE_CHOICES, db_index=True)
    vendor = models.ForeignKey(
        'vendors.VendorProfile',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='advertiser_identities',
    )
    provider = models.ForeignKey(
        'installers.ServiceProviderProfile',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='advertiser_identities',
    )
    user = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='advertiser_identities',
    )
    display_name = models.CharField(max_length=200, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['owner_type', 'is_active']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['owner_type', 'vendor'],
                condition=models.Q(vendor__isnull=False),
                name='unique_ads_vendor_advertiser_identity',
            ),
            models.UniqueConstraint(
                fields=['owner_type', 'provider'],
                condition=models.Q(provider__isnull=False),
                name='unique_ads_provider_advertiser_identity',
            ),
        ]

    def __str__(self):
        return self.display_name or f"{self.owner_type} advertiser #{self.pk}"

    def clean(self):
        super().clean()
        owner_fields = [bool(self.vendor_id), bool(self.provider_id), bool(self.user_id)]
        if self.owner_type == self.OWNER_VENDOR and not self.vendor_id:
            raise ValidationError("Vendor advertiser identities require a vendor.")
        if self.owner_type == self.OWNER_PROVIDER and not self.provider_id:
            raise ValidationError("Provider advertiser identities require a provider.")
        if self.owner_type == self.OWNER_PLATFORM and not self.user_id:
            raise ValidationError("Platform advertiser identities require a user.")
        if self.owner_type in {self.OWNER_VENDOR, self.OWNER_PROVIDER} and sum(owner_fields) != 2:
            raise ValidationError("Vendor/provider advertiser identities must include exactly one owner and its user.")
        if self.owner_type == self.OWNER_VENDOR and self.vendor_id and self.user_id != self.vendor.user_id:
            raise ValidationError("Vendor advertiser identity user must match the vendor owner.")
        if self.owner_type == self.OWNER_PROVIDER and self.provider_id and self.user_id != self.provider.user_id:
            raise ValidationError("Provider advertiser identity user must match the provider owner.")
        if self.owner_type == self.OWNER_PLATFORM and (self.vendor_id or self.provider_id):
            raise ValidationError("Platform advertiser identities cannot reference vendor or provider owners.")


class CampaignAsset(BaseModel):
    """Additive asset registry for sponsored products, videos, stores, and services."""

    ASSET_PRODUCT = 'product'
    ASSET_PRODUCT_VIDEO = 'product_video'
    ASSET_VENDOR_STORE = 'vendor_store'
    ASSET_PROVIDER_PROFILE = 'provider_profile'
    ASSET_PROVIDER_SERVICE = 'provider_service'
    ASSET_EXTERNAL_URL = 'external_url'

    ASSET_TYPE_CHOICES = [
        (ASSET_PRODUCT, 'Product'),
        (ASSET_PRODUCT_VIDEO, 'Product Video'),
        (ASSET_VENDOR_STORE, 'Vendor Store'),
        (ASSET_PROVIDER_PROFILE, 'Provider Profile'),
        (ASSET_PROVIDER_SERVICE, 'Provider Service'),
        (ASSET_EXTERNAL_URL, 'External URL'),
    ]

    campaign = models.ForeignKey(AdCampaign, on_delete=models.CASCADE, related_name='assets')
    advertiser_identity = models.ForeignKey(
        AdvertiserIdentity,
        on_delete=models.PROTECT,
        related_name='campaign_assets',
    )
    asset_type = models.CharField(max_length=30, choices=ASSET_TYPE_CHOICES, db_index=True)
    content_type = models.ForeignKey(ContentType, on_delete=models.PROTECT, null=True, blank=True)
    object_id = models.PositiveBigIntegerField(null=True, blank=True, db_index=True)
    content_object = GenericForeignKey('content_type', 'object_id')
    product_video = models.ForeignKey(
        'products.ProductVideo',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='ad_campaign_assets',
        help_text="Canonical ProductVideo reference for video commerce ads.",
    )
    destination_url = models.URLField(blank=True)
    title = models.CharField(max_length=200, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['asset_type', 'is_active']),
            models.Index(fields=['content_type', 'object_id']),
        ]

    def __str__(self):
        return self.title or f"{self.asset_type} asset for {self.campaign_id}"

    def clean(self):
        super().clean()
        if self.campaign_id and self.advertiser_identity_id:
            campaign_identity_id = getattr(self.campaign, "advertiser_identity_id", None)
            if campaign_identity_id and campaign_identity_id != self.advertiser_identity_id:
                raise ValidationError("Campaign asset advertiser must match campaign advertiser.")

        if self.asset_type != self.ASSET_EXTERNAL_URL and not (self.content_type_id and self.object_id):
            raise ValidationError("Campaign assets require an object reference unless they are external URLs.")

        if self.asset_type == self.ASSET_PRODUCT_VIDEO and not (self.product_video_id or self.content_object):
            raise ValidationError("Product video campaign assets require a ProductVideo reference.")

        from .ownership import ownership_resolver

        resolution = ownership_resolver.resolve_asset_owner(self)
        if self.asset_type != self.ASSET_EXTERNAL_URL:
            if not resolution.is_resolved:
                raise ValidationError(f"Asset ownership could not be resolved: {resolution.reason}.")
            if resolution.owner_type != self.advertiser_identity.owner_type:
                raise ValidationError("Asset owner type does not match advertiser identity.")
            if resolution.vendor and resolution.vendor.pk != self.advertiser_identity.vendor_id:
                raise ValidationError("Asset vendor does not match advertiser identity.")
            if resolution.provider and resolution.provider.pk != self.advertiser_identity.provider_id:
                raise ValidationError("Asset provider does not match advertiser identity.")


class ExternalAdvertisingAccount(BaseModel):
    """Encrypted-ready account shell for external ad channels; no credentials in V1."""

    CHANNEL_META = 'meta'
    CHANNEL_GOOGLE = 'google'
    CHANNEL_TIKTOK = 'tiktok'
    CHANNEL_LINKEDIN = 'linkedin'
    CHANNEL_OTHER = 'other'

    CHANNEL_CHOICES = [
        (CHANNEL_META, 'Meta'),
        (CHANNEL_GOOGLE, 'Google'),
        (CHANNEL_TIKTOK, 'TikTok'),
        (CHANNEL_LINKEDIN, 'LinkedIn'),
        (CHANNEL_OTHER, 'Other'),
    ]

    STATUS_NOT_CONNECTED = 'not_connected'
    STATUS_PENDING = 'pending'
    STATUS_DISCONNECTED = 'disconnected'
    STATUS_CONNECTED = 'connected'
    STATUS_EXPIRED = 'expired'
    STATUS_REVOKED = 'revoked'
    STATUS_REAUTHORIZATION_REQUIRED = 'reauthorization_required'
    STATUS_ERROR = 'error'

    STATUS_CHOICES = [
        (STATUS_NOT_CONNECTED, 'Not connected'),
        (STATUS_PENDING, 'Pending'),
        (STATUS_DISCONNECTED, 'Disconnected'),
        (STATUS_CONNECTED, 'Connected'),
        (STATUS_EXPIRED, 'Expired'),
        (STATUS_REVOKED, 'Revoked'),
        (STATUS_REAUTHORIZATION_REQUIRED, 'Reauthorization required'),
        (STATUS_ERROR, 'Error'),
    ]

    advertiser_identity = models.ForeignKey(
        AdvertiserIdentity,
        on_delete=models.CASCADE,
        related_name='external_accounts',
    )
    channel = models.CharField(max_length=30, choices=CHANNEL_CHOICES, db_index=True)
    external_account_id = models.CharField(max_length=200, blank=True)
    display_name = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_DISCONNECTED)
    connected_at = models.DateTimeField(null=True, blank=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        unique_together = ['advertiser_identity', 'channel', 'external_account_id']
        constraints = [
            models.UniqueConstraint(
                fields=['channel', 'external_account_id'],
                condition=(
                    ~models.Q(external_account_id='')
                    & ~models.Q(status__in=['disconnected', 'revoked'])
                ),
                name='uniq_active_external_ad_account',
            ),
        ]
        indexes = [
            models.Index(fields=['channel', 'status']),
        ]

    def __str__(self):
        return self.display_name or f"{self.channel} account"

    def clean(self):
        super().clean()
        if self.external_account_id:
            lowered = self.external_account_id.lower()
            if "token" in lowered or "secret" in lowered or "bearer " in lowered:
                raise ValidationError("Do not store credentials in external_account_id.")


class AdvertisingCredential(BaseModel):
    """Encrypted OAuth credential material for external advertising accounts."""

    external_account = models.OneToOneField(
        ExternalAdvertisingAccount,
        on_delete=models.CASCADE,
        related_name='credential',
    )
    provider = models.CharField(max_length=30, db_index=True)
    encrypted_access_token = models.BinaryField(null=True, blank=True, editable=False)
    encrypted_refresh_token = models.BinaryField(null=True, blank=True, editable=False)
    access_token_expires_at = models.DateTimeField(null=True, blank=True)
    refresh_token_expires_at = models.DateTimeField(null=True, blank=True)
    credential_version = models.PositiveIntegerField(default=1)
    scopes = models.JSONField(default=list, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['provider', 'revoked_at']),
        ]

    def __str__(self):
        return f"{self.provider} credential for account #{self.external_account.external_account_id}"


class AdvertisingOAuthState(BaseModel):
    """Single-use OAuth CSRF state bound to user, advertiser, provider, and session."""

    provider = models.CharField(max_length=30, db_index=True)
    state = models.CharField(max_length=128, unique=True, db_index=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='advertising_oauth_states')
    advertiser_identity = models.ForeignKey(
        AdvertiserIdentity,
        on_delete=models.CASCADE,
        related_name='oauth_states',
    )
    session_key = models.CharField(max_length=160, blank=True, db_index=True)
    expires_at = models.DateTimeField(db_index=True)
    used_at = models.DateTimeField(null=True, blank=True)
    redirect_uri = models.URLField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['provider', 'expires_at']),
            models.Index(fields=['advertiser_identity', 'provider', 'used_at']),
        ]

    def __str__(self):
        return f"{self.provider} OAuth state for {self.advertiser_identity_id}"


class AdvertisingConnectionAuditLog(BaseModel):
    """Non-sensitive audit trail for connected advertising account lifecycle."""

    EVENT_CONNECTION_INITIATED = 'connection_initiated'
    EVENT_CALLBACK_ACCEPTED = 'oauth_callback_accepted'
    EVENT_CONNECTION_COMPLETED = 'connection_completed'
    EVENT_ACCOUNT_SELECTED = 'account_selected'
    EVENT_TOKEN_REFRESHED = 'token_refreshed'
    EVENT_CONNECTION_REVOKED = 'connection_revoked'
    EVENT_REFRESH_FAILED = 'refresh_failed'
    EVENT_AUTHORIZATION_FAILED = 'authorization_failed'
    EVENT_ACCOUNT_ACCESS_LOST = 'account_access_lost'
    EVENT_TEST_PUBLICATION_REQUESTED = 'test_publication_requested'
    EVENT_TEST_PUBLICATION_APPROVED = 'test_publication_approved'
    EVENT_EXTERNAL_CREATE_ATTEMPTED = 'external_create_attempted'
    EVENT_EXTERNAL_CREATE_SUCCEEDED = 'external_create_succeeded'
    EVENT_EXTERNAL_CREATE_FAILED = 'external_create_failed'
    EVENT_EXTERNAL_CAMPAIGN_PAUSED = 'external_campaign_paused'
    EVENT_EXTERNAL_CAMPAIGN_RESUMED = 'external_campaign_resumed'
    EVENT_REPORT_PULLED = 'report_pulled'
    EVENT_READBACK_MISMATCH = 'readback_mismatch'

    advertiser_identity = models.ForeignKey(
        AdvertiserIdentity,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='connection_audit_logs',
    )
    external_account = models.ForeignKey(
        ExternalAdvertisingAccount,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs',
    )
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    provider = models.CharField(max_length=30, db_index=True)
    event_type = models.CharField(max_length=50, db_index=True)
    status = models.CharField(max_length=30, blank=True)
    message = models.CharField(max_length=240, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['provider', 'event_type', 'created_at']),
            models.Index(fields=['advertiser_identity', 'provider', 'created_at']),
        ]

    def __str__(self):
        return f"{self.provider} {self.event_type}"


class AdChannelExecution(BaseModel):
    """Execution record for serving or syncing a campaign on a channel."""

    CHANNEL_INTERNAL = 'internal'
    CHANNEL_META = ExternalAdvertisingAccount.CHANNEL_META
    CHANNEL_GOOGLE = ExternalAdvertisingAccount.CHANNEL_GOOGLE
    CHANNEL_TIKTOK = ExternalAdvertisingAccount.CHANNEL_TIKTOK
    CHANNEL_LINKEDIN = ExternalAdvertisingAccount.CHANNEL_LINKEDIN

    STATUS_DRAFT = 'draft'
    STATUS_PENDING = 'pending'
    STATUS_SYNCING = 'syncing'
    STATUS_READY = 'ready'
    STATUS_ACTIVE = 'active'
    STATUS_PAUSED = 'paused'
    STATUS_COMPLETED = 'completed'
    STATUS_FAILED = 'failed'
    STATUS_REJECTED = 'rejected'
    STATUS_REAUTHORIZATION_REQUIRED = 'reauthorization_required'
    STATUS_DISCONNECTED = 'disconnected'
    STATUS_ERROR = 'error'

    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'),
        (STATUS_PENDING, 'Pending'),
        (STATUS_SYNCING, 'Syncing'),
        (STATUS_READY, 'Ready'),
        (STATUS_ACTIVE, 'Active'),
        (STATUS_PAUSED, 'Paused'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_FAILED, 'Failed'),
        (STATUS_REJECTED, 'Rejected'),
        (STATUS_REAUTHORIZATION_REQUIRED, 'Reauthorization required'),
        (STATUS_DISCONNECTED, 'Disconnected'),
        (STATUS_ERROR, 'Error'),
    ]

    campaign = models.ForeignKey(AdCampaign, on_delete=models.CASCADE, related_name='channel_executions')
    advertiser_identity = models.ForeignKey(
        AdvertiserIdentity,
        on_delete=models.PROTECT,
        related_name='channel_executions',
    )
    channel = models.CharField(max_length=30, db_index=True)
    external_account = models.ForeignKey(
        ExternalAdvertisingAccount,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='channel_executions',
    )
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_DRAFT, db_index=True)
    external_status = models.CharField(max_length=80, blank=True)
    external_campaign_id = models.CharField(max_length=200, blank=True)
    external_ad_group_id = models.CharField(max_length=200, blank=True)
    external_creative_id = models.CharField(max_length=200, blank=True)
    idempotency_key = models.CharField(max_length=160, blank=True, db_index=True)
    budget_allocation = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=10, blank=True)
    last_error = models.TextField(blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['campaign', 'channel', 'status']),
            models.Index(fields=['advertiser_identity', 'channel']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['campaign', 'channel'],
                condition=models.Q(is_active=True),
                name='unique_active_ads_channel_execution',
            ),
            models.UniqueConstraint(
                fields=['idempotency_key'],
                condition=~models.Q(idempotency_key=''),
                name='unique_ads_channel_execution_idempotency',
            ),
        ]

    def clean(self):
        super().clean()
        if self.campaign_id and self.advertiser_identity_id:
            campaign_identity_id = getattr(self.campaign, "advertiser_identity_id", None)
            if campaign_identity_id and campaign_identity_id != self.advertiser_identity_id:
                raise ValidationError("Channel execution advertiser must match campaign advertiser.")
        if self.external_account_id and self.external_account.advertiser_identity_id != self.advertiser_identity_id:
            raise ValidationError("External account advertiser must match channel execution advertiser.")


class AdChannelReportingSnapshot(BaseModel):
    """Normalized external-provider reporting snapshot for a channel execution."""

    execution = models.ForeignKey(
        AdChannelExecution,
        on_delete=models.CASCADE,
        related_name='reporting_snapshots',
    )
    provider = models.CharField(max_length=30, db_index=True)
    reporting_start = models.DateField()
    reporting_end = models.DateField()
    impressions = models.PositiveIntegerField(default=0)
    clicks = models.PositiveIntegerField(default=0)
    spend = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    video_views = models.PositiveIntegerField(default=0)
    provider_conversions = models.PositiveIntegerField(default=0)
    currency = models.CharField(max_length=10, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['provider', 'reporting_start', 'reporting_end']),
            models.Index(fields=['execution', 'reporting_start']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['execution', 'reporting_start', 'reporting_end'],
                name='unique_ads_channel_reporting_window',
            ),
        ]


class AdEvent(BaseModel):
    """Canonical idempotent ad/recommendation event foundation."""

    EVENT_IMPRESSION = 'impression'
    EVENT_CLICK = 'click'
    EVENT_VIEW = 'view'
    EVENT_CONVERSION = 'conversion'

    EVENT_TYPE_CHOICES = [
        (EVENT_IMPRESSION, 'Impression'),
        (EVENT_CLICK, 'Click'),
        (EVENT_VIEW, 'View'),
        (EVENT_CONVERSION, 'Conversion'),
    ]

    event_uuid = models.UUIDField(default=uuid.uuid4, unique=True)
    delivery_id = models.UUIDField(null=True, blank=True, db_index=True)
    event_type = models.CharField(max_length=30, choices=EVENT_TYPE_CHOICES, db_index=True)
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)
    advertiser_identity = models.ForeignKey(
        AdvertiserIdentity,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ad_events',
    )
    campaign = models.ForeignKey(AdCampaign, on_delete=models.SET_NULL, null=True, blank=True, related_name='v2_events')
    asset = models.ForeignKey(CampaignAsset, on_delete=models.SET_NULL, null=True, blank=True, related_name='events')
    channel_execution = models.ForeignKey(
        AdChannelExecution,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='events',
    )
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='ad_events')
    session_id = models.CharField(max_length=200, blank=True, db_index=True)
    request_id = models.CharField(max_length=100, blank=True, db_index=True)
    event_source = models.CharField(max_length=50, default='internal', db_index=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['event_type', 'occurred_at']),
            models.Index(fields=['campaign', 'event_type']),
            models.Index(fields=['asset', 'event_type']),
        ]


class AdAttribution(BaseModel):
    """Attribution link between canonical ad events and downstream objects."""

    ATTR_VIEW_THROUGH = 'view_through'
    ATTR_CLICK_THROUGH = 'click_through'
    ATTR_DIRECT = 'direct'

    LIFECYCLE_ACTIVE = 'active'
    LIFECYCLE_REVERSED = 'reversed'
    LIFECYCLE_ADJUSTED = 'adjusted'

    ATTRIBUTION_TYPE_CHOICES = [
        (ATTR_VIEW_THROUGH, 'View-through'),
        (ATTR_CLICK_THROUGH, 'Click-through'),
        (ATTR_DIRECT, 'Direct'),
    ]

    MODEL_LAST_TOUCH = 'last_touch'
    MODEL_FIRST_TOUCH = 'first_touch'
    MODEL_LINEAR = 'linear'
    MODEL_POSITION_BASED = 'position_based'
    MODEL_DATA_DRIVEN = 'data_driven'

    ATTRIBUTION_MODEL_CHOICES = [
        (MODEL_LAST_TOUCH, 'Last touch'),
        (MODEL_FIRST_TOUCH, 'First touch'),
        (MODEL_LINEAR, 'Linear'),
        (MODEL_POSITION_BASED, 'Position based'),
        (MODEL_DATA_DRIVEN, 'Data driven'),
    ]

    LIFECYCLE_STATUS_CHOICES = [
        (LIFECYCLE_ACTIVE, 'Active'),
        (LIFECYCLE_REVERSED, 'Reversed'),
        (LIFECYCLE_ADJUSTED, 'Adjusted'),
    ]

    source_event = models.ForeignKey(AdEvent, on_delete=models.CASCADE, related_name='attributions')
    source_click_event = models.ForeignKey(
        AdEvent,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='click_attributions',
    )
    delivery_id = models.UUIDField(null=True, blank=True, db_index=True)
    campaign = models.ForeignKey(
        AdCampaign,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='v2_attributions',
    )
    advertiser_identity = models.ForeignKey(
        AdvertiserIdentity,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='attributions',
    )
    asset = models.ForeignKey(
        CampaignAsset,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='attributions',
    )
    product = models.ForeignKey(
        'products.Product',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ad_attributions',
    )
    vendor = models.ForeignKey(
        'vendors.VendorProfile',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ad_attributions',
    )
    order = models.ForeignKey(
        'orders.Order',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ad_attributions',
    )
    order_item = models.ForeignKey(
        'orders.OrderItem',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ad_attributions',
    )
    attribution_type = models.CharField(max_length=30, choices=ATTRIBUTION_TYPE_CHOICES, db_index=True)
    attribution_model = models.CharField(
        max_length=30,
        choices=ATTRIBUTION_MODEL_CHOICES,
        default=MODEL_LAST_TOUCH,
        db_index=True,
    )
    target_content_type = models.ForeignKey(ContentType, on_delete=models.PROTECT, null=True, blank=True)
    target_object_id = models.PositiveBigIntegerField(null=True, blank=True, db_index=True)
    target_object = GenericForeignKey('target_content_type', 'target_object_id')
    revenue_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    gross_revenue_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    net_revenue_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=10, default='NGN')
    lifecycle_status = models.CharField(
        max_length=20,
        choices=LIFECYCLE_STATUS_CHOICES,
        null=True,
        blank=True,
        db_index=True,
    )
    reversed_at = models.DateTimeField(null=True, blank=True)
    reversal_reason = models.CharField(max_length=80, null=True, blank=True)
    reversal_reference = models.CharField(max_length=160, null=True, blank=True, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['attribution_type', 'created_at']),
            models.Index(fields=['campaign', 'attribution_model']),
            models.Index(fields=['asset', 'delivery_id']),
            models.Index(fields=['order', 'order_item']),
            models.Index(fields=['target_content_type', 'target_object_id']),
            models.Index(fields=['advertiser_identity', 'lifecycle_status']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['source_event', 'order_item', 'attribution_type', 'attribution_model'],
                condition=models.Q(order_item__isnull=False),
                name='unique_ads_order_item_attribution',
            ),
        ]
