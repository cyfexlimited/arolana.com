from django.core.validators import RegexValidator
from django.db import models


hex_color_validator = RegexValidator(
    regex=r'^#(?:[0-9a-fA-F]{3}){1,2}$',
    message='Enter a valid hex color, for example #F8FAFC.',
)

class BaseModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        abstract = True

class SiteSettings(BaseModel):
    # Basic Information
    site_name = models.CharField(max_length=100, default='Arolana')
    site_tagline = models.CharField(max_length=200, default='Premium Multi-Vendor Marketplace', blank=True)
    site_description = models.TextField(blank=True, help_text="SEO description for the site")
    site_keywords = models.CharField(max_length=500, blank=True, help_text="SEO keywords, comma separated")
    
    # Branding
    site_logo = models.ImageField(upload_to='settings/', null=True, blank=True, help_text="Main logo (recommended size: 200x60)")
    site_favicon = models.ImageField(upload_to='settings/', null=True, blank=True, help_text="Browser favicon (recommended size: 32x32)")
    footer_logo = models.ImageField(upload_to='settings/', null=True, blank=True, help_text="Footer logo")
    
    # Contact Information
    contact_email = models.EmailField(default='contact@arolana.com')
    contact_phone = models.CharField(max_length=50, default='1-800-AROLANA')
    address = models.TextField(blank=True)
    
    # Social Media
    facebook_url = models.URLField(blank=True)
    twitter_url = models.URLField(blank=True)
    instagram_url = models.URLField(blank=True)
    linkedin_url = models.URLField(blank=True)
    youtube_url = models.URLField(blank=True)
    
    # Colors & Styling
    primary_color = models.CharField(max_length=7, default='#3B82F6', help_text="Primary brand color")
    secondary_color = models.CharField(max_length=7, default='#10B981', help_text="Secondary brand color")
    
    # Footer Content
    footer_copyright = models.CharField(max_length=200, default='© 2024 Arolana.com. All rights reserved.')
    shipping_note = models.CharField(max_length=200, default='Free shipping on orders over $50', blank=True)
    return_policy = models.CharField(max_length=200, default='30-day easy returns', blank=True)
    warranty_note = models.CharField(max_length=200, default='2-year warranty on all products', blank=True)
    
    # Meta Information
    meta_author = models.CharField(max_length=100, blank=True)
    meta_robots = models.CharField(max_length=100, default='index, follow', blank=True)
    
    class Meta:
        verbose_name = 'Site Setting'
        verbose_name_plural = 'Site Settings'
    
    def __str__(self):
        return self.site_name
    
    def save(self, *args, **kwargs):
        if not self.pk and SiteSettings.objects.exists():
            raise ValueError("Only one SiteSettings instance can exist")
        super().save(*args, **kwargs)

class PromoBanner(BaseModel):
    """Promotional banner for homepage"""
    title = models.CharField(max_length=200, default='Summer Mega Sale!')
    subtitle = models.CharField(max_length=500, blank=True, default='Get up to 50% off on selected items + Free Shipping')
    button_text = models.CharField(max_length=50, default='Shop Now')
    button_url = models.CharField(max_length=500, default='/products/?deals=true')
    background_color_start = models.CharField(max_length=7, default='#3B82F6', help_text="Start color (e.g., #3B82F6)")
    background_color_end = models.CharField(max_length=7, default='#9333EA', help_text="End color (e.g., #9333EA)")
    image = models.ImageField(upload_to='promo/', null=True, blank=True, help_text="Optional background image")
    is_active = models.BooleanField(default=True)
    order = models.IntegerField(default=0, help_text="Display order")
    
    class Meta:
        ordering = ['order']
        verbose_name = "Promo Banner"
        verbose_name_plural = "Promo Banners"
    
    def __str__(self):
        return self.title


class AdminAppearance(BaseModel):
    """Editable colors for the Jazzmin admin interface."""

    name = models.CharField(max_length=100, default='Default Admin Theme')
    page_background_color = models.CharField(max_length=7, default='#F6F8FB', validators=[hex_color_validator])
    content_background_color = models.CharField(max_length=7, default='#FFFFFF', validators=[hex_color_validator])
    card_background_color = models.CharField(max_length=7, default='#FFFFFF', validators=[hex_color_validator])
    text_color = models.CharField(max_length=7, default='#111827', validators=[hex_color_validator])
    muted_text_color = models.CharField(max_length=7, default='#667085', validators=[hex_color_validator])
    primary_color = models.CharField(max_length=7, default='#2563EB', validators=[hex_color_validator])
    accent_color = models.CharField(max_length=7, default='#0F766E', validators=[hex_color_validator])
    hero_start_color = models.CharField(max_length=7, default='#111827', validators=[hex_color_validator])
    hero_end_color = models.CharField(max_length=7, default='#0F766E', validators=[hex_color_validator])
    navbar_background_color = models.CharField(max_length=7, default='#FFFFFF', validators=[hex_color_validator])
    navbar_text_color = models.CharField(max_length=7, default='#111827', validators=[hex_color_validator])
    sidebar_background_color = models.CharField(max_length=7, default='#FFFFFF', validators=[hex_color_validator])
    sidebar_text_color = models.CharField(max_length=7, default='#1F2937', validators=[hex_color_validator])

    class Meta:
        verbose_name = 'Admin Appearance'
        verbose_name_plural = 'Admin Appearance'

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if self.is_active:
            AdminAppearance.objects.exclude(pk=self.pk).update(is_active=False)
        super().save(*args, **kwargs)
