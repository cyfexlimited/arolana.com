from django.db import models
from django.core.validators import MaxValueValidator, MinValueValidator
from core.models import BaseModel
from core.local_cache import local_delete, local_delete_prefix
from products.models import Brand, Category, Product
from vendors.models import VendorProfile
import re

class HomepageCategory(BaseModel):
    """Manageable category section on homepage"""
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='homepage_categories', null=True, blank=True)
    icon = models.CharField(max_length=50, default='fas fa-folder-open', help_text="FontAwesome icon class")
    display_order = models.IntegerField(default=0, help_text="Order in which categories appear")
    is_active = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['display_order']
        verbose_name = "Homepage Category"
        verbose_name_plural = "Homepage Categories"
    
    def __str__(self):
        return f"{self.category.name if self.category else 'No Category'} (Order: {self.display_order})"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        local_delete("homepage:categories")

    def delete(self, *args, **kwargs):
        result = super().delete(*args, **kwargs)
        local_delete("homepage:categories")
        return result

class HomepageBanner(BaseModel):
    """Manageable promo banner on homepage"""

    TARGET_AUDIENCE_CHOICES = [
        ('all', 'Everyone'),
        ('guests', 'Guests only'),
        ('authenticated', 'Signed-in users'),
        ('customers', 'Customers'),
        ('vendors', 'Vendors'),
        ('manufacturers', 'Manufacturers'),
        ('staff', 'Staff/Admin'),
    ]

    IMAGE_FIT_CHOICES = [
        ('cover', 'Fill frame (crop if needed)'),
        ('contain', 'Fit whole image'),
        ('fill', 'Stretch to frame'),
        ('scale-down', 'Scale down only'),
    ]

    CONTENT_LAYOUT_CHOICES = [
        ('designed', 'Designed banner with text/images'),
        ('image_only', 'Image only'),
    ]

    CONTENT_ALIGNMENT_CHOICES = [
        ('left', 'Left'),
        ('center', 'Center'),
        ('right', 'Right'),
    ]

    PLACEMENT_CHOICES = [
        ('top', 'Top of homepage'),
        ('after_categories', 'After categories'),
        ('after_products', 'After product sections'),
        ('after_manufacturers', 'After manufacturers'),
        ('after_vendors', 'After vendor sections'),
        ('before_newsletter', 'Before newsletter'),
        ('custom', 'Custom/manual placement'),
    ]

    BANNER_STYLE_CHOICES = [
        ('hero_slider', 'Hero slider'),
        ('wide_strip', 'Wide strip banner'),
        ('two_column', 'Two-column promo'),
        ('image_only', 'Image-only banner'),
        ('card_grid', 'Promo card/grid style'),
    ]

    title = models.CharField(max_length=200, default="Summer Mega Sale!")
    subtitle = models.CharField(
        max_length=500,
        blank=True,
        default="Get up to 50% off on selected items + Free Shipping"
    )
    button_text = models.CharField(max_length=50, default="Shop Now")
    button_url = models.CharField(max_length=500, default="/products/?deals=true")

    target_audience = models.CharField(
        max_length=20,
        choices=TARGET_AUDIENCE_CHOICES,
        default='all',
        help_text="Choose who should see this banner.",
    )

    placement = models.CharField(
        max_length=40,
        choices=PLACEMENT_CHOICES,
        default="top",
        db_index=True,
        help_text="Choose where this banner should appear on the homepage.",
    )

    banner_style = models.CharField(
        max_length=30,
        choices=BANNER_STYLE_CHOICES,
        default="hero_slider",
        help_text="Choose the visual structure for this banner.",
    )

    show_on_homepage = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Turn off if you want to keep this banner saved but hide it from the homepage.",
    )

    full_width = models.BooleanField(
        default=False,
        help_text="Allow banner to stretch wider than the normal homepage container.",
    )

    background_color_start = models.CharField(
        max_length=20,
        default="#3B82F6",
        help_text="Gradient start color"
    )
    background_color_end = models.CharField(
        max_length=20,
        default="#8B5CF6",
        help_text="Gradient end color"
    )

    desktop_height = models.PositiveIntegerField(
        default=320,
        validators=[MinValueValidator(120), MaxValueValidator(900)],
        help_text="Homepage banner height on desktop in pixels."
    )
    tablet_height = models.PositiveIntegerField(
        default=300,
        validators=[MinValueValidator(120), MaxValueValidator(800)],
        help_text="Homepage banner height on tablet in pixels."
    )
    mobile_height = models.PositiveIntegerField(
        default=260,
        validators=[MinValueValidator(120), MaxValueValidator(700)],
        help_text="Homepage banner height on mobile in pixels."
    )

    content_layout = models.CharField(
        max_length=20,
        choices=CONTENT_LAYOUT_CHOICES,
        default='designed',
        help_text="Choose image-only when the uploaded background already includes all text/buttons."
    )
    content_alignment = models.CharField(
        max_length=20,
        choices=CONTENT_ALIGNMENT_CHOICES,
        default='center'
    )

    background_fit = models.CharField(
        max_length=20,
        choices=IMAGE_FIT_CHOICES,
        default='cover'
    )
    background_position = models.CharField(
        max_length=50,
        default='center center',
        help_text="CSS object-position. Examples: center center, left center, 50% 35%."
    )
    background_opacity = models.FloatField(
        default=0.35,
        validators=[MinValueValidator(0), MaxValueValidator(1)],
        help_text="0 is hidden, 1 is full strength. Image-only banners display at full strength."
    )

    # Floating image URLs
    left_image = models.URLField(blank=True, help_text="URL for left floating image")
    right_image = models.URLField(blank=True, help_text="URL for right floating image")
    center_image = models.URLField(blank=True, help_text="URL for center floating image")

    # Animations
    left_animation = models.CharField(max_length=50, default="animate-bounce")
    right_animation = models.CharField(max_length=50, default="animate-pulse")
    center_animation = models.CharField(max_length=50, default="animate-spin-slow")

    display_order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['placement', 'display_order', 'id']
        verbose_name = "Homepage Banner"
        verbose_name_plural = "Homepage Banners"

    def __str__(self):
        return self.title

    @property
    def show_button(self):
        return bool(self.button_text and self.button_url and self.button_url != '#')

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        local_delete_prefix("homepage:banners:v4")

    def delete(self, *args, **kwargs):
        result = super().delete(*args, **kwargs)
        local_delete_prefix("homepage:banners:v4")
        return result

