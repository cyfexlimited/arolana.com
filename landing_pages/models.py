import re

from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from core.models import BaseModel


class LandingPage(BaseModel):
    PAGE_FLEXIBLE_PAYMENT = "flexible_payment"
    PAGE_FINANCING = "financing"
    PAGE_PROMOTION = "promotion"
    PAGE_CATEGORY_CAMPAIGN = "category_campaign"
    PAGE_BRAND_CAMPAIGN = "brand_campaign"
    PAGE_CUSTOM = "custom"

    PAGE_TYPE_CHOICES = [
        (PAGE_FLEXIBLE_PAYMENT, "Flexible Payment"),
        (PAGE_FINANCING, "Financing"),
        (PAGE_PROMOTION, "Promotion"),
        (PAGE_CATEGORY_CAMPAIGN, "Category Campaign"),
        (PAGE_BRAND_CAMPAIGN, "Brand Campaign"),
        (PAGE_CUSTOM, "Custom"),
    ]

    STATUS_DRAFT = "draft"
    STATUS_PUBLISHED = "published"
    STATUS_ARCHIVED = "archived"

    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_PUBLISHED, "Published"),
        (STATUS_ARCHIVED, "Archived"),
    ]

    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    subtitle = models.CharField(max_length=500, blank=True)
    page_type = models.CharField(max_length=40, choices=PAGE_TYPE_CHOICES, default=PAGE_CUSTOM)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    is_featured = models.BooleanField(default=False, db_index=True)
    show_on_homepage = models.BooleanField(default=False, db_index=True)
    show_in_nav = models.BooleanField(default=False, db_index=True)
    navigation_label = models.CharField(max_length=120, blank=True)

    hero_badge_text = models.CharField(max_length=120, blank=True)
    hero_headline = models.CharField(max_length=255, blank=True)
    hero_subheadline = models.TextField(blank=True)
    hero_background_image = models.ImageField(upload_to="landing_pages/hero/", blank=True, null=True)
    hero_mobile_image = models.ImageField(upload_to="landing_pages/hero_mobile/", blank=True, null=True)
    hero_video_url = models.URLField(blank=True)
    hero_overlay_opacity = models.DecimalField(max_digits=4, decimal_places=2, default=0.56)

    primary_cta_text = models.CharField(max_length=100, blank=True)
    primary_cta_url = models.CharField(max_length=500, blank=True)
    secondary_cta_text = models.CharField(max_length=100, blank=True)
    secondary_cta_url = models.CharField(max_length=500, blank=True)
    trust_badges = models.JSONField(default=list, blank=True)

    primary_color = models.CharField(max_length=20, default="#2563EB")
    accent_color = models.CharField(max_length=20, default="#F97316")
    dark_color = models.CharField(max_length=20, default="#0F172A")
    background_color = models.CharField(max_length=20, default="#F8FAFC")
    text_color = models.CharField(max_length=20, default="#0F172A")
    custom_css = models.TextField(blank=True)

    # Full page background image control
    page_background_image = models.ImageField(
        upload_to="landing_pages/backgrounds/",
        blank=True,
        null=True,
        help_text="Optional full-page background image shown behind landing page sections.",
    )
    page_background_overlay_opacity = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        default=0.35,
        validators=[MinValueValidator(0), MaxValueValidator(1)],
        help_text="Background overlay opacity. Use 0.00 for clear image, 1.00 for very strong overlay.",
    )
    page_background_blur = models.BooleanField(
        default=False,
        help_text="Softly blur the full-page background image.",
    )
    page_background_fixed = models.BooleanField(
        default=True,
        help_text="Keep background image fixed while scrolling for a premium effect.",
    )
    page_background_position = models.CharField(
        max_length=50,
        default="center center",
        help_text="CSS background position. Example: center center, top center, center right.",
    )

    meta_title = models.CharField(max_length=255, blank=True)
    meta_description = models.CharField(max_length=500, blank=True)
    meta_keywords = models.CharField(max_length=500, blank=True)
    og_title = models.CharField(max_length=255, blank=True)
    og_description = models.CharField(max_length=500, blank=True)
    og_image = models.ImageField(upload_to="landing_pages/og/", blank=True, null=True)
    canonical_url = models.URLField(blank=True)
    schema_markup = models.JSONField(default=dict, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-is_featured", "-published_at", "title"]
        indexes = [
            models.Index(fields=["slug", "status", "is_active"]),
            models.Index(fields=["page_type", "status"]),
            models.Index(fields=["show_on_homepage", "is_active"]),
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)
        if self.status == self.STATUS_PUBLISHED and not self.published_at:
            self.published_at = timezone.now()
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("landing_page_clean_detail", kwargs={"slug": self.slug})

    @property
    def public_title(self):
        return self.hero_headline or self.title

    @property
    def public_description(self):
        return self.meta_description or self.hero_subheadline or self.subtitle

    @property
    def og_image_url(self):
        image = self.og_image or self.hero_background_image
        if not image:
            return ""
        try:
            return image.url
        except Exception:
            return ""


class LandingPageSection(BaseModel):
    SECTION_HERO = "hero"
    SECTION_BENEFITS = "benefits"
    SECTION_OFFERS = "offers"
    SECTION_HOW_IT_WORKS = "how_it_works"
    SECTION_ELIGIBLE_CATEGORIES = "eligible_categories"
    SECTION_PRODUCT_GRID = "product_grid"
    SECTION_COMPARISON = "comparison"
    SECTION_TESTIMONIALS = "testimonials"
    SECTION_FAQ = "faq"
    SECTION_CONTACT = "contact"
    SECTION_TERMS = "terms"
    SECTION_VIDEO = "video"
    SECTION_VIDEO_GUIDES = "video_guides"
    SECTION_GALLERY = "gallery"
    SECTION_CUSTOM_HTML = "custom_html"

    SECTION_TYPE_CHOICES = [
        (SECTION_HERO, "Hero"),
        (SECTION_BENEFITS, "Benefits"),
        (SECTION_OFFERS, "Offers"),
        (SECTION_HOW_IT_WORKS, "How It Works"),
        (SECTION_ELIGIBLE_CATEGORIES, "Eligible Categories"),
        (SECTION_PRODUCT_GRID, "Product Grid"),
        (SECTION_COMPARISON, "Comparison"),
        (SECTION_TESTIMONIALS, "Testimonials"),
        (SECTION_FAQ, "FAQ"),
        (SECTION_CONTACT, "Contact"),
        (SECTION_TERMS, "Terms"),
        (SECTION_VIDEO, "Video"),
        (SECTION_VIDEO_GUIDES, "Video Guides"),
        (SECTION_GALLERY, "Gallery"),
        (SECTION_CUSTOM_HTML, "Custom HTML"),
    ]

    landing_page = models.ForeignKey(LandingPage, on_delete=models.CASCADE, related_name="sections")
    section_type = models.CharField(max_length=40, choices=SECTION_TYPE_CHOICES)
    title = models.CharField(max_length=255, blank=True)
    subtitle = models.CharField(max_length=500, blank=True)
    content = models.TextField(blank=True)
    background_color = models.CharField(max_length=20, blank=True)
    text_color = models.CharField(max_length=20, blank=True)
    image = models.ImageField(upload_to="landing_pages/sections/", blank=True, null=True)
    video_url = models.URLField(blank=True)
    button_text = models.CharField(max_length=100, blank=True)
    button_url = models.CharField(max_length=500, blank=True)
    sort_order = models.PositiveIntegerField(default=0, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    extra_data = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["sort_order", "id"]
        indexes = [
            models.Index(fields=["landing_page", "section_type", "is_active", "sort_order"]),
        ]

    def __str__(self):
        return f"{self.landing_page.title} - {self.get_section_type_display()}"


class LandingPageBenefit(BaseModel):
    landing_page = models.ForeignKey(LandingPage, on_delete=models.CASCADE, related_name="benefits")
    section = models.ForeignKey(LandingPageSection, on_delete=models.SET_NULL, related_name="benefits", null=True, blank=True)
    icon = models.CharField(max_length=80, blank=True)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    link_text = models.CharField(max_length=100, blank=True)
    link_url = models.CharField(max_length=500, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self):
        return self.title


class LandingPageOffer(BaseModel):
    landing_page = models.ForeignKey(LandingPage, on_delete=models.CASCADE, related_name="offers")
    section = models.ForeignKey(LandingPageSection, on_delete=models.SET_NULL, related_name="offers", null=True, blank=True)
    icon = models.CharField(max_length=80, blank=True)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    offer_label = models.CharField(max_length=120, blank=True)
    price_text = models.CharField(max_length=120, blank=True)
    discount_text = models.CharField(max_length=120, blank=True)
    button_text = models.CharField(max_length=100, blank=True)
    button_url = models.CharField(max_length=500, blank=True)
    image = models.ImageField(upload_to="landing_pages/offers/", blank=True, null=True)
    start_date = models.DateTimeField(null=True, blank=True)
    end_date = models.DateTimeField(null=True, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self):
        return self.title


class LandingPageStep(BaseModel):
    landing_page = models.ForeignKey(LandingPage, on_delete=models.CASCADE, related_name="steps")
    section = models.ForeignKey(LandingPageSection, on_delete=models.SET_NULL, related_name="steps", null=True, blank=True)
    step_number = models.PositiveIntegerField(default=1)
    icon = models.CharField(max_length=80, blank=True)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "step_number", "id"]

    def __str__(self):
        return self.title


class LandingPageCategoryCard(BaseModel):
    landing_page = models.ForeignKey(LandingPage, on_delete=models.CASCADE, related_name="category_cards")
    section = models.ForeignKey(LandingPageSection, on_delete=models.SET_NULL, related_name="category_cards", null=True, blank=True)
    icon = models.CharField(max_length=80, blank=True)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to="landing_pages/category_cards/", blank=True, null=True)
    category = models.ForeignKey("products.Category", on_delete=models.SET_NULL, null=True, blank=True, related_name="landing_page_cards")
    button_text = models.CharField(max_length=100, blank=True)
    button_url = models.CharField(max_length=500, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self):
        return self.title

    @property
    def resolved_url(self):
        if self.button_url:
            return self.button_url
        if self.category:
            return self.category.get_absolute_url()
        return "#"


