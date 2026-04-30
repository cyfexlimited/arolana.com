from django.db import models
from core.models import BaseModel
from accounts.models import User
from django.utils import timezone

class HeroBanner(BaseModel):
    """Advanced Hero Banner with full features"""
    
    # Basic Content
    title = models.CharField(max_length=200, help_text="Main headline text")
    subtitle = models.CharField(max_length=500, blank=True, help_text="Secondary text")
    description = models.TextField(blank=True, help_text="Additional description")
    
    # Media
    image_desktop = models.ImageField(upload_to='hero_banners/desktop/', blank=True, null=True, help_text="Desktop image (1920x1080 recommended)")
    image_tablet = models.ImageField(upload_to='hero_banners/tablet/', null=True, blank=True, help_text="Tablet image (1024x768)")
    image_mobile = models.ImageField(upload_to='hero_banners/mobile/', null=True, blank=True, help_text="Mobile image (768x1024)")
    
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
    button1_text = models.CharField(max_length=50, default='Shop Now')
    button1_url = models.CharField(max_length=500, default='/products/')
    button1_style = models.CharField(max_length=20, default='primary')
    
    button2_text = models.CharField(max_length=50, default='Learn More')
    button2_url = models.CharField(max_length=500, blank=True, default='#')
    button2_style = models.CharField(max_length=20, default='outline')
    
    # Advanced Styling
    overlay_color = models.CharField(max_length=20, default='#000000')
    overlay_opacity = models.FloatField(default=0.4)
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