class HomepageSection(BaseModel):
    """Admin-managed product section and presentation settings."""

    SECTION_TYPES = [
        ('featured', 'Featured Products'),
        ('new', 'New Arrivals'),
        ('bestsellers', 'Best Sellers'),
        ('trending', 'Trending Deals'),
        ('custom', 'Custom Section'),
    ]
    LAYOUT_CHOICES = [
        ('editorial', 'Editorial image slider'),
        ('compact', 'Compact two-row deals'),
        ('market_grid', 'Marketplace grid'),
        ('carousel', 'Product card carousel'),
    ]
    SORT_CHOICES = [
        ('automatic', 'Automatic for section type'),
        ('newest', 'Newest first'),
        ('best_selling', 'Best selling first'),
        ('trending', 'Most viewed and selling'),
        ('top_rated', 'Top rated first'),
        ('featured', 'Featured first'),
        ('price_low', 'Price: low to high'),
        ('price_high', 'Price: high to low'),
    ]
    VENDOR_TYPE_CHOICES = [
        ('', 'All vendor types'),
        ('manufacturer', 'Manufacturers'),
        ('distributor', 'Distributors'),
        ('wholesaler', 'Wholesalers'),
        ('retailer', 'Retailers'),
        ('service_provider', 'Service providers'),
    ]

    title = models.CharField(max_length=200)
    section_type = models.CharField(max_length=20, choices=SECTION_TYPES, default='featured')
    subtitle = models.CharField(max_length=500, blank=True)
    layout_style = models.CharField(
        max_length=30,
        choices=LAYOUT_CHOICES,
        default='carousel',
        help_text="Controls the visual structure independently from the product source.",
    )
    sort_mode = models.CharField(
        max_length=30,
        choices=SORT_CHOICES,
        default='automatic',
        help_text="Choose how automatically selected products are ordered.",
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='homepage_product_sections',
        help_text="Optional: limit this section to one category.",
    )
    brand = models.ForeignKey(
        Brand,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='homepage_product_sections',
        help_text="Optional: limit this section to one brand.",
    )
    vendor_type = models.CharField(
        max_length=30,
        choices=VENDOR_TYPE_CHOICES,
        blank=True,
        default='',
    )
    verified_vendors_only = models.BooleanField(default=False)
    use_subscription_priority = models.BooleanField(
        default=True,
        help_text="Give active higher-tier vendors stronger placement after curated products.",
    )
    fill_automatically = models.BooleanField(
        default=True,
        help_text="Fill remaining slots automatically after curated products.",
    )
    display_order = models.IntegerField(default=0)
    products_limit = models.PositiveIntegerField(default=8, help_text="Number of products to show")
    view_all_url = models.CharField(max_length=500, blank=True, default="/products/")
    view_all_text = models.CharField(max_length=50, default="View All", blank=True)
    show_view_all = models.BooleanField(default=True)
    empty_state_text = models.CharField(
        max_length=255,
        default="No products available in this section yet.",
        blank=True,
    )
    accent_color = models.CharField(max_length=20, default="#0F2D6B")
    background_color = models.CharField(max_length=20, default="transparent")
    show_vendor = models.BooleanField(default=True)
    show_subscription_badge = models.BooleanField(default=True)
    show_rating = models.BooleanField(default=True)
    show_price = models.BooleanField(default=True)
    show_add_to_cart = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['display_order']
        verbose_name = "Homepage Section"
        verbose_name_plural = "Homepage Sections"

    def __str__(self):
        return f"{self.title} ({self.get_section_type_display()})"

    def get_products(self):
        """Return curated products first, then filtered automatic products."""
        from products.ranking import order_products_for_visibility

        queryset = Product.objects.filter(
            is_active=True,
            approval_status='approved',
        ).select_related(
            'category',
            'brand',
            'vendor',
            'vendor__vendor_profile',
        )

        if self.category_id:
            queryset = queryset.filter(category=self.category)
        if self.brand_id:
            queryset = queryset.filter(brand=self.brand)
        if self.vendor_type:
            queryset = queryset.filter(vendor__vendor_profile__vendor_type=self.vendor_type)
        if self.verified_vendors_only:
            queryset = queryset.filter(vendor__vendor_profile__is_verified=True)

        curated = list(
            queryset.filter(
                homepage_section_links__section=self,
                homepage_section_links__is_active=True,
            ).order_by(
                'homepage_section_links__display_order',
                'homepage_section_links__id',
            )[:self.products_limit]
        )
        remaining = max(self.products_limit - len(curated), 0)
        if not self.fill_automatically or not remaining:
            return curated

        if curated:
            queryset = queryset.exclude(pk__in=[product.pk for product in curated])

        if self.section_type == 'featured':
            queryset = queryset.filter(is_featured=True)
        elif self.section_type == 'new':
            queryset = queryset.filter(is_new=True)
        elif self.section_type == 'bestsellers':
            queryset = queryset.filter(is_bestseller=True)

        queryset = order_products_for_visibility(
            queryset,
            sort_mode=self.sort_mode,
            section_type=self.section_type,
            use_subscription_priority=self.use_subscription_priority,
            homepage=True,
        )
        return curated + list(queryset[:remaining])

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        local_delete("homepage:sections")

    def delete(self, *args, **kwargs):
        result = super().delete(*args, **kwargs)
        local_delete("homepage:sections")
        return result