class LandingPageComparisonItem(BaseModel):
    SIDE_NEGATIVE = "negative"
    SIDE_POSITIVE = "positive"
    SIDE_CHOICES = [
        (SIDE_NEGATIVE, "Negative"),
        (SIDE_POSITIVE, "Positive"),
    ]

    landing_page = models.ForeignKey(LandingPage, on_delete=models.CASCADE, related_name="comparison_items")
    section = models.ForeignKey(LandingPageSection, on_delete=models.SET_NULL, related_name="comparison_items", null=True, blank=True)
    side = models.CharField(max_length=20, choices=SIDE_CHOICES)
    icon = models.CharField(max_length=80, blank=True)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["side", "sort_order", "id"]

    def __str__(self):
        return self.title


class LandingPageTestimonial(BaseModel):
    landing_page = models.ForeignKey(LandingPage, on_delete=models.CASCADE, related_name="testimonials")
    section = models.ForeignKey(LandingPageSection, on_delete=models.SET_NULL, related_name="testimonials", null=True, blank=True)
    quote = models.TextField()
    customer_name = models.CharField(max_length=180)
    customer_title = models.CharField(max_length=180, blank=True)
    customer_location = models.CharField(max_length=180, blank=True)
    rating = models.PositiveSmallIntegerField(default=5)
    image = models.ImageField(upload_to="landing_pages/testimonials/", blank=True, null=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self):
        return self.customer_name


