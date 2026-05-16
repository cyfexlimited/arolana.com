from django.db import models
from django.core.validators import MaxValueValidator, MinValueValidator
from core.models import BaseModel
from accounts.models import User
from django.utils import timezone

def normalize_opacity(value):
    """Accept legacy percent-like values and return a valid CSS opacity."""
    try:
        opacity = float(value)
    except (TypeError, ValueError):
        return 0.4

    if opacity < 0:
        opacity = abs(opacity)
    if opacity > 1:
        opacity = opacity / 100

    return min(max(opacity, 0), 1)

class HeroBanner(BaseModel):
    """Advanced Hero Banner with full features"""
    IMAGE_FIT_CHOICES = [
        ('cover', 'Fill frame (crop if needed)'),
        ('contain', 'Fit whole image'),
        ('fill', 'Stretch to frame'),
        ('scale-down', 'Scale down only'),
    ]

    MOBILE_CONTENT_LAYOUT_CHOICES = [
        ('image_only', 'Image only on mobile (B&H style)'),
        ('overlay', 'Text over image'),
        ('below', 'Text below image'),
    ]
    
    # Basic Content
    title = models.CharField(max_length=200, help_text="Main headline text")
    subtitle = models.CharField(max_length=500, blank=True, help_text="Secondary text")
    description = models.TextField(blank=True, help_text="Additional description")
    
    # Media
    image_desktop = models.ImageField(upload_to='hero_banners/desktop/', blank=True, null=True, help_text="Desktop image (1920x1080 recommended)")
    image_tablet = models.ImageField(upload_to='hero_banners/tablet/', null=True, blank=True, help_text="Tablet image (1024x768)")
    image_mobile = models.ImageField(upload_to='hero_banners/mobile/', null=True, blank=True, help_text="Mobile image (768x1024)")

    # Size & crop controls
    desktop_height = models.PositiveIntegerField(default=560, validators=[MinValueValidator(160), MaxValueValidator(1200)], help_text="Desktop hero height in pixels.")
    tablet_height = models.PositiveIntegerField(default=460, validators=[MinValueValidator(160), MaxValueValidator(1000)], help_text="Tablet hero height in pixels.")
    mobile_height = models.PositiveIntegerField(default=380, validators=[MinValueValidator(180), MaxValueValidator(900)], help_text="Mobile hero height in pixels. Around 360-420 gives a B&H-style mobile banner.")
    image_fit_desktop = models.CharField(max_length=20, choices=IMAGE_FIT_CHOICES, default='cover')
    image_fit_tablet = models.CharField(max_length=20, choices=IMAGE_FIT_CHOICES, default='cover')
    image_fit_mobile = models.CharField(max_length=20, choices=IMAGE_FIT_CHOICES, default='cover')
    image_position_desktop = models.CharField(max_length=50, default='center center', help_text="CSS object-position. Examples: center center, left center, 50% 35%.")
    image_position_tablet = models.CharField(max_length=50, default='center center', help_text="CSS object-position for tablet.")
    image_position_mobile = models.CharField(max_length=50, default='center center', help_text="CSS object-position for mobile.")
    mobile_content_layout = models.CharField(max_length=20, choices=MOBILE_CONTENT_LAYOUT_CHOICES, default='image_only', help_text="Use image only when your mobile image already contains the text/buttons.")
    
    # 3D & Animation Effects
    EFFECTS_CHOICES = [
        ('fade', 'Fade'),
        ('slide', 'Slide'),
        ('zoom', 'Zoom'),
        ('none', 'No Effect'),
    ]
    animation_effect = models.CharField(max_length=20, choices=EFFECTS_CHOICES, default='fade')
    animation_duration = models.FloatField(default=0.8, help_text="Animation duration in seconds")
    
    # Buttons & CTA
    BUTTON_STYLE_CHOICES = [
        ('primary', 'Primary'),
        ('secondary', 'Secondary'),
        ('outline', 'Outline'),
    ]

    button1_text = models.CharField(max_length=50, blank=True, default='')
    button1_url = models.CharField(max_length=500, blank=True, default='')
    button1_style = models.CharField(max_length=20, choices=BUTTON_STYLE_CHOICES, default='primary')
    
    button2_text = models.CharField(max_length=50, blank=True, default='')
    button2_url = models.CharField(max_length=500, blank=True, default='#')
    button2_style = models.CharField(max_length=20, choices=BUTTON_STYLE_CHOICES, default='outline')

    button3_text = models.CharField(max_length=50, blank=True, default='')
    button3_url = models.CharField(max_length=500, blank=True, default='')
    button3_style = models.CharField(max_length=20, choices=BUTTON_STYLE_CHOICES, default='secondary')
    
    # Advanced Styling
    overlay_color = models.CharField(max_length=20, default='#000000')
    overlay_opacity = models.FloatField(
        default=0.4,
        validators=[MinValueValidator(0), MaxValueValidator(1)],
        help_text="0 is transparent, 1 is fully dark. Example: 0.4",
    )
    text_color = models.CharField(max_length=20, default='#FFFFFF')
    text_alignment = models.CharField(max_length=20, choices=[
        ('left', 'Left'), ('center', 'Center'), ('right', 'Right'),
    ], default='center')
    content_position = models.CharField(max_length=20, choices=[
        ('top', 'Top'), ('center', 'Center'), ('bottom', 'Bottom'),
    ], default='center')
    
    # Scheduling
    start_date = models.DateTimeField(null=True, blank=True)
    end_date = models.DateTimeField(null=True, blank=True)
    
    # Display Settings
    display_order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    autoplay_delay = models.IntegerField(default=5000)
    
    # Analytics
    views_count = models.IntegerField(default=0)
    clicks_count = models.IntegerField(default=0)
    
    class Meta:
        ordering = ['display_order', '-created_at']
    
    def __str__(self):
        return self.title

    @property
    def overlay_opacity_css(self):
        return f"{normalize_opacity(self.overlay_opacity):.2f}".rstrip('0').rstrip('.')

    @property
    def show_button1(self):
        return bool(self.button1_text and self.button1_url and self.button1_url != '#')

    @property
    def show_button2(self):
        return bool(self.button2_text and self.button2_url and self.button2_url != '#')

    @property
    def show_button3(self):
        return bool(self.button3_text and self.button3_url and self.button3_url != '#')
    
    def increment_view(self):
        self.views_count += 1
        self.save()
    
    def increment_click(self):
        self.clicks_count += 1
        self.save()

class HeroBannerAnalytics(BaseModel):
    banner = models.ForeignKey(HeroBanner, on_delete=models.CASCADE, related_name='analytics')
    session_id = models.CharField(max_length=200, blank=True, null=True)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=20, choices=[('view', 'View'), ('click', 'Click')])
    timestamp = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-timestamp']
