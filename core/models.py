from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.validators import RegexValidator, MinValueValidator, MaxValueValidator
from django.db import models
from core.local_cache import local_delete


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


class ContentTranslation(models.Model):
    """Admin-managed translations for model fields and shared system labels."""

    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="arolana_content_translations",
    )
    object_id = models.PositiveBigIntegerField(null=True, blank=True, db_index=True)
    content_object = GenericForeignKey("content_type", "object_id")
    translation_key = models.CharField(
        max_length=255,
        blank=True,
        db_index=True,
        help_text="Use for shared labels, for example product.condition.brand_new.",
    )
    language_code = models.CharField(
        max_length=20,
        db_index=True,
        help_text="BCP-47 language code, for example yo, ig, ha, fr, or es.",
    )
    field_name = models.CharField(
        max_length=100,
        blank=True,
        help_text="Model field being translated, for example name, description, or specifications.",
    )
    translated_text = models.TextField()
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("content_type", "object_id", "field_name", "language_code")
        indexes = [
            models.Index(fields=("content_type", "object_id", "language_code")),
            models.Index(fields=("translation_key", "language_code", "is_active")),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("content_type", "object_id", "language_code", "field_name"),
                condition=models.Q(content_type__isnull=False, object_id__isnull=False),
                name="unique_content_field_translation",
            ),
            models.UniqueConstraint(
                fields=("translation_key", "language_code"),
                condition=~models.Q(translation_key=""),
                name="unique_system_key_translation",
            ),
        ]
        verbose_name = "Content Translation"
        verbose_name_plural = "Content Translations"

    def clean(self):
        from django.core.exceptions import ValidationError

        has_object = bool(self.content_type_id and self.object_id and self.field_name)
        has_key = bool(self.translation_key)
        if has_object == has_key:
            raise ValidationError(
                "Choose either a model object/field or a translation key, not both."
            )

    def __str__(self):
        target = self.translation_key or f"{self.content_type} #{self.object_id}.{self.field_name}"
        return f"{target} [{self.language_code}]"


class ProtectedImageAsset(models.Model):
    """Hash registry for uploaded images so Arolana can detect unsafe duplicates."""

    DUPLICATE_STATUS_CHOICES = (
        ("original", "Original"),
        ("same_vendor_reuse", "Same Vendor Reuse"),
        ("needs_review", "Needs Review"),
        ("approved", "Admin Allowed"),
        ("rejected", "Rejected"),
    )
    DUPLICATE_TYPE_CHOICES = (
        ("", "Not a Duplicate"),
        ("exact", "Exact Duplicate"),
        ("near", "Likely / Near Duplicate"),
    )

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField(db_index=True)
    field_name = models.CharField(max_length=100, db_index=True)
    file_name = models.CharField(max_length=500, db_index=True)
    original_filename = models.CharField(max_length=500, blank=True)
    sha256 = models.CharField(max_length=64, db_index=True)
    perceptual_hash = models.CharField(max_length=32, blank=True, db_index=True)
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    size_bytes = models.PositiveIntegerField(null=True, blank=True)
    is_duplicate = models.BooleanField(default=False, db_index=True)
    duplicate_type = models.CharField(
        max_length=20,
        choices=DUPLICATE_TYPE_CHOICES,
        blank=True,
        db_index=True,
    )
    duplicate_status = models.CharField(
        max_length=30,
        choices=DUPLICATE_STATUS_CHOICES,
        default="original",
        db_index=True,
    )
    perceptual_distance = models.PositiveSmallIntegerField(null=True, blank=True)
    duplicate_of = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="duplicate_assets",
    )
    allow_duplicate = models.BooleanField(
        default=False,
        help_text="Admin override for legitimate shared manufacturer/product images.",
    )
    duplicate_reason = models.TextField(blank=True)
    uploader = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="uploaded_protected_images",
    )
    vendor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="vendor_protected_images",
    )
    source_product_id = models.PositiveBigIntegerField(null=True, blank=True, db_index=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reviewed_protected_images",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at",)
        indexes = [
            models.Index(fields=("content_type", "object_id")),
            models.Index(fields=("sha256", "is_duplicate")),
            models.Index(fields=("perceptual_hash", "is_duplicate")),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("content_type", "object_id", "field_name", "file_name"),
                name="unique_protected_image_asset",
            )
        ]
        verbose_name = "Protected Image Asset"
        verbose_name_plural = "Protected Image Assets"

    def __str__(self):
        return f"{self.content_type} #{self.object_id} {self.field_name}"

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
    smart_chat_bot_image = models.ImageField(
        upload_to='settings/smart-chat/',
        null=True,
        blank=True,
        help_text="Smart Chat bot avatar (recommended: square PNG or WebP, at least 256x256).",
    )
    logo_height_desktop = models.PositiveIntegerField(default=88, help_text="Storefront logo height on desktop in pixels")
    logo_height_mobile = models.PositiveIntegerField(default=58, help_text="Storefront logo height on mobile/tablet in pixels")
    footer_logo_height = models.PositiveIntegerField(default=76, help_text="Footer logo height in pixels")
    
    # Contact Information
    contact_email = models.EmailField(default='contact@arolana.com')
    contact_phone = models.CharField(max_length=50, default='1-800-AROLANA')

    support_whatsapp_number = models.CharField(
    max_length=40,
    blank=True,
    default='2349132924620',
    help_text='Arolana admin/support WhatsApp number. Use international format, for example: 2349132924620.',
)

    cart_whatsapp_message = models.TextField(
    blank=True,
    default=(
        'Hello Arolana Support, I am contacting you from the cart page.\n\n'
        'I need help with my cart, checkout, delivery, payment, or order support '
        'before completing my purchase.'
    ),
    help_text='First WhatsApp message customers send when contacting support from the cart page.',
)

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
    
    @classmethod
    def load(cls):
        obj = cls.objects.first()
        if obj:
            return obj
        return cls.objects.create()

    class Meta:
        verbose_name = 'Site Setting'
        verbose_name_plural = 'Site Settings'
    
    def __str__(self):
        return self.site_name
    
    def save(self, *args, **kwargs):
        if not self.pk and SiteSettings.objects.exists():
            raise ValueError("Only one SiteSettings instance can exist")
        super().save(*args, **kwargs)
        local_delete('global_context:site_settings')

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