class LandingPageFAQ(BaseModel):
    landing_page = models.ForeignKey(LandingPage, on_delete=models.CASCADE, related_name="faqs")
    section = models.ForeignKey(LandingPageSection, on_delete=models.SET_NULL, related_name="faqs", null=True, blank=True)
    question = models.CharField(max_length=255)
    answer = models.TextField()
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self):
        return self.question


class LandingPageCTA(BaseModel):
    STYLE_PRIMARY = "primary"
    STYLE_SECONDARY = "secondary"
    STYLE_OUTLINE = "outline"
    STYLE_DARK = "dark"
    STYLE_LIGHT = "light"
    STYLE_CHOICES = [
        (STYLE_PRIMARY, "Primary"),
        (STYLE_SECONDARY, "Secondary"),
        (STYLE_OUTLINE, "Outline"),
        (STYLE_DARK, "Dark"),
        (STYLE_LIGHT, "Light"),
    ]

    OPEN_SAME_PAGE = "same_page"
    OPEN_NEW_TAB = "new_tab"
    OPEN_CHOICES = [
        (OPEN_SAME_PAGE, "Same Page"),
        (OPEN_NEW_TAB, "New Tab"),
    ]

    landing_page = models.ForeignKey(LandingPage, on_delete=models.CASCADE, related_name="ctas")
    section = models.ForeignKey(LandingPageSection, on_delete=models.SET_NULL, related_name="ctas", null=True, blank=True)
    label = models.CharField(max_length=100)
    url = models.CharField(max_length=500)
    style = models.CharField(max_length=20, choices=STYLE_CHOICES, default=STYLE_PRIMARY)
    open_behavior = models.CharField(max_length=20, choices=OPEN_CHOICES, default=OPEN_SAME_PAGE)
    icon = models.CharField(max_length=80, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self):
        return self.label


