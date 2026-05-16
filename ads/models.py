from django.db import models
from django.core.validators import MaxValueValidator, MinValueValidator
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
        ('active', 'Active'),
        ('paused', 'Paused'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]
    
    BUDGET_TYPE = [
        ('daily', 'Daily Budget'),
        ('total', 'Total Budget'),
        ('lifetime', 'Lifetime Budget'),
    ]
    
    name = models.CharField(max_length=200)
    campaign_id = models.CharField(max_length=50, unique=True, blank=True)
    campaign_type = models.CharField(max_length=20, choices=CAMPAIGN_TYPES, default='display')
    
    # Budget & Billing
    budget_type = models.CharField(max_length=10, choices=BUDGET_TYPE, default='total')
    daily_budget = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    total_budget = models.DecimalField(max_digits=10, decimal_places=2, default=100.00)
    spent = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
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
    alt_text = models.CharField(max_length=200, blank=True)
    
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