class HomepageSectionProduct(BaseModel):
    """Admin-curated product placement inside a homepage section."""

    section = models.ForeignKey(
        HomepageSection,
        on_delete=models.CASCADE,
        related_name='product_links',
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='homepage_section_links',
    )
    display_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['display_order', 'id']
        constraints = [
            models.UniqueConstraint(
                fields=['section', 'product'],
                name='unique_homepage_section_product',
            ),
        ]
        verbose_name = "Curated Homepage Product"
        verbose_name_plural = "Curated Homepage Products"

    def __str__(self):
        return f"{self.section.title}: {self.product.name}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        local_delete("homepage:sections")

    def delete(self, *args, **kwargs):
        result = super().delete(*args, **kwargs)
        local_delete("homepage:sections")
        return result

class HomepageVendorSettings(BaseModel):
    """Settings for vendor carousel on homepage"""
    title = models.CharField(max_length=200, default="Top Rated Vendors")
    subtitle = models.CharField(max_length=500, blank=True, default="Our trusted partners")
    vendor_count = models.IntegerField(default=8, help_text="Number of vendors to show")
    autoplay_speed = models.IntegerField(default=3000, help_text="Autoplay speed in milliseconds")
    is_active = models.BooleanField(default=True)
    
    class Meta:
        verbose_name = "Homepage Vendor Settings"
        verbose_name_plural = "Homepage Vendor Settings"
    
    def __str__(self):
        return "Vendor Carousel Settings"


