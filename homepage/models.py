from django.db import models
from core.models import BaseModel
from products.models import Category, Product
from vendors.models import VendorProfile

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

class HomepageBanner(BaseModel):
    """Manageable promo banner on homepage"""
    title = models.CharField(max_length=200, default="Summer Mega Sale!")
    subtitle = models.CharField(max_length=500, blank=True, default="Get up to 50% off on selected items + Free Shipping")
    button_text = models.CharField(max_length=50, default="Shop Now")
    button_url = models.CharField(max_length=500, default="/products/?deals=true")
    background_color_start = models.CharField(max_length=20, default="#3B82F6", help_text="Gradient start color")
    background_color_end = models.CharField(max_length=20, default="#8B5CF6", help_text="Gradient end color")
    
    # Floating images
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
        ordering = ['display_order']
        verbose_name = "Homepage Banner"
        verbose_name_plural = "Homepage Banners"
    
    def __str__(self):
        return self.title

class HomepageSection(BaseModel):
    """Manageable sections on homepage"""
    SECTION_TYPES = [
        ('featured', 'Featured Products'),
        ('new', 'New Arrivals'),
        ('bestsellers', 'Best Sellers'),
        ('trending', 'Trending'),
        ('custom', 'Custom Section'),
    ]
    
    title = models.CharField(max_length=200)
    section_type = models.CharField(max_length=20, choices=SECTION_TYPES, default='featured')
    subtitle = models.CharField(max_length=500, blank=True)
    display_order = models.IntegerField(default=0)
    products_limit = models.IntegerField(default=8, help_text="Number of products to show")
    view_all_url = models.CharField(max_length=500, blank=True, default="/products/")
    is_active = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['display_order']
        verbose_name = "Homepage Section"
        verbose_name_plural = "Homepage Sections"
    
    def __str__(self):
        return f"{self.title} ({self.get_section_type_display()})"
    
    def get_products(self):
        """Get products based on section type - APPROVED ONLY"""
        if self.section_type == 'featured':
            return Product.objects.filter(is_featured=True, is_active=True, approval_status='approved')[:self.products_limit]
        elif self.section_type == 'new':
            return Product.objects.filter(is_new=True, is_active=True, approval_status='approved')[:self.products_limit]
        elif self.section_type == 'bestsellers':
            return Product.objects.filter(is_bestseller=True, is_active=True, approval_status='approved')[:self.products_limit]
        elif self.section_type == 'trending':
            return Product.objects.filter(is_active=True, approval_status='approved').order_by('-sales_count')[:self.products_limit]
        else:
            return Product.objects.filter(is_active=True, approval_status='approved')[:self.products_limit]

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
    banner = models.ForeignKey(HomepageBanner, on_delete=models.CASCADE, related_name='uploaded_images')
    image = models.ImageField(upload_to='homepage/banners/', help_text="Upload banner image")
    position = models.CharField(max_length=20, choices=[
        ('left', 'Left'),
        ('right', 'Right'),
        ('center', 'Center'),
        ('background', 'Background'),
    ], default='center')
    animation = models.CharField(max_length=50, default='animate-bounce')
    display_order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['display_order']
    
    def __str__(self):
        return f"Image for {self.banner.title} - {self.position}"

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
        # Extract YouTube video ID from URL
        if self.youtube_url and 'youtube.com' in self.youtube_url:
            if 'v=' in self.youtube_url:
                self.youtube_id = self.youtube_url.split('v=')[1].split('&')[0]
            elif 'youtu.be/' in self.youtube_url:
                self.youtube_id = self.youtube_url.split('youtu.be/')[1].split('?')[0]
        super().save(*args, **kwargs)
    
    def get_video_url(self):
        """Get the appropriate video URL based on source"""
        if self.video_source == 'youtube' and self.youtube_id:
            return self.get_embed_url()
        elif self.video_source == 'local' and self.local_video:
            return self.local_video.url
        return None
    
    def get_embed_url(self):
        """Get the embed URL with parameters - with themed player"""
        if not self.youtube_id:
            return None
        
        params = []
        
        # Basic parameters
        if self.autoplay:
            params.append('autoplay=1')
        if self.loop:
            params.append('loop=1')
        if not self.show_controls:
            params.append('controls=0')
        if self.modestbranding:
            params.append('modestbranding=1')
        if not self.rel:
            params.append('rel=0')
        
        # Additional parameters for better playback and theming
        params.append('playsinline=1')
        params.append('enablejsapi=1')
        params.append('color=white')
        params.append('theme=light')
        params.append('fs=1')
        params.append('iv_load_policy=3')
        
        embed_url = f"https://www.youtube-nocookie.com/embed/{self.youtube_id}"
        if params:
            embed_url += "?" + "&".join(params)
        return embed_url
    
    def __str__(self):
        return f"Video Section - {self.title}"