class LandingPageContactOption(BaseModel):
    landing_page = models.ForeignKey(LandingPage, on_delete=models.CASCADE, related_name="contact_options")
    icon = models.CharField(max_length=80, blank=True)
    label = models.CharField(max_length=100)
    value = models.CharField(max_length=255)
    url = models.CharField(max_length=500, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self):
        return f"{self.label}: {self.value}"


class LandingPageVideoGuide(BaseModel):
    PLATFORM_YOUTUBE = "youtube"
    PLATFORM_VIMEO = "vimeo"
    PLATFORM_EXTERNAL = "external"
    PLATFORM_CHOICES = [
        (PLATFORM_YOUTUBE, "YouTube"),
        (PLATFORM_VIMEO, "Vimeo"),
        (PLATFORM_EXTERNAL, "External"),
    ]

    landing_page = models.ForeignKey(LandingPage, on_delete=models.CASCADE, related_name="video_guides")
    section = models.ForeignKey(LandingPageSection, on_delete=models.SET_NULL, related_name="video_guides", null=True, blank=True)
    title = models.CharField(max_length=255)
    subtitle = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    video_url = models.URLField()
    thumbnail = models.ImageField(upload_to="landing_pages/video_thumbnails/", blank=True, null=True)
    duration = models.CharField(max_length=20, blank=True, help_text="Example: 1:55")
    platform = models.CharField(max_length=20, choices=PLATFORM_CHOICES, default=PLATFORM_YOUTUBE)
    button_text = models.CharField(max_length=100, default="Watch Video")
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self):
        return self.title

    @property
    def youtube_id(self):
        patterns = [
            r"youtube\.com/watch\?(?:.*&)?v=([\w-]+)",
            r"youtu\.be/([\w-]+)",
            r"youtube\.com/embed/([\w-]+)",
            r"youtube\.com/shorts/([\w-]+)",
            r"youtube\.com/live/([\w-]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, self.video_url or "")
            if match:
                return match.group(1)
        return ""

    @property
    def thumbnail_url(self):
        if self.thumbnail:
            try:
                return self.thumbnail.url
            except Exception:
                return ""
        if self.platform == self.PLATFORM_YOUTUBE and self.youtube_id:
            return f"https://img.youtube.com/vi/{self.youtube_id}/hqdefault.jpg"
        return ""

    @property
    def embed_url(self):
        if self.platform == self.PLATFORM_YOUTUBE and self.youtube_id:
            return f"https://www.youtube.com/embed/{self.youtube_id}?rel=0&modestbranding=1&playsinline=1"
        if self.platform == self.PLATFORM_VIMEO:
            match = re.search(r"vimeo\.com/(?:video/)?(\d+)", self.video_url or "")
            if match:
                return f"https://player.vimeo.com/video/{match.group(1)}"
        return ""