class HomepageVendorSection(BaseModel):
    """Admin-managed vendor marketplace sections used by web and mobile."""
    SECTION_TYPES = [
        ('verified_vendors', 'Verified Vendors'),
        ('factory_direct_manufacturers', 'Factory Direct Manufacturers'),
        ('top_retailers', 'Top Retailers'),
        ('distributors_wholesalers', 'Distributors & Wholesalers'),
        ('service_providers', 'Service Providers'),
        ('custom', 'Custom'),
    ]
    VENDOR_TYPE_FILTERS = [
        ('', 'Any vendor type'),
        ('manufacturer', 'Manufacturer'),
        ('distributor', 'Distributor'),
        ('wholesaler', 'Wholesaler'),
        ('retailer', 'Retailer'),
        ('service_provider', 'Service Provider'),
        ('distributor_wholesaler', 'Distributor + Wholesaler'),
    ]

    title = models.CharField(max_length=200)
    description = models.CharField(max_length=500, blank=True, default='')
    section_type = models.CharField(max_length=40, choices=SECTION_TYPES, default='verified_vendors', db_index=True)
    vendor_type_filter = models.CharField(max_length=40, choices=VENDOR_TYPE_FILTERS, blank=True, default='')
    verified_only = models.BooleanField(default=True)
    manufacturer_only = models.BooleanField(default=False, help_text="Hard lock this section to vendor_type=manufacturer.")
    max_items = models.PositiveIntegerField(default=12)
    sort_order = models.IntegerField(default=0)
    empty_state_text = models.CharField(max_length=255, default='No vendors yet.', blank=True)
    view_all_url = models.CharField(max_length=500, default='/vendors/', blank=True)
    show_view_all = models.BooleanField(default=True)
    show_when_empty = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['sort_order', 'title']
        verbose_name = "Homepage Vendor Section"
        verbose_name_plural = "Homepage Vendor Sections"
        indexes = [
            models.Index(fields=['section_type', 'is_active']),
            models.Index(fields=['sort_order', 'is_active']),
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        local_delete('homepage:vendor_sections:v3')

    def delete(self, *args, **kwargs):
        result = super().delete(*args, **kwargs)
        local_delete('homepage:vendor_sections:v3')
        return result

    def get_vendor_queryset(self):
        qs = VendorProfile.objects.filter(approval_status='approved').select_related('user')
        if self.verified_only:
            qs = qs.filter(is_verified=True)
        if self.manufacturer_only or self.section_type == 'factory_direct_manufacturers':
            qs = qs.filter(vendor_type='manufacturer').filter(models.Q(is_verified=True) | models.Q(manufacturer_verified=True))
        elif self.section_type == 'top_retailers':
            qs = qs.filter(vendor_type='retailer')
        elif self.section_type == 'distributors_wholesalers':
            qs = qs.filter(vendor_type__in=['distributor', 'wholesaler'])
        elif self.section_type == 'service_providers':
            qs = qs.filter(vendor_type='service_provider')
        elif self.vendor_type_filter == 'distributor_wholesaler':
            qs = qs.filter(vendor_type__in=['distributor', 'wholesaler'])
        elif self.vendor_type_filter:
            qs = qs.filter(vendor_type=self.vendor_type_filter)
        return qs.order_by('-manufacturer_verified', '-priority_score', '-rating_avg')[:self.max_items]

class HomepageNewsletterSettings(BaseModel):
    """Settings for newsletter section"""
    title = models.CharField(max_length=200, default="Subscribe to Our Newsletter")
    subtitle = models.CharField(max_length=500, default="Get exclusive deals, new arrivals, and special offers directly to your inbox")
    button_text = models.CharField(max_length=50, default="Subscribe")
    background_color = models.CharField(max_length=20, default="#F3F4F6")
    is_active = models.BooleanField(default=True)
    
    class Meta:
        verbose_name = "Newsletter Settings"
        verbose_name_plural = "Newsletter Settings"
    
    def __str__(self):
        return "Newsletter Section Settings"

class HomepageBannerImage(BaseModel):
    """Upload images for banners"""
    IMAGE_FIT_CHOICES = HomepageBanner.IMAGE_FIT_CHOICES

    banner = models.ForeignKey(HomepageBanner, on_delete=models.CASCADE, related_name='uploaded_images')
    image = models.ImageField(upload_to='homepage/banners/', help_text="Upload banner image")
    position = models.CharField(max_length=20, choices=[
        ('left', 'Left'),
        ('right', 'Right'),
        ('center', 'Center'),
        ('background', 'Background'),
    ], default='center')
    animation = models.CharField(max_length=50, default='animate-bounce')
    width_px = models.PositiveIntegerField(null=True, blank=True, help_text="Optional custom display width in pixels.")
    height_px = models.PositiveIntegerField(null=True, blank=True, help_text="Optional custom display height in pixels.")
    object_fit = models.CharField(max_length=20, choices=IMAGE_FIT_CHOICES, default='contain')
    object_position = models.CharField(max_length=50, default='center center', help_text="CSS object-position for this image.")
    display_order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['display_order']
    
    def __str__(self):
        return f"Image for {self.banner.title} - {self.position}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        local_delete_prefix("homepage:banners:v4")

    def delete(self, *args, **kwargs):
        result = super().delete(*args, **kwargs)
        local_delete_prefix("homepage:banners:v4")
        return result

class HomepageManufacturerSettings(BaseModel):
    """Settings for manufacturers section on homepage"""
    title = models.CharField(max_length=200, default="Top Manufacturers")
    subtitle = models.CharField(max_length=500, blank=True, default="Shop from trusted brands")
    display_count = models.IntegerField(default=8, help_text="Number of manufacturers to show")
    display_order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    show_featured_only = models.BooleanField(default=True, help_text="Show only featured manufacturers")
    
    class Meta:
        verbose_name = "Homepage Manufacturer Settings"
        verbose_name_plural = "Homepage Manufacturer Settings"
    
    def __str__(self):
        return "Manufacturer Section Settings"

class HomepageManufacturerCategory(BaseModel):
    """Manufacturer categories to display on homepage"""
    category = models.ForeignKey('manufacturers.ManufacturerCategory', on_delete=models.CASCADE, related_name='homepage_categories', null=True, blank=True)
    icon = models.CharField(max_length=50, default='fas fa-industry', help_text="FontAwesome icon class")
    display_order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['display_order']
        verbose_name = "Homepage Manufacturer Category"
        verbose_name_plural = "Homepage Manufacturer Categories"
    
    def __str__(self):
        return f"{self.category.name if self.category else 'No Category'} (Order: {self.display_order})"

class HomepageVideoSection(BaseModel):
    """Video section for homepage with local video support"""
    title = models.CharField(max_length=200, default="Featured Video", help_text="Section title")
    subtitle = models.CharField(max_length=500, blank=True, help_text="Section subtitle")
    
    # Video source type
    VIDEO_SOURCE_CHOICES = [
        ('youtube', 'YouTube (Online)'),
        ('local', 'Local Video (MP4 - Works Offline)'),
        ('vimeo', 'Vimeo'),
    ]
    video_source = models.CharField(max_length=20, choices=VIDEO_SOURCE_CHOICES, default='youtube')
    
    # YouTube settings
    youtube_url = models.URLField(blank=True, help_text="YouTube video URL")
    youtube_id = models.CharField(max_length=100, blank=True, help_text="YouTube video ID (auto-extracted)")

    # Vimeo settings
    vimeo_url = models.URLField(blank=True, help_text="Vimeo video URL")
    vimeo_id = models.CharField(max_length=100, blank=True, help_text="Vimeo video ID (auto-extracted)")
    
    # Local video settings (for offline use)
    local_video = models.FileField(
        upload_to='homepage/videos/%Y/%m/',
        null=True, 
        blank=True, 
        help_text="Upload MP4 video file (works offline)",
        verbose_name="Local Video File"
    )
    poster_image = models.ImageField(
        upload_to='homepage/video_posters/%Y/%m/',
        null=True, 
        blank=True, 
        help_text="Poster/thumbnail image for video",
        verbose_name="Video Poster Image"
    )
    
    # Position options
    POSITION_CHOICES = [
        ('left', 'Left Aligned'),
        ('center', 'Center Aligned'),
        ('right', 'Right Aligned'),
    ]
    position = models.CharField(max_length=20, choices=POSITION_CHOICES, default='center')

    INFO_POSITION_CHOICES = [
        ('right', 'Info on Right'),
        ('left', 'Info on Left'),
        ('top', 'Info Above Video'),
        ('bottom', 'Info Below Video'),
        ('hidden', 'Hide Info'),
    ]
    info_position = models.CharField(
        max_length=20,
        choices=INFO_POSITION_CHOICES,
        default='right',
        help_text="Choose where title, subtitle, and button appear relative to the video.",
    )
    
    # Display options
    video_width = models.CharField(max_length=20, default="100%", help_text="Video width (e.g., 800, 100%, 80%)")
    video_height = models.IntegerField(default=450, help_text="Video height in pixels")
    autoplay = models.BooleanField(default=False, help_text="Auto-play video")
    loop = models.BooleanField(default=False, help_text="Loop video")
    show_controls = models.BooleanField(default=True, help_text="Show video controls")
    
    # For YouTube only
    modestbranding = models.BooleanField(default=True, help_text="Hide YouTube logo")
    rel = models.BooleanField(default=False, help_text="Show related videos at end")
    
    # Background and styling
    background_color = models.CharField(max_length=20, default="#F9FAFB", help_text="Section background color")
    text_color = models.CharField(max_length=20, default="#1F2937", help_text="Text color")
    
    # Call to Action button
    button_text = models.CharField(max_length=100, blank=True, help_text="Optional button text")
    button_url = models.CharField(max_length=500, blank=True, help_text="Button link URL")
    button_color = models.CharField(max_length=20, default="#3B82F6", help_text="Button color")
    
    # Display settings
    display_order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['display_order']
        verbose_name = "Homepage Video Section"
        verbose_name_plural = "Homepage Video Sections"
    
    def save(self, *args, **kwargs):
        if self.youtube_url:
            self.youtube_id = self.extract_youtube_id(self.youtube_url)
        if self.vimeo_url:
            self.vimeo_id = self.extract_vimeo_id(self.vimeo_url)
        super().save(*args, **kwargs)

    @staticmethod
    def extract_youtube_id(url):
        if re.match(r'^[a-zA-Z0-9_-]{11}$', url or ''):
            return url

        patterns = [
            r'youtube\.com/watch\?(?:.*&)?v=([\w-]+)',
            r'youtu\.be/([\w-]+)',
            r'youtube\.com/embed/([\w-]+)',
            r'youtube\.com/shorts/([\w-]+)',
            r'youtube\.com/live/([\w-]+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, url or '')
            if match:
                return match.group(1)
        return ''

    @staticmethod
    def extract_vimeo_id(url):
        patterns = [
            r'vimeo\.com/(\d+)',
            r'player\.vimeo\.com/video/(\d+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, url or '')
            if match:
                return match.group(1)
        return ''
    
    def get_video_url(self):
        """Get the appropriate video URL based on source"""
        if self.video_source == 'youtube' and self.youtube_id:
            return self.get_embed_url()
        elif self.video_source == 'local' and self.local_video:
            return self.local_video.url
        elif self.video_source == 'vimeo' and self.vimeo_id:
            return self.get_embed_url()
        return None

    @property
    def video_width_css(self):
        width = (self.video_width or '100%').strip()
        return f"{width}px" if width.isdigit() else width
    
    def get_embed_url(self):
        """Get the embed URL with parameters - with themed player"""
        if self.video_source == 'youtube' and self.youtube_id:
            params = []
            if self.autoplay:
                params.append('autoplay=1')
            if self.loop:
                params.append(f'loop=1&playlist={self.youtube_id}')
            if not self.show_controls:
                params.append('controls=0')
            if self.modestbranding:
                params.append('modestbranding=1')
            if not self.rel:
                params.append('rel=0')
            params.extend(['playsinline=1', 'enablejsapi=1', 'fs=1', 'iv_load_policy=3'])
            embed_url = f"https://www.youtube-nocookie.com/embed/{self.youtube_id}"
        elif self.video_source == 'vimeo' and self.vimeo_id:
            params = []
            if self.autoplay:
                params.append('autoplay=1')
            if self.loop:
                params.append('loop=1')
            params.append('title=0')
            params.append('byline=0')
            params.append('portrait=0')
            embed_url = f"https://player.vimeo.com/video/{self.vimeo_id}"
        else:
            return None

        if params:
            embed_url += "?" + "&".join(params)
        return embed_url
    
    def __str__(self):
        return f"Video Section - {self.title}"