class HomePageAppearance(BaseModel):
    """
    Singleton homepage appearance settings.
    Controls desktop and mobile homepage background from admin.
    """

    title = models.CharField(max_length=120, default="Homepage Background Settings")

    desktop_background_image = models.ImageField(
        upload_to="homepage/backgrounds/desktop/",
        blank=True,
        null=True,
        help_text="Desktop homepage background. Recommended: 1920×1080 WebP.",
    )
    mobile_background_image = models.ImageField(
        upload_to="homepage/backgrounds/mobile/",
        blank=True,
        null=True,
        help_text="Mobile homepage background. Recommended: 1080×1350 WebP or 1080×1920 WebP.",
    )

    desktop_overlay_opacity = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        default=0.35,
        validators=[MinValueValidator(0), MaxValueValidator(1)],
        help_text="Desktop overlay opacity. 0.15 = clear image, 0.35 = balanced, 0.70 = muted.",
    )
    mobile_overlay_opacity = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        default=0.50,
        validators=[MinValueValidator(0), MaxValueValidator(1)],
        help_text="Mobile overlay opacity. Mobile usually needs stronger overlay for readability.",
    )

    desktop_position = models.CharField(
        max_length=50,
        default="center center",
        help_text="Desktop CSS background position. Example: center center, top center, center right.",
    )
    mobile_position = models.CharField(
        max_length=50,
        default="center center",
        help_text="Mobile CSS background position. Example: center center, top center, center right.",
    )

    blur_background = models.BooleanField(
        default=False,
        help_text="Softly blur the homepage background image.",
    )
    fixed_background = models.BooleanField(
        default=True,
        help_text="Keep desktop background fixed while scrolling. Mobile uses scroll for performance.",
    )
    make_sections_glass = models.BooleanField(
        default=True,
        help_text="Make homepage cards and white sections slightly transparent so the background shows nicely.",
    )

    class Meta:
        verbose_name = "Homepage Appearance"
        verbose_name_plural = "Homepage Appearance"

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)
        local_delete("global_context:homepage_appearance")

    @classmethod
    def load(cls):
        obj, _created = cls.objects.get_or_create(pk=1)
        return obj
