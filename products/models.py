from decimal import Decimal

import random
import re
import string

from django.core.exceptions import ValidationError
from django.core.validators import (
    MaxValueValidator,
    MinValueValidator,
)
from django.db import models
from django.urls import reverse
from django.utils.text import slugify
from django.utils.timezone import now
from django_ckeditor_5.fields import CKEditor5Field
from phonenumber_field.modelfields import PhoneNumberField
from taggit.managers import TaggableManager

from accounts.models import User
from core.image_protection import (
    ProtectedImageUploadPath,
    protect_uploaded_image,
    record_protected_image,
)
from core.models import BaseModel
from core.private_upload_validation import (
    validate_private_profile_image_upload,
    validate_review_video_upload,
)


# =============================================================================
# VENDOR MODEL
# =============================================================================


class Vendor(BaseModel):
    """Vendor/Seller profile."""

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="vendor",
    )

    shop_name = models.CharField(
        max_length=200,
        unique=True,
        db_index=True,
    )

    shop_slug = models.SlugField(
        max_length=255,
        unique=True,
        db_index=True,
    )

    shop_logo = models.ImageField(
        upload_to=ProtectedImageUploadPath(
            "vendors/logos"
        ),
        null=True,
        blank=True,
    )

    shop_banner = models.ImageField(
        upload_to=ProtectedImageUploadPath(
            "vendors/banners"
        ),
        null=True,
        blank=True,
    )

    shop_description = models.TextField(
        blank=True,
    )

    # Contact Information

    shop_phone = PhoneNumberField(
        null=True,
        blank=True,
    )

    shop_email = models.EmailField(
        null=True,
        blank=True,
    )

    shop_website = models.URLField(
        blank=True,
    )

    # Business Information

    business_address = models.TextField(
        blank=True,
    )

    business_license = models.CharField(
        max_length=100,
        blank=True,
    )

    tax_id = models.CharField(
        max_length=100,
        blank=True,
    )

    # Verification & Status

    is_verified = models.BooleanField(
        default=False,
        db_index=True,
    )

    verification_date = models.DateTimeField(
        null=True,
        blank=True,
    )

    is_active = models.BooleanField(
        default=True,
        db_index=True,
    )

    # Statistics

    total_products = models.IntegerField(
        default=0,
        validators=[
            MinValueValidator(0),
        ],
    )

    total_sales = models.IntegerField(
        default=0,
        validators=[
            MinValueValidator(0),
        ],
    )

    rating_avg = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        default=0,
        validators=[
            MinValueValidator(0),
            MaxValueValidator(5),
        ],
    )

    rating_count = models.IntegerField(
        default=0,
        validators=[
            MinValueValidator(0),
        ],
    )

    total_reviews = models.IntegerField(
        default=0,
        validators=[
            MinValueValidator(0),
        ],
    )

    # Commission & Policies

    commission_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=5.00,
        validators=[
            MinValueValidator(0),
            MaxValueValidator(100),
        ],
        help_text="Commission percentage",
    )

    response_time = models.CharField(
        max_length=50,
        blank=True,
        help_text="Average response time",
    )

    return_policy = models.TextField(
        blank=True,
    )

    class Meta:
        ordering = [
            "-created_at",
        ]

        indexes = [
            models.Index(
                fields=[
                    "is_verified",
                    "is_active",
                ]
            ),
            models.Index(
                fields=[
                    "-rating_avg",
                ]
            ),
        ]

    def save(
        self,
        *args,
        **kwargs,
    ):
        protect_uploaded_image(
            self,
            "shop_logo",
        )

        protect_uploaded_image(
            self,
            "shop_banner",
        )

        if not self.shop_slug:
            self.shop_slug = slugify(
                self.shop_name
            )

        super().save(
            *args,
            **kwargs,
        )

        record_protected_image(
            self,
            "shop_logo",
        )

        record_protected_image(
            self,
            "shop_banner",
        )

    def __str__(self):
        return self.shop_name

    def get_absolute_url(self):
        return reverse(
            "products:vendor",
            kwargs={
                "slug": self.shop_slug,
            },
        )


# =============================================================================
# CATEGORY MODEL
# =============================================================================


class Category(BaseModel):
    """Product categories with hierarchical support."""

    name = models.CharField(
        max_length=100,
        unique=True,
        db_index=True,
    )

    slug = models.SlugField(
        max_length=255,
        unique=True,
        db_index=True,
    )

    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="children",
    )

    image = models.ImageField(
        upload_to=ProtectedImageUploadPath(
            "categories"
        ),
        null=True,
        blank=True,
        help_text=(
            "Category thumbnail image "
            "(for cards)"
        ),
    )

    background_image = models.ImageField(
        upload_to=ProtectedImageUploadPath(
            "categories/backgrounds"
        ),
        null=True,
        blank=True,
        help_text=(
            "Hero background image for category "
            "landing page (1920x400 recommended)"
        ),
    )

    icon = models.CharField(
        max_length=50,
        blank=True,
        help_text=(
            "CSS icon class or icon name"
        ),
    )

    description = models.TextField(
        blank=True,
        help_text=(
            "Category description for SEO"
        ),
    )

    hero_title = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text=(
            "Custom hero title "
            "(overrides default category name)"
        ),
    )

    hero_subtitle = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        help_text=(
            "Hero subtitle text displayed "
            "on category landing page"
        ),
    )

    show_hero_eyebrow = models.BooleanField(
        default=True,
        help_text=(
            "Show the small category hero "
            "eyebrow label."
        ),
    )

    show_hero_title = models.BooleanField(
        default=True,
        help_text=(
            "Show the category hero title."
        ),
    )

    show_hero_subtitle = models.BooleanField(
        default=True,
        help_text=(
            "Show the category hero "
            "subtitle/description."
        ),
    )

    show_hero_stats = models.BooleanField(
        default=True,
        help_text=(
            "Show product/vendor/subcategory "
            "metrics on the category hero."
        ),
    )

    show_hero_cta = models.BooleanField(
        default=True,
        help_text=(
            "Show the category hero CTA button."
        ),
    )

    show_hero_side_image = models.BooleanField(
        default=True,
        help_text=(
            "Show the optional category side image."
        ),
    )

    hero_background_color = models.CharField(
        max_length=20,
        blank=True,
        default="",
        help_text=(
            "Optional category hero background color, "
            "used behind or instead of an image. "
            "Example: #0f172a"
        ),
    )

    hero_text_color = models.CharField(
        max_length=20,
        blank=True,
        default="",
        help_text=(
            "Optional category hero text color. "
            "Example: #ffffff"
        ),
    )

    hero_accent_color = models.CharField(
        max_length=20,
        blank=True,
        default="",
        help_text=(
            "Optional category hero accent color "
            "for badges and stats."
        ),
    )

    hero_button_background_color = models.CharField(
        max_length=20,
        blank=True,
        default="",
        help_text=(
            "Optional category hero button "
            "background color."
        ),
    )

    hero_button_text_color = models.CharField(
        max_length=20,
        blank=True,
        default="",
        help_text=(
            "Optional category hero button text color."
        ),
    )

    hero_image_brightness = models.PositiveSmallIntegerField(
        default=62,
        help_text=(
            "Hero image brightness percentage. "
            "Lower values make the banner darker; "
            "100 keeps the image original."
        ),
    )

    hero_height_desktop = models.PositiveIntegerField(
        default=520,
        help_text=(
            "Category hero height on desktop in pixels."
        ),
    )

    hero_height_tablet = models.PositiveIntegerField(
        default=440,
        help_text=(
            "Category hero height on tablet in pixels."
        ),
    )

    hero_height_mobile = models.PositiveIntegerField(
        default=360,
        help_text=(
            "Category hero height on mobile in pixels."
        ),
    )

    meta_title = models.CharField(
        max_length=200,
        blank=True,
        help_text="SEO title",
    )

    meta_description = models.TextField(
        blank=True,
        help_text=(
            "SEO description (160 chars)"
        ),
    )

    meta_keywords = models.CharField(
        max_length=200,
        blank=True,
    )

    order = models.IntegerField(
        default=0,
        db_index=True,
    )

    is_navigation_featured = models.BooleanField(
        default=True,
        db_index=True,
        help_text=(
            "Show this top-level category in the desktop "
            "priority navigation rail. It always remains "
            "available in All Categories."
        ),
    )

    is_active = models.BooleanField(
        default=True,
        db_index=True,
    )

    class Meta:
        verbose_name_plural = "Categories"

        ordering = [
            "order",
            "name",
        ]

        indexes = [
            models.Index(
                fields=[
                    "is_active",
                    "order",
                ]
            ),
            models.Index(
                fields=[
                    "parent",
                    "is_active",
                ]
            ),
        ]

    def save(
        self,
        *args,
        **kwargs,
    ):
        protect_uploaded_image(
            self,
            "image",
        )

        protect_uploaded_image(
            self,
            "background_image",
        )

        if not self.slug:
            self.slug = slugify(
                self.name
            )

        super().save(
            *args,
            **kwargs,
        )

        record_protected_image(
            self,
            "image",
        )

        record_protected_image(
            self,
            "background_image",
        )

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse(
            "products:category",
            kwargs={
                "slug": self.slug,
            },
        )

    def get_ancestors(self):
        """Get all parent categories."""

        ancestors = []

        current = self.parent

        while current:
            ancestors.append(
                current
            )

            current = (
                current.parent
            )

        return reversed(
            ancestors
        )

    @property
    def product_count(self):
        """
        Get total products in this category,
        including subcategories.
        """

        category_ids = [
            self.id,
        ]

        for child in (
            self.children
            .filter(
                is_active=True
            )
        ):
            category_ids.append(
                child.id
            )

            for grandchild in (
                child.children
                .filter(
                    is_active=True
                )
            ):
                category_ids.append(
                    grandchild.id
                )

        return (
            Product.objects
            .filter(
                category_id__in=(
                    category_ids
                ),
                is_active=True,
            )
            .count()
        )

    @property
    def display_hero_title(self):
        return (
            self.hero_title
            if self.hero_title
            else self.name
        )

    @property
    def display_hero_subtitle(self):
        if self.hero_subtitle:
            return self.hero_subtitle

        if self.description:
            return self.description

        return (
            "Discover our curated collection of "
            f"{self.name.lower()} products"
        )

    @property
    def has_background_image(self):
        return bool(
            self.background_image
        )


# =============================================================================
# BRAND MODEL
# =============================================================================


class Brand(BaseModel):
    """Product brands/manufacturers."""

    LOGO_DISPLAY_CONTAIN = "contain"
    LOGO_DISPLAY_FILL = "fill"
    LOGO_DISPLAY_TRANSPARENT = "transparent"

    LOGO_DISPLAY_MODE_CHOICES = [
        (
            LOGO_DISPLAY_CONTAIN,
            "Contain with padding",
        ),
        (
            LOGO_DISPLAY_FILL,
            "Fill card",
        ),
        (
            LOGO_DISPLAY_TRANSPARENT,
            "Transparent / no background",
        ),
    ]

    name = models.CharField(
        max_length=100,
        unique=True,
        db_index=True,
    )

    slug = models.SlugField(
        max_length=255,
        unique=True,
        db_index=True,
    )

    logo = models.ImageField(
        upload_to=ProtectedImageUploadPath(
            "brands"
        ),
        null=True,
        blank=True,
    )

    logo_display_mode = models.CharField(
        "Brand logo display",
        max_length=30,
        choices=LOGO_DISPLAY_MODE_CHOICES,
        default=LOGO_DISPLAY_CONTAIN,
        help_text=(
            "Choose how the uploaded brand logo appears on Brand Detail pages. "
            "Use Fill card when the uploaded logo image already includes its "
            "own background. Use Transparent / no background for transparent "
            "PNG/WebP logos."
        ),
    )

    description = models.TextField(
        blank=True,
    )

    website = models.URLField(
        blank=True,
    )

    is_active = models.BooleanField(
        default=True,
        db_index=True,
    )

    featured = models.BooleanField(
        default=False,
    )

    class Meta:
        ordering = [
            "name",
        ]

        indexes = [
            models.Index(
                fields=[
                    "is_active",
                    "featured",
                ]
            ),
        ]

    def save(
        self,
        *args,
        **kwargs,
    ):
        protect_uploaded_image(
            self,
            "logo",
        )

        if not self.slug:
            self.slug = slugify(
                self.name
            )

        super().save(
            *args,
            **kwargs,
        )

        record_protected_image(
            self,
            "logo",
        )

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse(
            "products:brand_detail",
            kwargs={
                "slug": self.slug,
            },
        )


# =============================================================================
# PRODUCT MODEL
# =============================================================================


class Product(BaseModel):
    """
    Enhanced product model with comprehensive features
    and approval system.
    """

    CONDITION_BRAND_NEW = "brand_new"
    CONDITION_OPEN_BOX = "open_box"
    CONDITION_UK_USED = "uk_used"
    CONDITION_FOREIGN_USED = "foreign_used"
    CONDITION_LOCALLY_USED = "locally_used"
    CONDITION_REFURBISHED = "refurbished"
    CONDITION_FAIRLY_USED = "fairly_used"
    CONDITION_CERTIFIED_PRE_OWNED = "certified_pre_owned"

    PRODUCT_CONDITION_CHOICES = [
        (
            CONDITION_BRAND_NEW,
            "Brand New",
        ),
        (
            CONDITION_OPEN_BOX,
            "Open Box",
        ),
        (
            CONDITION_UK_USED,
            "UK Used",
        ),
        (
            CONDITION_FOREIGN_USED,
            "Foreign Used",
        ),
        (
            CONDITION_LOCALLY_USED,
            "Locally Used",
        ),
        (
            CONDITION_REFURBISHED,
            "Refurbished",
        ),
        (
            CONDITION_FAIRLY_USED,
            "Fairly Used",
        ),
        (
            CONDITION_CERTIFIED_PRE_OWNED,
            "Certified Pre-Owned",
        ),
    ]

    # =========================================================================
    # BASIC INFORMATION
    # =========================================================================

    sku = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text="Unique product identifier",
    )

    manufacturer_sku = models.CharField(
        max_length=100,
        blank=True,
        db_index=True,
        help_text=(
            "Optional SKU/model number "
            "supplied by the manufacturer"
        ),
    )

    name = models.CharField(
        max_length=200,
        db_index=True,
    )

    slug = models.SlugField(
        max_length=255,
        unique=True,
        db_index=True,
    )

    condition = models.CharField(
        max_length=30,
        choices=PRODUCT_CONDITION_CHOICES,
        default=CONDITION_BRAND_NEW,
        db_index=True,
        help_text=(
            "Clearly disclose whether this item is "
            "brand new, used, open box, or refurbished."
        ),
    )

    description = CKEditor5Field()

    specifications = CKEditor5Field(
        blank=True,
        null=True,
        help_text=(
            "Product specifications and technical details"
        ),
    )

    # =========================================================================
    # RELATIONSHIPS
    # =========================================================================

    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name="products",
        db_index=True,
    )

    brand = models.ForeignKey(
        Brand,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
    )

    vendor = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="products",
        limit_choices_to={
            "user_type": "vendor",
        },
        db_index=True,
    )

    # =========================================================================
    # PRICING
    # =========================================================================

    price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[
            MinValueValidator(
                Decimal("0.01")
            ),
        ],
        db_index=True,
    )

    compare_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(
                Decimal("0.01")
            ),
        ],
        help_text=(
            "Original price before discount"
        ),
    )

    cost_per_item = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(
                Decimal("0.01")
            ),
        ],
        help_text=(
            "Your cost per item "
            "(for profit calculation)"
        ),
    )

    wholesale_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(
                Decimal("0.01")
            ),
        ],
        help_text=(
            "Optional manufacturer/wholesale unit price."
        ),
    )

    bulk_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(
                Decimal("0.01")
            ),
        ],
        help_text=(
            "Optional bulk buying unit price."
        ),
    )

    # =========================================================================
    # INVENTORY
    # =========================================================================

    stock_quantity = models.IntegerField(
        default=0,
        validators=[
            MinValueValidator(0),
        ],
        db_index=True,
        help_text=(
            "Current stock quantity"
        ),
    )

    low_stock_threshold = models.IntegerField(
        default=5,
        validators=[
            MinValueValidator(0),
        ],
        help_text=(
            "Alert when stock reaches this level"
        ),
    )

    is_in_stock = models.BooleanField(
        default=True,
        db_index=True,
    )

    allow_backorder = models.BooleanField(
        default=False,
        help_text=(
            "Allow customers to order "
            "when out of stock"
        ),
    )

    reserved_quantity = models.IntegerField(
        default=0,
        validators=[
            MinValueValidator(0),
        ],
        help_text=(
            "Quantity reserved for pending orders"
        ),
    )

    minimum_order_quantity = models.PositiveIntegerField(
        default=1,
        help_text=(
            "Minimum order quantity for "
            "wholesale/manufacturer orders."
        ),
    )

    moq_unit = models.CharField(
        max_length=40,
        default="unit",
        blank=True,
        help_text=(
            "MOQ unit, e.g. unit, carton, "
            "pallet, roll."
        ),
    )

    sample_available = models.BooleanField(
        default=False,
    )

    sample_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(
                Decimal("0.01")
            ),
        ],
    )

    lead_time_days = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text=(
            "Estimated production/dispatch "
            "lead time in days."
        ),
    )

    country_of_origin = models.CharField(
        max_length=120,
        blank=True,
    )

    manufacturer_address = models.TextField(
        blank=True,
    )

    certifications = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "Certification names or document labels."
        ),
    )

    # =========================================================================
    # PHYSICAL ATTRIBUTES
    # =========================================================================

    weight = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(
                Decimal("0.001")
            ),
        ],
        help_text="Product weight",
    )

    weight_unit = models.CharField(
        max_length=10,
        choices=[
            (
                "kg",
                "Kilograms",
            ),
            (
                "lbs",
                "Pounds",
            ),
            (
                "g",
                "Grams",
            ),
            (
                "oz",
                "Ounces",
            ),
        ],
        default="kg",
    )

    dimensions_length = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(
                Decimal("0.01")
            ),
        ],
        help_text="Length",
    )

    dimensions_width = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(
                Decimal("0.01")
            ),
        ],
        help_text="Width",
    )

    dimensions_height = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(
                Decimal("0.01")
            ),
        ],
        help_text="Height",
    )

    dimension_unit = models.CharField(
        max_length=10,
        choices=[
            (
                "cm",
                "Centimeters",
            ),
            (
                "in",
                "Inches",
            ),
            (
                "mm",
                "Millimeters",
            ),
        ],
        default="cm",
    )

    # =========================================================================
    # WARRANTY
    # =========================================================================

    warranty_years = models.IntegerField(
        default=1,
        validators=[
            MinValueValidator(0),
        ],
        help_text=(
            "Warranty period in years"
        ),
    )

    warranty_description = models.TextField(
        blank=True,
        help_text="Warranty terms",
    )

    extended_warranty_available = models.BooleanField(
        default=False,
    )

    extended_warranty_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(
                Decimal("0.01")
            ),
        ],
    )

    # =========================================================================
    # MEDIA
    # =========================================================================

    main_image = models.ImageField(
        upload_to=ProtectedImageUploadPath(
            "products"
        ),
        null=True,
        blank=True,
        help_text=(
            "Main product image (featured)"
        ),
    )

    # =========================================================================
    # PRODUCT PAGE DISPLAY CONTROLS
    # =========================================================================

    show_top_gallery = models.BooleanField(
        default=True,
        help_text=(
            "Show the normal product image gallery "
            "at the top of the product detail page."
        ),
    )

    show_auto_overview_gallery = models.BooleanField(
        default=True,
        help_text=(
            "Show uploaded product images automatically "
            "inside the Overview tab."
        ),
    )

    auto_fill_description_images = models.BooleanField(
        default=True,
        help_text=(
            "Automatically fill image placeholders in "
            "the styled product description using uploaded "
            "product gallery images."
        ),
    )

    # =========================================================================
    # VIDEO
    # =========================================================================

    VIDEO_TYPE_CHOICES = [
        (
            "youtube",
            "YouTube",
        ),
        (
            "vimeo",
            "Vimeo",
        ),
        (
            "local",
            "Local Video",
        ),
    ]

    video_type = models.CharField(
        max_length=20,
        choices=VIDEO_TYPE_CHOICES,
        default="youtube",
        blank=True,
    )

    video_url = models.URLField(
        blank=True,
        help_text=(
            "YouTube or Vimeo URL"
        ),
    )

    local_video = models.FileField(
        upload_to="products/videos/%Y/%m/",
        null=True,
        blank=True,
        help_text=(
            "Local video file (MP4, WebM)"
        ),
    )

    video_thumbnail = models.ImageField(
        upload_to=ProtectedImageUploadPath(
            "products/video_thumbs"
        ),
        null=True,
        blank=True,
    )

    video_title = models.CharField(
        max_length=200,
        blank=True,
    )

    manual_pdf = models.FileField(
        upload_to="products/manuals/%Y/%m/",
        null=True,
        blank=True,
        help_text=(
            "Optional PDF manual, brochure, or "
            "specification sheet for customer download."
        ),
    )

    # =========================================================================
    # SEO
    # =========================================================================

    meta_title = models.CharField(
        max_length=200,
        blank=True,
        help_text=(
            "SEO title (60 chars)"
        ),
    )

    meta_description = models.TextField(
        blank=True,
        max_length=160,
        help_text=(
            "SEO description (160 chars)"
        ),
    )

    meta_keywords = models.CharField(
        max_length=200,
        blank=True,
        help_text=(
            "Comma-separated SEO keywords"
        ),
    )

    # =========================================================================
    # STATISTICS
    # =========================================================================

    views_count = models.IntegerField(
        default=0,
        validators=[
            MinValueValidator(0),
        ],
    )

    sales_count = models.IntegerField(
        default=0,
        validators=[
            MinValueValidator(0),
        ],
    )

    rating_avg = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        default=0,
        validators=[
            MinValueValidator(0),
            MaxValueValidator(5),
        ],
    )

    rating_count = models.IntegerField(
        default=0,
        validators=[
            MinValueValidator(0),
        ],
    )

    # =========================================================================
    # FEATURES & STATUS
    # =========================================================================

    is_featured = models.BooleanField(
        default=False,
        db_index=True,
        help_text=(
            "Show on homepage"
        ),
    )

    is_new = models.BooleanField(
        default=False,
        db_index=True,
        help_text="New arrival",
    )

    is_bestseller = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Bestseller",
    )

    is_active = models.BooleanField(
        default=True,
        db_index=True,
    )

    # =========================================================================
    # APPROVAL SYSTEM
    # =========================================================================

    APPROVAL_STATUS_CHOICES = [
        (
            "draft",
            "Draft",
        ),
        (
            "pending",
            "Pending Approval",
        ),
        (
            "approved",
            "Approved",
        ),
        (
            "rejected",
            "Rejected",
        ),
        (
            "requires_changes",
            "Requires Changes",
        ),
    ]

    approval_status = models.CharField(
        max_length=20,
        choices=APPROVAL_STATUS_CHOICES,
        default="pending",
        db_index=True,
    )

    approval_notes = models.TextField(
        blank=True,
        help_text=(
            "Notes from admin about approval/rejection"
        ),
    )

    approved_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_products",
    )

    approved_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    submitted_for_review_at = models.DateTimeField(
        auto_now_add=True,
    )

    resubmitted_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    # =========================================================================
    # TAGS
    # =========================================================================

    tags = TaggableManager(
        blank=True,
    )

    class Meta:
        ordering = [
            "-created_at",
        ]

        indexes = [
            models.Index(
                fields=[
                    "sku",
                ]
            ),
            models.Index(
                fields=[
                    "slug",
                ]
            ),
            models.Index(
                fields=[
                    "category",
                    "is_active",
                    "approval_status",
                ]
            ),
            models.Index(
                fields=[
                    "-created_at",
                ]
            ),
            models.Index(
                fields=[
                    "vendor",
                    "is_active",
                ]
            ),
            models.Index(
                fields=[
                    "is_featured",
                    "-created_at",
                ]
            ),
            models.Index(
                fields=[
                    "is_bestseller",
                    "-sales_count",
                ]
            ),
            models.Index(
                fields=[
                    "rating_avg",
                    "-rating_count",
                ]
            ),
            models.Index(
                fields=[
                    "approval_status",
                    "-submitted_for_review_at",
                ]
            ),
            models.Index(
                fields=[
                    "minimum_order_quantity",
                ]
            ),
        ]

    def clean(self):
        """Validate product data."""

        self.description = (
            self._strip_placeholder_images(
                self.description
            )
        )

        self.specifications = (
            self._strip_placeholder_images(
                self.specifications
            )
        )

        if (
            self.compare_price
            and self.compare_price
            <= self.price
        ):
            raise ValidationError(
                "Compare price must be greater than price"
            )

        if self.stock_quantity < 0:
            raise ValidationError(
                "Stock quantity cannot be negative"
            )

        if (
            self.manual_pdf
            and not str(
                self.manual_pdf.name
            )
            .lower()
            .endswith(
                ".pdf"
            )
        ):
            raise ValidationError(
                {
                    "manual_pdf": (
                        "Only PDF manuals or brochures "
                        "are allowed."
                    ),
                }
            )

        vendor_profile = (
            self.vendor_profile
        )

        if (
            self.approval_status
            == "approved"
            and vendor_profile
            and not vendor_profile.address_is_complete
        ):
            raise ValidationError(
                {
                    "vendor": (
                        "Vendor address, city, state, and "
                        "country must be completed before "
                        "publishing approved products."
                    ),
                }
            )

    @staticmethod
    def _strip_placeholder_images(
        value,
    ):
        """
        Never persist editor image placeholders
        as customer-facing URLs.
        """

        html = str(
            value
            or ""
        )

        html = re.sub(
            (
                r"<figure\b[^>]*>"
                r"[\s\S]*?"
                r"UPLOAD_PRODUCT_IMAGE_URL_HERE"
                r"[\s\S]*?"
                r"</figure>"
            ),
            "",
            html,
            flags=re.IGNORECASE,
        )

        return re.sub(
            (
                r"<img\b[^>]*"
                r"UPLOAD_PRODUCT_IMAGE_URL_HERE"
                r"[^>]*>"
            ),
            "",
            html,
            flags=re.IGNORECASE,
        )

    def save(
        self,
        *args,
        **kwargs,
    ):
        if self.certifications in (None, "", "null"):
            self.certifications = []

        self.clean()

        protect_uploaded_image(
            self,
            "main_image",
        )

        protect_uploaded_image(
            self,
            "video_thumbnail",
        )

        if not self.sku:
            self.sku = (
                self._generate_sku()
            )

        requested_slug = slugify(
            self.slug
            or self.name
        )

        self.slug = self.build_unique_slug(
            name=self.name,
            vendor=self.vendor,
            requested_slug=requested_slug,
            current_pk=self.pk,
        )

        self._slug_was_adjusted = (
            self.slug
            != requested_slug
        )

        self.is_in_stock = (
            self.get_available_stock()
            > 0
        )

        super().save(
            *args,
            **kwargs,
        )

        record_protected_image(
            self,
            "main_image",
        )

        record_protected_image(
            self,
            "video_thumbnail",
        )

    @classmethod
    def build_unique_slug(
        cls,
        name,
        vendor=None,
        requested_slug="",
        current_pk=None,
    ):
        base = (
            slugify(
                requested_slug
                or name
            )
            or "product"
        )

        base = (
            base[:255]
            .strip("-")
            or "product"
        )

        queryset = (
            cls.objects.all()
        )

        if current_pk:
            queryset = queryset.exclude(
                pk=current_pk
            )

        if not queryset.filter(
            slug=base
        ).exists():
            return base

        vendor_suffixes = []

        if vendor is not None:
            try:
                profile_slug = slugify(
                    vendor
                    .vendor_profile
                    .store_slug
                )

            except Exception:
                profile_slug = ""

            for value in (
                profile_slug,
                slugify(
                    getattr(
                        vendor,
                        "username",
                        "",
                    )
                ),
                (
                    f"vendor-{getattr(vendor, 'pk', '')}"
                    if getattr(
                        vendor,
                        "pk",
                        None,
                    )
                    else ""
                ),
            ):
                if (
                    value
                    and value
                    not in vendor_suffixes
                ):
                    vendor_suffixes.append(
                        value
                    )

        for suffix in vendor_suffixes:
            candidate = (
                f"{base[:max(1, 254 - len(suffix))]}"
                f"-{suffix}"
            ).strip("-")

            if not queryset.filter(
                slug=candidate
            ).exists():
                return candidate

        counter = 2

        while True:
            suffix = str(
                counter
            )

            candidate = (
                f"{base[:max(1, 254 - len(suffix))]}"
                f"-{suffix}"
            ).strip("-")

            if not queryset.filter(
                slug=candidate
            ).exists():
                return candidate

            counter += 1

    def _generate_sku(self):
        """Generate unique SKU."""

        prefix = (
            f"{self.category.slug[:3]}-"
            f"{self.brand.slug[:3] if self.brand else 'XXX'}"
        ).upper()

        random_part = "".join(
            random.choices(
                string.digits,
                k=8,
            )
        )

        return (
            f"{prefix}{random_part}"
        )

    def __str__(self):
        return (
            f"{self.name} "
            f"({self.sku})"
        )

    def get_absolute_url(self):
        return reverse(
            "products:detail",
            kwargs={
                "slug": self.slug,
            },
        )

    @property
    def vendor_profile(self):
        vendor_user = getattr(
            self,
            "vendor",
            None,
        )

        if not vendor_user:
            return None

        try:
            return (
                vendor_user.vendor_profile
            )

        except Exception:
            return None

    @property
    def vendor_display_name(self):
        profile = (
            self.vendor_profile
        )

        if profile:
            return profile.display_name

        vendor_user = getattr(
            self,
            "vendor",
            None,
        )

        if vendor_user:
            return (
                vendor_user.get_full_name()
                or vendor_user.username
                or vendor_user.email
                or "Arolana Vendor"
            )

        return "Arolana Vendor"

    @property
    def vendor_verified(self):
        profile = (
            self.vendor_profile
        )

        return bool(
            profile
            and (
                profile.is_verified
                or profile.manufacturer_verified
                or profile.has_verified_kyc()
            )
        )

    @property
    def vendor_package_name(self):
        profile = (
            self.vendor_profile
        )

        return (
            profile.active_plan_name
            if profile
            else "Vendor"
        )

    @property
    def condition_label(self):
        try:
            return (
                self.get_condition_display()
            )

        except Exception:
            return (
                str(
                    self.condition
                    or ""
                )
                .replace(
                    "_",
                    " ",
                )
                .title()
            )

    @property
    def location_label(self):
        profile = (
            self.vendor_profile
        )

        return (
            profile.location_label
            if profile
            else ""
        )

    @property
    def discount_percent(self):
        if (
            self.compare_price
            and self.compare_price
            > self.price
        ):
            discount = (
                (
                    self.compare_price
                    - self.price
                )
                / self.compare_price
            ) * 100

            return int(
                discount
            )

        return 0

    @property
    def is_low_stock(self):
        return (
            self.stock_quantity
            <= self.low_stock_threshold
            and self.stock_quantity
            > 0
        )

    @property
    def available_stock(self):
        return max(
            0,
            self.stock_quantity
            - self.reserved_quantity,
        )

    def get_available_stock(self):
        return self.available_stock

    @property
    def profit_margin(self):
        if (
            self.cost_per_item
            and self.price
            > self.cost_per_item
        ):
            margin = (
                (
                    self.price
                    - self.cost_per_item
                )
                / self.price
            ) * 100

            return round(
                margin,
                2,
            )

        return 0

    @property
    def dimensions(self):
        if all(
            [
                self.dimensions_length,
                self.dimensions_width,
                self.dimensions_height,
            ]
        ):
            return (
                f"{self.dimensions_length}×"
                f"{self.dimensions_width}×"
                f"{self.dimensions_height} "
                f"{self.dimension_unit}"
            )

        return None

    @property
    def formatted_weight(self):
        if self.weight:
            return (
                f"{self.weight} "
                f"{self.weight_unit}"
            )

        return None

    # =========================================================================
    # APPROVAL SYSTEM METHODS
    # =========================================================================

    def needs_approval(self):
        return (
            self.approval_status
            == "pending"
        )

    def is_approved(self):
        return (
            self.approval_status
            == "approved"
        )

    def is_rejected(self):
        return (
            self.approval_status
            in [
                "rejected",
                "requires_changes",
            ]
        )

    def resubmit_for_approval(self):
        self.approval_status = (
            "pending"
        )

        self.approval_notes = ""

        self.resubmitted_at = now()

        self.save()

    def get_video_embed_url(self):
        if not self.video_type:
            return None

        if (
            self.video_type
            == "local"
            and self.local_video
        ):
            return self.local_video.url

        if (
            self.video_type
            == "youtube"
            and self.video_url
        ):
            return self._extract_youtube_embed(
                self.video_url
            )

        if (
            self.video_type
            == "vimeo"
            and self.video_url
        ):
            return self._extract_vimeo_embed(
                self.video_url
            )

        return None

    @staticmethod
    def _extract_youtube_embed(
        url,
    ):
        patterns = [
            r"youtube\.com/watch\?(?:.*&)?v=([\w-]+)",
            r"youtu\.be/([\w-]+)",
            r"youtube\.com/embed/([\w-]+)",
            r"youtube\.com/shorts/([\w-]+)",
            r"youtube\.com/live/([\w-]+)",
        ]

        for pattern in patterns:
            match = re.search(
                pattern,
                url
                or "",
            )

            if match:
                video_id = (
                    match.group(1)
                )

                return (
                    "https://www.youtube.com/embed/"
                    f"{video_id}"
                    "?rel=0&modestbranding=1&playsinline=1"
                )

        if re.match(
            r"^[a-zA-Z0-9_-]{11}$",
            url
            or "",
        ):
            return (
                "https://www.youtube.com/embed/"
                f"{url}"
                "?rel=0&modestbranding=1&playsinline=1"
            )

        return None

    @staticmethod
    def _extract_vimeo_embed(
        url,
    ):
        patterns = [
            r"vimeo\.com/(\d+)",
            r"player\.vimeo\.com/video/(\d+)",
        ]

        for pattern in patterns:
            match = re.search(
                pattern,
                url
                or "",
            )

            if match:
                return (
                    "https://player.vimeo.com/video/"
                    f"{match.group(1)}"
                )

        if re.match(
            r"^\d+$",
            url
            or "",
        ):
            return (
                "https://player.vimeo.com/video/"
                f"{url}"
            )

        return None

    def increment_views(self):
        Product.objects.filter(
            pk=self.pk
        ).update(
            views_count=(
                models.F(
                    "views_count"
                )
                + 1
            )
        )


# =============================================================================
# PRODUCT WHOLESALE TIER
# =============================================================================


class ProductWholesaleTier(BaseModel):
    """Tiered manufacturer/wholesale price breaks for bulk buyers."""

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="wholesale_tiers",
    )

    min_quantity = models.PositiveIntegerField(
        default=1,
    )

    max_quantity = models.PositiveIntegerField(
        null=True,
        blank=True,
    )

    price_per_unit = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[
            MinValueValidator(
                Decimal("0.01")
            ),
        ],
    )

    sort_order = models.PositiveIntegerField(
        default=0,
    )

    is_active = models.BooleanField(
        default=True,
    )

    class Meta:
        ordering = [
            "sort_order",
            "min_quantity",
        ]

        indexes = [
            models.Index(
                fields=[
                    "product",
                    "is_active",
                ]
            ),
            models.Index(
                fields=[
                    "min_quantity",
                ]
            ),
        ]

    def clean(self):
        if (
            self.max_quantity
            and self.max_quantity
            < self.min_quantity
        ):
            raise ValidationError(
                (
                    "Maximum quantity must be greater "
                    "than or equal to minimum quantity."
                )
            )

    def save(
        self,
        *args,
        **kwargs,
    ):
        self.clean()

        super().save(
            *args,
            **kwargs,
        )

    def __str__(self):
        maximum = (
            f"{self.max_quantity}"
            if self.max_quantity
            else "+"
        )

        return (
            f"{self.product.name}: "
            f"{self.min_quantity}-"
            f"{maximum} @ "
            f"{self.price_per_unit}"
        )


# =============================================================================
# PRODUCT ARTICLE LINK
# =============================================================================


class ProductArticleLink(BaseModel):
    """
    Attach rich editorial articles to a product with
    admin-controlled opening and reader behavior.
    """

    OPEN_BEHAVIOR_CHOICES = [
        (
            "same_page",
            "Open article in same page",
        ),
        (
            "new_page",
            "Open article in new tab",
        ),
        (
            "side_reader",
            (
                "Open beside product "
                "(same-page split reader)"
            ),
        ),
        (
            "popup",
            (
                "Legacy popup / split reader"
            ),
        ),
    ]

    READER_CONTENT_MODE_CHOICES = [
        (
            "clean_full_article",
            (
                "Full article page, cleaned "
                "for product reader"
            ),
        ),
        (
            "full_article",
            (
                "Full article page exactly "
                "as article layout"
            ),
        ),
        (
            "body_only",
            "Main article body only",
        ),
    ]

    PLACEMENT_CHOICES = [
        (
            "overview",
            "Below product overview",
        ),
        (
            "articles_tab",
            "Articles tab",
        ),
        (
            "description",
            "Description support link",
        ),
        (
            "hero",
            "Product top section",
        ),
    ]

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="article_links",
    )

    article = models.ForeignKey(
        "blog.BlogPost",
        on_delete=models.CASCADE,
        related_name="product_links",
    )

    label = models.CharField(
        max_length=120,
        blank=True,
        help_text=(
            "Optional button/card title override"
        ),
    )

    teaser = models.TextField(
        blank=True,
        help_text=(
            "Optional short teaser override"
        ),
    )

    placement = models.CharField(
        max_length=30,
        choices=PLACEMENT_CHOICES,
        default="articles_tab",
    )

    open_behavior = models.CharField(
        max_length=20,
        choices=OPEN_BEHAVIOR_CHOICES,
        default="side_reader",
        db_index=True,
        help_text=(
            "Admin controls how this article opens from "
            "the product page. Choose same page, new tab, "
            "or the B&H-style same-page split reader."
        ),
    )

    reader_content_mode = models.CharField(
        max_length=30,
        choices=READER_CONTENT_MODE_CHOICES,
        default="clean_full_article",
        help_text=(
            "Used only when Open behavior is split "
            "reader/popup. Clean full article is "
            "recommended for product pages."
        ),
    )

    reader_show_ads = models.BooleanField(
        default=False,
        help_text=(
            "Used only in split reader. Turn on if "
            "you intentionally want article ad placements "
            "inside the product reader."
        ),
    )

    reader_show_cookie_banner = models.BooleanField(
        default=False,
        help_text=(
            "Used only in split reader. Normally keep off "
            "so imported cookie banners do not cover the "
            "product page."
        ),
    )

    reader_show_chat_widgets = models.BooleanField(
        default=False,
        help_text=(
            "Used only in split reader. Normally keep off "
            "to avoid duplicate floating chat buttons."
        ),
    )

    reader_show_site_header_footer = models.BooleanField(
        default=False,
        help_text=(
            "Used only in split reader. Normally keep off "
            "because the product page already has the "
            "site header/footer."
        ),
    )

    reader_show_newsletter = models.BooleanField(
        default=True,
        help_text=(
            "Used only in split reader. Show/hide article "
            "newsletter signup blocks inside the reader."
        ),
    )

    reader_show_comments = models.BooleanField(
        default=True,
        help_text=(
            "Used only in split reader. Show/hide comments "
            "inside the reader."
        ),
    )

    sort_order = models.PositiveIntegerField(
        default=0,
    )

    is_active = models.BooleanField(
        default=True,
    )

    class Meta:
        ordering = [
            "sort_order",
            "article__published_at",
        ]

        unique_together = [
            (
                "product",
                "article",
                "placement",
            ),
        ]

        verbose_name = (
            "Product Article Link"
        )

        verbose_name_plural = (
            "Product Article Links"
        )

    def __str__(self):
        return (
            f"{self.product.name} -> "
            f"{self.article.title}"
        )

    @property
    def display_label(self):
        return (
            self.label
            or self.article.title
        )

    @property
    def display_teaser(self):
        return (
            self.teaser
            or self.article.excerpt
        )

    @property
    def article_url(self):
        return (
            self.article
            .get_absolute_url()
        )

    @property
    def article_image_url(self):
        return (
            self.article
            .display_image_url
        )

    @property
    def opens_in_side_reader(self):
        return (
            self.open_behavior
            in [
                "side_reader",
                "popup",
            ]
        )

    @property
    def opens_in_new_page(self):
        return (
            self.open_behavior
            == "new_page"
        )

    @property
    def opens_in_same_page(self):
        return (
            self.open_behavior
            == "same_page"
        )


# =============================================================================
# CATEGORY ARTICLE LINK
# =============================================================================


class CategoryArticleLink(BaseModel):
    """Attach editable editorial articles to category landing pages."""

    OPEN_BEHAVIOR_CHOICES = (
        ProductArticleLink
        .OPEN_BEHAVIOR_CHOICES
    )

    PLACEMENT_CHOICES = [
        (
            "overview",
            "Below category hero",
        ),
        (
            "guide_card",
            "Category guide card",
        ),
        (
            "articles_tab",
            "Articles section",
        ),
    ]

    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name="article_links",
    )

    article = models.ForeignKey(
        "blog.BlogPost",
        on_delete=models.CASCADE,
        related_name="category_links",
    )

    label = models.CharField(
        max_length=120,
        blank=True,
        help_text=(
            "Optional button/card title override"
        ),
    )

    teaser = models.TextField(
        blank=True,
        help_text=(
            "Optional short teaser override"
        ),
    )

    placement = models.CharField(
        max_length=30,
        choices=PLACEMENT_CHOICES,
        default="guide_card",
    )

    open_behavior = models.CharField(
        max_length=20,
        choices=OPEN_BEHAVIOR_CHOICES,
        default="same_page",
    )

    sort_order = models.PositiveIntegerField(
        default=0,
    )

    is_active = models.BooleanField(
        default=True,
    )

    class Meta:
        ordering = [
            "sort_order",
            "article__published_at",
        ]

        unique_together = [
            (
                "category",
                "article",
                "placement",
            ),
        ]

        verbose_name = (
            "Category Article Link"
        )

        verbose_name_plural = (
            "Category Article Links"
        )

        indexes = [
            models.Index(
                fields=[
                    "category",
                    "is_active",
                    "sort_order",
                ]
            ),
            models.Index(
                fields=[
                    "placement",
                    "is_active",
                ]
            ),
        ]

    def __str__(self):
        return (
            f"{self.category.name} -> "
            f"{self.article.title}"
        )

    @property
    def display_label(self):
        return (
            self.label
            or self.article.title
        )

    @property
    def display_teaser(self):
        return (
            self.teaser
            or self.article.excerpt
        )

    @property
    def article_url(self):
        return (
            self.article
            .get_absolute_url()
        )

    @property
    def article_image_url(self):
        return (
            self.article
            .display_image_url
        )


# =============================================================================
# ACCESSORY MODEL
# =============================================================================


class Accessory(BaseModel):
    """Standalone accessories/add-ons."""

    name = models.CharField(
        max_length=200,
        db_index=True,
    )

    slug = models.SlugField(
        max_length=255,
        unique=True,
        blank=True,
    )

    description = models.TextField(
        blank=True,
    )

    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[
            MinValueValidator(
                Decimal("0.01")
            ),
        ],
    )

    compare_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(
                Decimal("0.01")
            ),
        ],
    )

    image = models.ImageField(
        upload_to=ProtectedImageUploadPath(
            "accessories"
        ),
        null=True,
        blank=True,
    )

    stock_quantity = models.IntegerField(
        default=0,
        validators=[
            MinValueValidator(0),
        ],
    )

    is_active = models.BooleanField(
        default=True,
        db_index=True,
    )

    display_order = models.IntegerField(
        default=0,
    )

    class Meta:
        ordering = [
            "display_order",
            "name",
        ]

        verbose_name_plural = (
            "Accessories"
        )

        indexes = [
            models.Index(
                fields=[
                    "is_active",
                    "display_order",
                ]
            ),
        ]

    def save(
        self,
        *args,
        **kwargs,
    ):
        protect_uploaded_image(
            self,
            "image",
        )

        if not self.slug:
            self.slug = slugify(
                self.name
            )

        super().save(
            *args,
            **kwargs,
        )

        record_protected_image(
            self,
            "image",
        )

    def __str__(self):
        return (
            f"{self.name} - "
            f"${self.price}"
        )

    @property
    def discount_percent(self):
        if (
            self.compare_price
            and self.compare_price
            > self.price
        ):
            return int(
                (
                    (
                        self.compare_price
                        - self.price
                    )
                    / self.compare_price
                )
                * 100
            )

        return 0


# =============================================================================
# ACCESSORY-PRODUCT RELATIONSHIP
# =============================================================================


class AccessoryProduct(BaseModel):
    """
    Many-to-many relationship for product accessories
    with additional metadata.
    """

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="product_accessories",
    )

    accessory = models.ForeignKey(
        Accessory,
        on_delete=models.CASCADE,
        related_name="linked_products",
    )

    required = models.BooleanField(
        default=False,
        help_text=(
            "Is this accessory required?"
        ),
    )

    discount_when_bought_together = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=[
            MinValueValidator(0),
            MaxValueValidator(100),
        ],
        help_text=(
            "Discount % when bought together"
        ),
    )

    display_order = models.IntegerField(
        default=0,
    )

    class Meta:
        unique_together = [
            "product",
            "accessory",
        ]

        ordering = [
            "display_order",
        ]

        verbose_name = (
            "Product Accessory"
        )

        verbose_name_plural = (
            "Product Accessories"
        )

    def __str__(self):
        return (
            f"{self.product.name} + "
            f"{self.accessory.name}"
        )


# =============================================================================
# PRODUCT IMAGE MODEL
# =============================================================================


class ProductImage(BaseModel):
    """Product gallery images."""

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="images",
    )

    image = models.ImageField(
        upload_to=ProtectedImageUploadPath(
            "products/gallery"
        ),
        help_text=(
            "Product gallery image"
        ),
    )

    alt_text = models.CharField(
        max_length=200,
        blank=True,
        help_text=(
            "Alt text for SEO"
        ),
    )

    is_main = models.BooleanField(
        default=False,
        help_text=(
            "Set as main product image"
        ),
    )

    order = models.IntegerField(
        default=0,
    )

    class Meta:
        ordering = [
            "order",
        ]

        verbose_name = (
            "Product Image"
        )

        verbose_name_plural = (
            "Product Images"
        )

        indexes = [
            models.Index(
                fields=[
                    "product",
                    "order",
                ]
            ),
        ]

    def save(
        self,
        *args,
        **kwargs,
    ):
        protect_uploaded_image(
            self,
            "image",
        )

        if self.is_main:
            ProductImage.objects.filter(
                product=self.product,
                is_main=True,
            ).exclude(
                pk=self.pk
            ).update(
                is_main=False
            )

        super().save(
            *args,
            **kwargs,
        )

        record_protected_image(
            self,
            "image",
        )

    def __str__(self):
        return (
            f"Image for "
            f"{self.product.name}"
        )


# =============================================================================
# PRODUCT VARIANT MODEL
# =============================================================================


class ProductVariant(BaseModel):
    """Product variants (size, color, material, etc.)."""

    VARIANT_TYPES = [
        (
            "size",
            "Size",
        ),
        (
            "color",
            "Color",
        ),
        (
            "material",
            "Material",
        ),
        (
            "style",
            "Style",
        ),
        (
            "pattern",
            "Pattern",
        ),
        (
            "finish",
            "Finish",
        ),
        (
            "capacity",
            "Capacity",
        ),
        (
            "other",
            "Other",
        ),
    ]

    VARIANT_MODE_SIMPLE = "simple"
    VARIANT_MODE_FULL = "full"

    VARIANT_MODE_CHOICES = [
        (
            VARIANT_MODE_SIMPLE,
            "Simple selector variant",
        ),
        (
            VARIANT_MODE_FULL,
            "Full sellable catalog variant",
        ),
    ]

    SELECTOR_TYPE_CHOICES = [
        (
            "text",
            "Text Button",
        ),
        (
            "color",
            "Color Swatch",
        ),
        (
            "image",
            "Image Swatch",
        ),
        (
            "dropdown",
            "Dropdown",
        ),
        (
            "card",
            "Configuration Card",
        ),
    ]

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="variants",
    )

    variant_type = models.CharField(
        max_length=20,
        choices=VARIANT_TYPES,
        default="other",
    )

    name = models.CharField(
        max_length=100,
        help_text=(
            "Variant name (Size, Color, etc.)"
        ),
    )

    value = models.CharField(
        max_length=100,
        help_text=(
            "Variant value (Large, Red, etc.)"
        ),
    )

    sku = models.CharField(
        max_length=50,
        unique=True,
        blank=True,
    )

    slug = models.SlugField(
        max_length=255,
        blank=True,
        db_index=True,
        help_text=(
            "Variant URL/selector slug. "
            "Auto-generated when blank."
        ),
    )

    variant_mode = models.CharField(
        max_length=20,
        choices=VARIANT_MODE_CHOICES,
        default=VARIANT_MODE_SIMPLE,
        db_index=True,
        help_text=(
            "Simple variants inherit product content. "
            "Full variants can override content, media, "
            "warranty, SEO, and specifications."
        ),
    )

    selector_type = models.CharField(
        max_length=20,
        choices=SELECTOR_TYPE_CHOICES,
        default="text",
    )

    display_order = models.PositiveIntegerField(
        default=0,
        db_index=True,
    )

    is_default = models.BooleanField(
        default=False,
        db_index=True,
    )

    model_number = models.CharField(
        max_length=120,
        blank=True,
        db_index=True,
    )

    manufacturer_sku = models.CharField(
        max_length=120,
        blank=True,
        db_index=True,
    )

    gtin = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
    )

    upc = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
    )

    ean = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
    )

    barcode = models.CharField(
        max_length=128,
        blank=True,
        db_index=True,
    )

    short_description = models.TextField(
        blank=True,
    )

    description = models.TextField(
        blank=True,
    )

    specifications = models.TextField(
        blank=True,
    )

    key_features = models.JSONField(
        default=list,
        blank=True,
    )

    compatibility_notes = models.TextField(
        blank=True,
    )

    included_accessories = models.TextField(
        blank=True,
    )

    recommended_use = models.TextField(
        blank=True,
    )

    price_adjustment = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text=(
            "Price adjustment (positive or negative)"
        ),
    )

    stock_quantity = models.IntegerField(
        default=0,
        validators=[
            MinValueValidator(0),
        ],
    )

    image = models.ImageField(
        upload_to=ProtectedImageUploadPath(
            "products/variants"
        ),
        null=True,
        blank=True,
    )

    hover_image = models.ImageField(
        upload_to=ProtectedImageUploadPath(
            "products/variants/hover"
        ),
        null=True,
        blank=True,
    )

    manual_pdf = models.FileField(
        upload_to=(
            "products/variants/manuals/%Y/%m/"
        ),
        null=True,
        blank=True,
    )

    video_type = models.CharField(
        max_length=20,
        choices=Product.VIDEO_TYPE_CHOICES,
        default="youtube",
        blank=True,
    )

    video_url = models.URLField(
        blank=True,
    )

    local_video = models.FileField(
        upload_to=(
            "products/variants/videos/%Y/%m/"
        ),
        null=True,
        blank=True,
    )

    video_thumbnail = models.ImageField(
        upload_to=ProtectedImageUploadPath(
            "products/variants/video_thumbs"
        ),
        null=True,
        blank=True,
    )

    video_title = models.CharField(
        max_length=200,
        blank=True,
    )

    weight = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(
                Decimal("0.001")
            ),
        ],
    )

    weight_unit = models.CharField(
        max_length=10,
        choices=[
            (
                "kg",
                "Kilograms",
            ),
            (
                "lbs",
                "Pounds",
            ),
            (
                "g",
                "Grams",
            ),
            (
                "oz",
                "Ounces",
            ),
        ],
        default="kg",
    )

    dimensions_length = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(
                Decimal("0.01")
            ),
        ],
    )

    dimensions_width = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(
                Decimal("0.01")
            ),
        ],
    )

    dimensions_height = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(
                Decimal("0.01")
            ),
        ],
    )

    dimension_unit = models.CharField(
        max_length=10,
        choices=[
            (
                "cm",
                "Centimeters",
            ),
            (
                "in",
                "Inches",
            ),
            (
                "mm",
                "Millimeters",
            ),
        ],
        default="cm",
    )

    warranty_years = models.IntegerField(
        null=True,
        blank=True,
        validators=[
            MinValueValidator(0),
        ],
    )

    warranty_description = models.TextField(
        blank=True,
    )

    extended_warranty_available = models.BooleanField(
        default=False,
    )

    meta_title = models.CharField(
        max_length=200,
        blank=True,
    )

    meta_description = models.TextField(
        blank=True,
        max_length=160,
    )

    meta_keywords = models.CharField(
        max_length=200,
        blank=True,
    )

    canonical_override = models.URLField(
        blank=True,
    )

    is_indexable = models.BooleanField(
        default=True,
    )

    color_code = models.CharField(
        max_length=20,
        blank=True,
        help_text=(
            "Optional color swatch value, for example "
            "#111827 or rgb(17, 24, 39)"
        ),
    )

    is_active = models.BooleanField(
        default=True,
        db_index=True,
    )

    class Meta:
        ordering = [
            "display_order",
            "variant_type",
            "name",
            "value",
        ]

        unique_together = [
            "product",
            "name",
            "value",
        ]

        verbose_name = (
            "Product Variant"
        )

        verbose_name_plural = (
            "Product Variants"
        )

        indexes = [
            models.Index(
                fields=[
                    "product",
                    "is_active",
                ]
            ),
            models.Index(
                fields=[
                    "product",
                    "variant_mode",
                    "is_active",
                ]
            ),
            models.Index(
                fields=[
                    "product",
                    "slug",
                ]
            ),
        ]

    def save(
        self,
        *args,
        **kwargs,
    ):
        protect_uploaded_image(
            self,
            "image",
        )

        protect_uploaded_image(
            self,
            "hover_image",
        )

        protect_uploaded_image(
            self,
            "video_thumbnail",
        )

        if not self.sku:
            self.sku = (
                self._generate_variant_sku()
            )

        if not self.slug:
            self.slug = (
                self._generate_variant_slug()
            )

        if self.is_default:
            ProductVariant.objects.filter(
                product=self.product,
                is_default=True,
            ).exclude(
                pk=self.pk
            ).update(
                is_default=False
            )

        super().save(
            *args,
            **kwargs,
        )

        record_protected_image(
            self,
            "image",
        )

        record_protected_image(
            self,
            "hover_image",
        )

        record_protected_image(
            self,
            "video_thumbnail",
        )

    def _generate_variant_sku(self):
        base_sku = (
            f"{self.product.sku}-"
            f"{self.name[:2]}"
            f"{self.value[:2]}"
        ).upper()

        base_sku = "".join(
            character
            for character
            in base_sku
            if (
                character.isalnum()
                or character == "-"
            )
        )

        random_suffix = "".join(
            random.choices(
                string.digits,
                k=6,
            )
        )

        sku = (
            f"{base_sku}-"
            f"{random_suffix}"
        )

        while ProductVariant.objects.filter(
            sku=sku
        ).exists():
            random_suffix = "".join(
                random.choices(
                    string.digits,
                    k=6,
                )
            )

            sku = (
                f"{base_sku}-"
                f"{random_suffix}"
            )

        return sku

    def _generate_variant_slug(self):
        base = (
            slugify(
                f"{self.name}-{self.value}"
            )
            or slugify(
                self.sku
            )
            or "variant"
        )

        base = (
            base[:240]
            .strip("-")
            or "variant"
        )

        queryset = (
            ProductVariant.objects
            .filter(
                product=self.product
            )
        )

        if self.pk:
            queryset = queryset.exclude(
                pk=self.pk
            )

        candidate = base
        counter = 2

        while queryset.filter(
            slug=candidate
        ).exists():
            suffix = (
                f"-{counter}"
            )

            candidate = (
                f"{base[:max(1, 255 - len(suffix))]}"
                f"{suffix}"
            ).strip("-")

            counter += 1

        return candidate

    def __str__(self):
        return (
            f"{self.product.name} - "
            f"{self.name}: "
            f"{self.value}"
        )

    @property
    def final_price(self):
        return (
            self.product.price
            + self.price_adjustment
        )

    @property
    def is_available(self):
        return (
            self.is_active
            and self.stock_quantity
            > 0
        )


# =============================================================================
# PRODUCT VARIANT SPECIFICATION
# =============================================================================


class ProductVariantSpecification(BaseModel):
    """
    Structured specifications that can override or extend
    product-level specifications.
    """

    variant = models.ForeignKey(
        ProductVariant,
        on_delete=models.CASCADE,
        related_name="structured_specs",
    )

    group = models.CharField(
        max_length=120,
        blank=True,
        help_text=(
            "Example: Display, Audio, Connectivity."
        ),
    )

    name = models.CharField(
        max_length=160,
    )

    value = models.TextField()

    unit = models.CharField(
        max_length=40,
        blank=True,
    )

    display_order = models.PositiveIntegerField(
        default=0,
    )

    is_highlight = models.BooleanField(
        default=False,
    )

    class Meta:
        ordering = [
            "display_order",
            "group",
            "name",
        ]

        indexes = [
            models.Index(
                fields=[
                    "variant",
                    "display_order",
                ]
            ),
            models.Index(
                fields=[
                    "variant",
                    "is_highlight",
                ]
            ),
        ]

    def __str__(self):
        return (
            f"{self.variant} - "
            f"{self.name}: "
            f"{self.value}"
        )


# =============================================================================
# PRODUCT VARIANT IMAGE
# =============================================================================


class ProductVariantImage(BaseModel):
    """Multiple images per variant."""

    variant = models.ForeignKey(
        ProductVariant,
        on_delete=models.CASCADE,
        related_name="images",
    )

    image = models.ImageField(
        upload_to=ProtectedImageUploadPath(
            "products/variants/gallery"
        )
    )

    IMAGE_TYPE_CHOICES = [
        (
            "gallery",
            "Gallery",
        ),
        (
            "swatch",
            "Selector Swatch",
        ),
        (
            "packaging",
            "Packaging",
        ),
        (
            "lifestyle",
            "Lifestyle",
        ),
        (
            "diagram",
            "Diagram / Spec",
        ),
        (
            "certificate",
            "Certificate",
        ),
        (
            "other",
            "Other",
        ),
    ]

    image_type = models.CharField(
        max_length=30,
        choices=IMAGE_TYPE_CHOICES,
        default="gallery",
    )

    title = models.CharField(
        max_length=160,
        blank=True,
    )

    alt_text = models.CharField(
        max_length=200,
        blank=True,
    )

    order = models.IntegerField(
        default=0,
    )

    sort_order = models.PositiveIntegerField(
        default=0,
    )

    is_main = models.BooleanField(
        default=False,
    )

    is_primary = models.BooleanField(
        default=False,
    )

    is_active = models.BooleanField(
        default=True,
        db_index=True,
    )

    class Meta:
        ordering = [
            "sort_order",
            "order",
        ]

        verbose_name = (
            "Variant Image"
        )

        verbose_name_plural = (
            "Variant Images"
        )

        indexes = [
            models.Index(
                fields=[
                    "variant",
                    "is_active",
                    "sort_order",
                ]
            ),
            models.Index(
                fields=[
                    "variant",
                    "image_type",
                ]
            ),
        ]

    def save(
        self,
        *args,
        **kwargs,
    ):
        protect_uploaded_image(
            self,
            "image",
        )

        if self.is_primary:
            self.is_main = True

        if self.is_main:
            self.is_primary = True

            ProductVariantImage.objects.filter(
                variant=self.variant,
                is_main=True,
            ).exclude(
                pk=self.pk
            ).update(
                is_main=False
            )

            ProductVariantImage.objects.filter(
                variant=self.variant,
                is_primary=True,
            ).exclude(
                pk=self.pk
            ).update(
                is_primary=False
            )

        super().save(
            *args,
            **kwargs,
        )

        record_protected_image(
            self,
            "image",
        )


# =============================================================================
# VENDOR PRODUCT OFFER
# =============================================================================


class VendorProductOffer(BaseModel):
    """Vendor-owned sellable offer for a shared catalog product/variant."""

    STATUS_DRAFT = "draft"
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_SUSPENDED = "suspended"

    STATUS_CHOICES = [
        (
            STATUS_DRAFT,
            "Draft",
        ),
        (
            STATUS_PENDING,
            "Pending Review",
        ),
        (
            STATUS_APPROVED,
            "Approved / Live",
        ),
        (
            STATUS_REJECTED,
            "Rejected",
        ),
        (
            STATUS_SUSPENDED,
            "Suspended",
        ),
    ]

    FULFILMENT_CHOICES = [
        (
            "vendor",
            "Vendor Fulfilled",
        ),
        (
            "arolana",
            "Arolana Fulfilled",
        ),
        (
            "dropship",
            "Dropship",
        ),
        (
            "pickup",
            "Pickup Only",
        ),
    ]

    vendor = models.ForeignKey(
        "vendors.VendorProfile",
        on_delete=models.CASCADE,
        related_name="product_offers",
    )

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="vendor_offers",
    )

    variant = models.ForeignKey(
        ProductVariant,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="vendor_offers",
    )

    seller_sku = models.CharField(
        max_length=120,
        blank=True,
        db_index=True,
    )

    price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[
            MinValueValidator(
                Decimal("0.01")
            ),
        ],
    )

    sale_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(
                Decimal("0.01")
            ),
        ],
    )

    currency = models.CharField(
        max_length=10,
        default="NGN",
    )

    stock_quantity = models.PositiveIntegerField(
        default=0,
    )

    reserved_quantity = models.PositiveIntegerField(
        default=0,
    )

    condition = models.CharField(
        max_length=30,
        choices=Product.PRODUCT_CONDITION_CHOICES,
        default=Product.CONDITION_BRAND_NEW,
    )

    seller_warranty = models.TextField(
        blank=True,
    )

    return_policy = models.TextField(
        blank=True,
    )

    delivery_note = models.TextField(
        blank=True,
    )

    lead_time_days = models.PositiveIntegerField(
        null=True,
        blank=True,
    )

    fulfilment_method = models.CharField(
        max_length=20,
        choices=FULFILMENT_CHOICES,
        default="vendor",
    )

    approval_status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
    )

    approval_notes = models.TextField(
        blank=True,
    )

    is_featured = models.BooleanField(
        default=False,
        db_index=True,
    )

    is_preferred = models.BooleanField(
        default=False,
        db_index=True,
    )

    is_active = models.BooleanField(
        default=True,
        db_index=True,
    )

    class Meta:
        ordering = [
            "-is_preferred",
            "-is_featured",
            "price",
            "-created_at",
        ]

        indexes = [
            models.Index(
                fields=[
                    "vendor",
                    "is_active",
                    "approval_status",
                ]
            ),
            models.Index(
                fields=[
                    "product",
                    "is_active",
                    "approval_status",
                ]
            ),
            models.Index(
                fields=[
                    "variant",
                    "is_active",
                    "approval_status",
                ]
            ),
            models.Index(
                fields=[
                    "condition",
                ]
            ),
        ]

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "vendor",
                    "product",
                    "variant",
                    "seller_sku",
                ],
                name=(
                    "unique_vendor_offer_sku_per_catalog_item"
                ),
            ),
        ]

    def clean(self):
        if (
            self.variant_id
            and self.product_id
            and self.variant.product_id
            != self.product_id
        ):
            raise ValidationError(
                {
                    "variant": (
                        "Selected variant does not belong "
                        "to this product."
                    ),
                }
            )

        if (
            self.sale_price
            and self.sale_price
            >= self.price
        ):
            raise ValidationError(
                {
                    "sale_price": (
                        "Sale price must be lower "
                        "than normal price."
                    ),
                }
            )

    def save(
        self,
        *args,
        **kwargs,
    ):
        self.clean()

        if not self.seller_sku:
            base = (
                self.variant.sku
                if self.variant_id
                else self.product.sku
            )

            self.seller_sku = (
                f"{base}-{self.vendor_id}"
                .strip("-")
            )

        super().save(
            *args,
            **kwargs,
        )

    @property
    def final_price(self):
        return (
            self.sale_price
            or self.price
        )

    @property
    def available_stock(self):
        return max(
            (
                int(
                    self.stock_quantity
                    or 0
                )
                - int(
                    self.reserved_quantity
                    or 0
                )
            ),
            0,
        )

    @property
    def is_available(self):
        return (
            self.is_active
            and self.approval_status
            == self.STATUS_APPROVED
            and self.available_stock
            > 0
        )

    @property
    def display_name(self):
        if self.variant_id:
            return (
                f"{self.product.name} - "
                f"{self.variant.value}"
            )

        return self.product.name

    @property
    def vendor_display_name(self):
        return (
            self.vendor.display_name
            if self.vendor_id
            else "Arolana Vendor"
        )

    def __str__(self):
        return (
            f"{self.vendor_display_name} offer: "
            f"{self.display_name}"
        )


# =============================================================================
# PRODUCT CATALOG REQUEST
# =============================================================================


class ProductCatalogRequest(BaseModel):
    REQUEST_NEW_PRODUCT = "new_product"
    REQUEST_NEW_VARIANT = "new_variant"

    REQUEST_CHOICES = [
        (
            REQUEST_NEW_PRODUCT,
            "New catalog product",
        ),
        (
            REQUEST_NEW_VARIANT,
            "Missing product variant",
        ),
    ]

    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_NEEDS_INFO = "needs_info"

    STATUS_CHOICES = [
        (
            STATUS_PENDING,
            "Pending review",
        ),
        (
            STATUS_APPROVED,
            "Approved",
        ),
        (
            STATUS_REJECTED,
            "Rejected",
        ),
        (
            STATUS_NEEDS_INFO,
            "Needs more information",
        ),
    ]

    vendor = models.ForeignKey(
        "vendors.VendorProfile",
        on_delete=models.CASCADE,
        related_name="catalog_requests",
    )

    requested_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="product_catalog_requests",
    )

    request_type = models.CharField(
        max_length=24,
        choices=REQUEST_CHOICES,
        db_index=True,
    )

    product = models.ForeignKey(
        Product,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="catalog_requests",
    )

    resulting_product = models.ForeignKey(
        Product,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_catalog_requests",
    )

    resulting_variant = models.ForeignKey(
        ProductVariant,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_catalog_requests",
    )

    title = models.CharField(
        max_length=255,
    )

    brand_name = models.CharField(
        max_length=120,
        blank=True,
    )

    model_number = models.CharField(
        max_length=120,
        blank=True,
    )

    manufacturer_sku = models.CharField(
        max_length=120,
        blank=True,
    )

    gtin = models.CharField(
        max_length=64,
        blank=True,
    )

    upc = models.CharField(
        max_length=64,
        blank=True,
    )

    ean = models.CharField(
        max_length=64,
        blank=True,
    )

    barcode = models.CharField(
        max_length=128,
        blank=True,
    )

    requested_attributes = models.JSONField(
        default=dict,
        blank=True,
    )

    description = models.TextField(
        blank=True,
    )

    vendor_note = models.TextField(
        blank=True,
    )

    status = models.CharField(
        max_length=24,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
    )

    admin_notes = models.TextField(
        blank=True,
    )

    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_product_catalog_requests",
    )

    reviewed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    class Meta:
        ordering = [
            "-created_at",
        ]

        indexes = [
            models.Index(
                fields=[
                    "vendor",
                    "status",
                    "-created_at",
                ]
            ),
            models.Index(
                fields=[
                    "request_type",
                    "status",
                ]
            ),
            models.Index(
                fields=[
                    "product",
                    "status",
                ]
            ),
        ]

    def clean(self):
        if (
            self.request_type
            == self.REQUEST_NEW_VARIANT
            and not self.product_id
        ):
            raise ValidationError(
                {
                    "product": (
                        "Choose the existing catalog product "
                        "that needs this new variant."
                    ),
                }
            )

    def mark_reviewed(
        self,
        status,
        user=None,
        notes="",
    ):
        self.status = status

        self.reviewed_by = (
            user
        )

        self.reviewed_at = (
            now()
        )

        if notes:
            self.admin_notes = (
                notes
            )

        self.save(
            update_fields=[
                "status",
                "reviewed_by",
                "reviewed_at",
                "admin_notes",
                "updated_at",
            ]
        )

    def __str__(self):
        return (
            f"{self.get_request_type_display()} - "
            f"{self.title}"
        )


# =============================================================================
# PRODUCT DETAIL SECTION
# =============================================================================


class ProductDetailSection(BaseModel):
    """Admin-managed product detail sections shared by web and mobile."""

    SECTION_CHOICES = [
        (
            "overview",
            "Overview",
        ),
        (
            "specifications",
            "Specifications",
        ),
        (
            "variants",
            "Variants",
        ),
        (
            "wholesale_pricing",
            "Wholesale Pricing",
        ),
        (
            "moq",
            "MOQ",
        ),
        (
            "product_images",
            "Product Images",
        ),
        (
            "videos",
            "Videos",
        ),
        (
            "brochure",
            "PDF Brochure / Manual",
        ),
        (
            "certifications",
            "Certifications",
        ),
        (
            "accessories",
            "Accessories",
        ),
        (
            "frequently_bought_together",
            "Frequently Bought Together",
        ),
        (
            "related_products",
            "Related Products",
        ),
        (
            "reviews",
            "Reviews",
        ),
        (
            "qa",
            "Q&A",
        ),
        (
            "shipping",
            "Shipping",
        ),
        (
            "warranty",
            "Warranty",
        ),
        (
            "vendor_profile",
            "Vendor / Manufacturer Profile",
        ),
        (
            "factory_details",
            "Factory Details",
        ),
        (
            "rfq",
            "RFQ",
        ),
        (
            "recently_viewed",
            "Recently Viewed",
        ),
        (
            "recommended_products",
            "Recommended Products",
        ),
    ]

    key = models.CharField(
        max_length=60,
        choices=SECTION_CHOICES,
        unique=True,
    )

    title = models.CharField(
        max_length=120,
    )

    is_enabled = models.BooleanField(
        default=True,
        db_index=True,
    )

    display_order = models.IntegerField(
        default=0,
    )

    mobile_enabled = models.BooleanField(
        default=True,
    )

    web_enabled = models.BooleanField(
        default=True,
    )

    class Meta:
        ordering = [
            "display_order",
            "title",
        ]

        verbose_name = (
            "Product Detail Section"
        )

        verbose_name_plural = (
            "Product Detail Sections"
        )

    def __str__(self):
        return self.title


# =============================================================================
# PRODUCT DETAIL FIELD CONFIG
# =============================================================================


class ProductDetailFieldConfig(BaseModel):
    """
    Admin-managed product form/detail field visibility
    shared by web and mobile.
    """

    FIELD_CHOICES = [
        (
            "brand",
            "Brand",
        ),
        (
            "model_number",
            "Model Number",
        ),
        (
            "sku",
            "SKU",
        ),
        (
            "manufacturer_sku",
            "Manufacturer SKU",
        ),
        (
            "condition",
            "Product Condition",
        ),
        (
            "category",
            "Category",
        ),
        (
            "subcategory",
            "Subcategory",
        ),
        (
            "minimum_order_quantity",
            "MOQ",
        ),
        (
            "price",
            "Retail Price",
        ),
        (
            "wholesale_price",
            "Wholesale Price",
        ),
        (
            "bulk_price",
            "Bulk Price",
        ),
        (
            "stock_quantity",
            "Stock Quantity",
        ),
        (
            "country_of_origin",
            "Country of Origin",
        ),
        (
            "lead_time_days",
            "Lead Time",
        ),
        (
            "warranty",
            "Warranty",
        ),
        (
            "shipping_weight",
            "Shipping Weight",
        ),
        (
            "package_dimensions",
            "Package Dimensions",
        ),
        (
            "video_type",
            "Video Type",
        ),
        (
            "youtube_url",
            "YouTube URL",
        ),
        (
            "local_video",
            "Local Video",
        ),
        (
            "manufacturer_address",
            "Manufacturer Address",
        ),
        (
            "description",
            "Description",
        ),
        (
            "specifications",
            "Specifications",
        ),
        (
            "certifications",
            "Certifications",
        ),
        (
            "accessories",
            "Accessories",
        ),
        (
            "manual_pdf",
            "PDF Brochure",
        ),
        (
            "images",
            "Images",
        ),
        (
            "variants",
            "Variants",
        ),
    ]

    key = models.CharField(
        max_length=80,
        choices=FIELD_CHOICES,
        unique=True,
    )

    label = models.CharField(
        max_length=120,
    )

    is_enabled = models.BooleanField(
        default=True,
        db_index=True,
    )

    is_required = models.BooleanField(
        default=False,
    )

    display_order = models.IntegerField(
        default=0,
    )

    help_text = models.CharField(
        max_length=255,
        blank=True,
    )

    class Meta:
        ordering = [
            "display_order",
            "label",
        ]

        verbose_name = (
            "Product Detail Field Config"
        )

        verbose_name_plural = (
            "Product Detail Field Configs"
        )

    def __str__(self):
        return self.label


# =============================================================================
# PRODUCT VARIANT TYPE CONFIG
# =============================================================================


class ProductVariantTypeConfig(BaseModel):
    """Admin-managed variant types used by product forms and detail pages."""

    key = models.CharField(
        max_length=40,
        unique=True,
    )

    label = models.CharField(
        max_length=80,
    )

    display_order = models.IntegerField(
        default=0,
    )

    is_active = models.BooleanField(
        default=True,
    )

    class Meta:
        ordering = [
            "display_order",
            "label",
        ]

        verbose_name = (
            "Product Variant Type"
        )

        verbose_name_plural = (
            "Product Variant Types"
        )

    def __str__(self):
        return self.label


# =============================================================================
# PRODUCT VIDEO MODEL
# =============================================================================


class ProductVideo(BaseModel):
    """Multiple public videos per product."""

    VIDEO_SOURCE_CHOICES = [
        (
            "youtube",
            "YouTube",
        ),
        (
            "vimeo",
            "Vimeo",
        ),
        (
            "local",
            "Local Video",
        ),
    ]

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="additional_videos",
    )

    title = models.CharField(
        max_length=200,
        blank=True,
    )

    description = models.TextField(
        blank=True,
    )

    source = models.CharField(
        max_length=20,
        choices=VIDEO_SOURCE_CHOICES,
        default="youtube",
    )

    youtube_url = models.URLField(
        blank=True,
        help_text="YouTube video URL",
    )

    vimeo_url = models.URLField(
        blank=True,
        help_text="Vimeo video URL",
    )

    local_video = models.FileField(
        upload_to=(
            "products/videos/additional/%Y/%m/"
        ),
        null=True,
        blank=True,
        help_text=(
            "MP4, WebM, or Ogg format"
        ),
    )

    thumbnail = models.ImageField(
        upload_to=ProtectedImageUploadPath(
            "products/video_thumbs/additional"
        ),
        null=True,
        blank=True,
    )

    is_main = models.BooleanField(
        default=False,
    )

    display_order = models.IntegerField(
        default=0,
    )

    # Arolana vendor short-video commerce fields. Existing legacy videos can
    # remain vendor-less, while vendor-submitted videos use moderation.
    vendor = models.ForeignKey(
        "vendors.VendorProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="product_videos",
    )

    moderation_status = models.CharField(
        max_length=20,
        choices=(
            ("pending", "Pending"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
        ),
        default="approved",
        db_index=True,
    )

    moderation_note = models.TextField(
        blank=True,
    )

    approved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_product_videos",
    )

    approved_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    duration_seconds = models.PositiveIntegerField(
        default=0,
    )

    views_count = models.PositiveIntegerField(
        default=0,
    )

    product_clicks = models.PositiveIntegerField(
        default=0,
    )

    helpful_count = models.PositiveIntegerField(
        default=0,
    )

    rating_sum = models.PositiveIntegerField(
        default=0,
    )

    rating_count = models.PositiveIntegerField(
        default=0,
    )

    @property
    def average_rating(self):
        if not self.rating_count:
            return 0
        return round(
            self.rating_sum / self.rating_count,
            1,
        )

    class Meta:
        ordering = [
            "display_order",
        ]

        verbose_name = (
            "Product Video"
        )

        verbose_name_plural = (
            "Product Videos"
        )

    def save(
        self,
        *args,
        **kwargs,
    ):
        protect_uploaded_image(
            self,
            "thumbnail",
        )

        super().save(
            *args,
            **kwargs,
        )

        record_protected_image(
            self,
            "thumbnail",
        )

    def __str__(self):
        return (
            f"{self.product.name} - "
            f"{self.title or 'Video'}"
        )

    def get_embed_url(self):
        if (
            self.source
            == "youtube"
            and self.youtube_url
        ):
            return (
                Product._extract_youtube_embed(
                    self.youtube_url
                )
            )

        if (
            self.source
            == "vimeo"
            and self.vimeo_url
        ):
            return (
                Product._extract_vimeo_embed(
                    self.vimeo_url
                )
            )

        if (
            self.source
            == "local"
            and self.local_video
        ):
            return (
                self.local_video.url
            )

        return None

    @property
    def is_local_video(self):
        return (
            self.source
            == "local"
            and bool(
                self.local_video
            )
        )

    @property
    def is_external_video(self):
        return (
            self.source
            in [
                "youtube",
                "vimeo",
            ]
            and bool(
                self.get_embed_url()
            )
        )


# =============================================================================
# PRODUCT REVIEW MODEL
# =============================================================================


class ProductReview(BaseModel):
    """
    Customer product reviews with rich media support.

    Customer review videos are private/user-submitted media and use the
    review video upload validator.
    """

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="reviews",
        db_index=True,
    )

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="product_reviews",
    )

    rating = models.IntegerField(
        choices=[
            (
                i,
                f"{i} Star{'s' if i > 1 else ''}",
            )
            for i
            in range(
                1,
                6,
            )
        ],
        validators=[
            MinValueValidator(1),
            MaxValueValidator(5),
        ],
    )

    title = models.CharField(
        max_length=200,
        help_text="Review title",
    )

    review = models.TextField(
        help_text=(
            "Your detailed review"
        ),
    )

    verified_purchase = models.BooleanField(
        default=False,
        db_index=True,
    )

    helpful_count = models.IntegerField(
        default=0,
        validators=[
            MinValueValidator(0),
        ],
    )

    unhelpful_count = models.IntegerField(
        default=0,
        validators=[
            MinValueValidator(0),
        ],
    )

    video_review = models.FileField(
        upload_to="reviews/videos/%Y/%m/",
        null=True,
        blank=True,
        validators=[
            validate_review_video_upload,
        ],
        help_text=(
            "Optional review video. "
            "MP4 or WebM only."
        ),
    )

    review_video_converted = models.FileField(
        upload_to="reviews/videos/converted/%Y/%m/",
        blank=True,
        null=True,
        help_text=(
            "Browser-compatible H.264/AAC MP4 generated automatically "
            "from the customer upload."
        ),
    )

    review_video_conversion_status = models.CharField(
        max_length=20,
        choices=(
            ("none", "No video"),
            ("pending", "Pending"),
            ("processing", "Processing"),
            ("completed", "Completed"),
            ("failed", "Failed"),
        ),
        default="none",
        db_index=True,
    )

    review_video_conversion_error = models.TextField(
        blank=True,
    )

    review_video_converted_at = models.DateTimeField(
        blank=True,
        null=True,
    )

    class Meta:
        unique_together = [
            "product",
            "user",
        ]

        ordering = [
            "-created_at",
        ]

        indexes = [
            models.Index(
                fields=[
                    "product",
                    "-created_at",
                ]
            ),
            models.Index(
                fields=[
                    "user",
                    "-created_at",
                ]
            ),
            models.Index(
                fields=[
                    "rating",
                ]
            ),
            models.Index(
                fields=[
                    "verified_purchase",
                    "-helpful_count",
                ]
            ),
        ]

    def __str__(self):
        return (
            f"{self.user.username} - "
            f"{self.product.name} - "
            f"{self.rating}★"
        )

    def helpful_ratio(self):
        total = (
            self.helpful_count
            + self.unhelpful_count
        )

        return (
            self.helpful_count
            / total
            * 100
        ) if total > 0 else 0



class ProductVideoRating(BaseModel):
    """A customer's rating of a seller product video, separate from product reviews."""
    video = models.ForeignKey(ProductVideo, on_delete=models.CASCADE, related_name="ratings")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="product_video_ratings")
    rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    helpful = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["video", "user"], name="unique_product_video_rating_user")
        ]

    def __str__(self):
        return f"{self.video_id} - {self.user_id} - {self.rating}★"


class ProductVideoComment(BaseModel):
    """One editable customer comment per seller product video."""

    video = models.ForeignKey(
        ProductVideo,
        on_delete=models.CASCADE,
        related_name="comments",
    )

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="product_video_comments",
    )

    body = models.TextField(
        max_length=1500,
    )

    is_visible = models.BooleanField(
        default=True,
        db_index=True,
    )

    is_edited = models.BooleanField(
        default=False,
    )

    moderated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="moderated_product_video_comments",
    )

    moderated_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["video", "user"],
                name="unique_product_video_comment_user",
            )
        ]
        indexes = [
            models.Index(fields=["video", "is_visible", "-created_at"]),
        ]

    def __str__(self):
        return f"Video {self.video_id} comment by {self.user_id}"


# =============================================================================
# PRODUCT Q&A MODEL
# =============================================================================


class ProductQuestion(BaseModel):
    """Product Q&A system."""

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="questions",
    )

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="product_questions",
    )

    question = models.TextField()

    answer = models.TextField(
        blank=True,
        null=True,
    )

    answered_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="answered_product_questions",
    )

    answered_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    helpful_count = models.IntegerField(
        default=0,
        validators=[
            MinValueValidator(0),
        ],
    )

    is_public = models.BooleanField(
        default=True,
        db_index=True,
    )

    class Meta:
        ordering = [
            "-created_at",
        ]

        verbose_name = (
            "Product Question"
        )

        verbose_name_plural = (
            "Product Questions"
        )

        indexes = [
            models.Index(
                fields=[
                    "product",
                    "is_public",
                ]
            ),
            models.Index(
                fields=[
                    "user",
                    "-created_at",
                ]
            ),
        ]

    def __str__(self):
        return (
            f"Q: {self.question[:50]}..."
        )

    def is_answered(self):
        return bool(
            self.answer
            and self.answered_at
        )

    def mark_as_answered(
        self,
        user,
        answer_text,
    ):
        self.answer = (
            answer_text
        )

        self.answered_by = (
            user
        )

        self.answered_at = (
            now()
        )

        self.save()


# =============================================================================
# RECENTLY VIEWED
# =============================================================================


class RecentlyViewed(BaseModel):
    """Track recently viewed products."""

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="recently_viewed",
    )

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="recently_viewed_by",
    )

    viewed_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = [
            "-viewed_at",
        ]

        unique_together = [
            "user",
            "product",
        ]

        indexes = [
            models.Index(
                fields=[
                    "user",
                    "-viewed_at",
                ]
            ),
        ]

    def __str__(self):
        return (
            f"{self.user.username} viewed "
            f"{self.product.name}"
        )


# =============================================================================
# WISHLIST
# =============================================================================


class Wishlist(BaseModel):
    """User wishlist."""

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="wishlist_items",
    )

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="in_wishlists",
    )

    added_at = models.DateTimeField(
        auto_now_add=True,
        null=True,
        blank=True,
    )

    class Meta:
        unique_together = [
            "user",
            "product",
        ]

        ordering = [
            "-added_at",
        ]

        indexes = [
            models.Index(
                fields=[
                    "user",
                    "-added_at",
                ]
            ),
        ]

    def __str__(self):
        return (
            f"{self.user.username} - "
            f"{self.product.name}"
        )


# =============================================================================
# MANUFACTURER WARRANTY
# =============================================================================


class ManufacturerWarranty(BaseModel):
    """Manufacturer warranty information."""

    product = models.OneToOneField(
        Product,
        on_delete=models.CASCADE,
        related_name="manufacturer_warranty",
    )

    provider = models.CharField(
        max_length=200,
        help_text=(
            "Warranty provider name"
        ),
    )

    duration_years = models.IntegerField(
        default=1,
        validators=[
            MinValueValidator(0),
        ],
    )

    duration_months = models.IntegerField(
        default=0,
        validators=[
            MinValueValidator(0),
            MaxValueValidator(11),
        ],
    )

    coverage_details = models.TextField(
        blank=True,
        help_text=(
            "What's covered"
        ),
    )

    exclusions = models.TextField(
        blank=True,
        help_text=(
            "What's not covered"
        ),
    )

    terms_url = models.URLField(
        blank=True,
        help_text=(
            "Link to warranty terms"
        ),
    )

    registration_required = models.BooleanField(
        default=False,
    )

    registration_url = models.URLField(
        blank=True,
        help_text=(
            "Warranty registration URL"
        ),
    )

    customer_support_phone = models.CharField(
        max_length=50,
        blank=True,
    )

    customer_support_email = models.EmailField(
        blank=True,
    )

    class Meta:
        verbose_name = (
            "Manufacturer Warranty"
        )

        verbose_name_plural = (
            "Manufacturer Warranties"
        )

    def __str__(self):
        return (
            f"Warranty for "
            f"{self.product.name}"
        )

    def duration_text(self):
        if (
            self.duration_years
            and self.duration_months
        ):
            return (
                f"{self.duration_years} "
                f"year{'s' if self.duration_years > 1 else ''} "
                f"{self.duration_months} "
                f"month{'s' if self.duration_months > 1 else ''}"
            )

        if self.duration_years:
            return (
                f"{self.duration_years} "
                f"year{'s' if self.duration_years > 1 else ''}"
            )

        if self.duration_months:
            return (
                f"{self.duration_months} "
                f"month{'s' if self.duration_months > 1 else ''}"
            )

        return "No warranty"


# =============================================================================
# SHIPPING INFO
# =============================================================================


class ShippingInfo(BaseModel):
    """Product shipping information."""

    product = models.OneToOneField(
        Product,
        on_delete=models.CASCADE,
        related_name="shipping_info",
    )

    weight_shipping = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(
                Decimal("0.001")
            ),
        ],
        help_text=(
            "Shipping weight (kg/lbs)"
        ),
    )

    dimensions_package = models.CharField(
        max_length=100,
        blank=True,
        help_text=(
            "Package dimensions (L×W×H)"
        ),
    )

    shipping_restrictions = models.TextField(
        blank=True,
        help_text=(
            "Shipping restrictions or special handling notes"
        ),
    )

    hazmat = models.BooleanField(
        default=False,
        help_text=(
            "Is this a hazardous material?"
        ),
    )

    free_shipping = models.BooleanField(
        default=False,
    )

    estimated_delivery_days_min = models.IntegerField(
        default=3,
        validators=[
            MinValueValidator(1),
        ],
    )

    estimated_delivery_days_max = models.IntegerField(
        default=7,
        validators=[
            MinValueValidator(1),
        ],
    )

    class Meta:
        verbose_name = (
            "Shipping Information"
        )

        verbose_name_plural = (
            "Shipping Information"
        )

    def __str__(self):
        return (
            f"Shipping info for "
            f"{self.product.name}"
        )

    def delivery_estimate(self):
        if (
            self.estimated_delivery_days_min
            == self.estimated_delivery_days_max
        ):
            return (
                f"{self.estimated_delivery_days_min} days"
            )

        return (
            f"{self.estimated_delivery_days_min}-"
            f"{self.estimated_delivery_days_max} days"
        )


# =============================================================================
# REVIEW VIDEO MODEL
# =============================================================================


class ReviewVideo(BaseModel):
    """
    Customer review videos.

    Review video files and generated/customer thumbnails are private
    user-submitted media and use the private upload validators.
    """

    review = models.ForeignKey(
        ProductReview,
        on_delete=models.CASCADE,
        related_name="review_videos",
    )

    title = models.CharField(
        max_length=200,
        blank=True,
    )

    video_file = models.FileField(
        upload_to="reviews/videos/%Y/%m/",
        null=True,
        blank=True,
        validators=[
            validate_review_video_upload,
        ],
        help_text=(
            "Upload customer review video. "
            "MP4, WebM, MOV or M4V."
        ),
    )

    thumbnail = models.ImageField(
        upload_to=ProtectedImageUploadPath(
            "reviews/thumbs"
        ),
        null=True,
        blank=True,
        validators=[
            validate_private_profile_image_upload,
        ],
    )

    is_main = models.BooleanField(
        default=False,
    )

    class Meta:
        ordering = [
            "-created_at",
        ]

    def save(
        self,
        *args,
        **kwargs,
    ):
        protect_uploaded_image(
            self,
            "thumbnail",
        )

        super().save(
            *args,
            **kwargs,
        )

        record_protected_image(
            self,
            "thumbnail",
        )

    def __str__(self):
        return (
            "Review video for "
            f"{self.review.product.name}"
        )


# =============================================================================
# PRODUCT LISTING BANNER
# =============================================================================


class ProductListingBanner(BaseModel):
    """Admin-editable banner for the main products listing page."""

    PLACEMENT_CHOICES = [
        (
            "products_list",
            "Products List Page",
        ),
    ]

    title = models.CharField(
        max_length=160,
        default=(
            "Discover the future of shopping"
        ),
    )

    subtitle = models.TextField(
        blank=True,
        default=(
            "Explore trusted products from verified vendors, "
            "compare prices, filter faster, and shop with a "
            "premium marketplace experience built for every screen."
        ),
    )

    eyebrow = models.CharField(
        max_length=80,
        default=(
            "Arolana Marketplace"
        ),
    )

    placement = models.CharField(
        max_length=40,
        choices=PLACEMENT_CHOICES,
        default="products_list",
        db_index=True,
    )

    background_image = models.ImageField(
        upload_to=ProtectedImageUploadPath(
            "products/listing_banners"
        ),
        blank=True,
        null=True,
        help_text=(
            "Main banner background image. "
            "Recommended: 1920x700."
        ),
    )

    side_image = models.ImageField(
        upload_to=ProtectedImageUploadPath(
            "products/listing_banners/side"
        ),
        blank=True,
        null=True,
        help_text=(
            "Optional floating side image/icon "
            "for desktop."
        ),
    )

    cta_text = models.CharField(
        max_length=80,
        blank=True,
        default="Start shopping",
    )

    cta_link = models.CharField(
        max_length=255,
        blank=True,
        default="#products-section",
    )

    cta_background_color = models.CharField(
        max_length=20,
        blank=True,
        default="",
        help_text=(
            "Optional CTA button background color."
        ),
    )

    cta_text_color = models.CharField(
        max_length=20,
        blank=True,
        default="",
        help_text=(
            "Optional CTA button text color."
        ),
    )

    show_eyebrow = models.BooleanField(
        default=True,
        help_text=(
            "Show the banner eyebrow label."
        ),
    )

    show_title = models.BooleanField(
        default=True,
        help_text=(
            "Show the banner title."
        ),
    )

    show_subtitle = models.BooleanField(
        default=True,
        help_text=(
            "Show the banner subtitle."
        ),
    )

    show_metrics = models.BooleanField(
        default=True,
        help_text=(
            "Show the metric chips on the banner."
        ),
    )

    show_cta = models.BooleanField(
        default=True,
        help_text=(
            "Show the CTA button."
        ),
    )

    show_side_image = models.BooleanField(
        default=True,
        help_text=(
            "Show the optional floating side image."
        ),
    )

    metric_one_icon = models.CharField(
        max_length=50,
        default="box",
    )

    metric_one_text = models.CharField(
        max_length=80,
        default="Products",
    )

    metric_two_icon = models.CharField(
        max_length=50,
        default="shield-alt",
    )

    metric_two_text = models.CharField(
        max_length=80,
        default="Verified Vendors",
    )

    metric_three_icon = models.CharField(
        max_length=50,
        default="truck",
    )

    metric_three_text = models.CharField(
        max_length=80,
        default="Fast Delivery",
    )

    primary_color = models.CharField(
        max_length=20,
        blank=True,
        default="#2563eb",
    )

    secondary_color = models.CharField(
        max_length=20,
        blank=True,
        default="#7c3aed",
    )

    is_active = models.BooleanField(
        default=True,
        db_index=True,
    )

    display_order = models.PositiveIntegerField(
        default=0,
    )

    class Meta:
        ordering = [
            "display_order",
            "-created_at",
        ]

        verbose_name = (
            "Product Listing Banner"
        )

        verbose_name_plural = (
            "Product Listing Banners"
        )

    def save(
        self,
        *args,
        **kwargs,
    ):
        protect_uploaded_image(
            self,
            "background_image",
        )

        protect_uploaded_image(
            self,
            "side_image",
        )

        super().save(
            *args,
            **kwargs,
        )

        record_protected_image(
            self,
            "background_image",
        )

        record_protected_image(
            self,
            "side_image",
        )

    def __str__(self):
        return self.title

class ProductListLowerSection(BaseModel):
    SECTION_CHOICES = [
        ("why_buy", "Why Buy From Arolana"),
        ("buying_guides", "Buying Guides"),
        ("recently_viewed", "Recently Viewed"),
        ("recommendations", "You May Also Like"),
        ("verified_providers", "See Verified Service Providers"),
        ("blog", "From Our Blog"),
    ]

    SELECTION_CHOICES = [
        ("automatic", "Automatic"),
        ("manual", "Manual"),
        ("mixed", "Mixed"),
    ]

    section_type = models.CharField(
        max_length=40,
        choices=SECTION_CHOICES,
        unique=True,
    )
    title = models.CharField(max_length=160)
    subtitle = models.CharField(max_length=300, blank=True)

    is_active = models.BooleanField(default=True)
    display_order = models.PositiveSmallIntegerField(default=0)

    maximum_items = models.PositiveSmallIntegerField(default=40)
    desktop_visible_count = models.PositiveSmallIntegerField(default=4)
    tablet_visible_count = models.PositiveSmallIntegerField(default=3)
    mobile_visible_count = models.PositiveSmallIntegerField(default=2)

    selection_mode = models.CharField(
        max_length=20,
        choices=SELECTION_CHOICES,
        default="automatic",
    )

    view_all_text = models.CharField(
        max_length=50,
        default="View All",
    )
    view_all_url = models.CharField(max_length=300, blank=True)

    shuffle_on_refresh = models.BooleanField(default=False)
    show_when_empty = models.BooleanField(default=False)

    class Meta:
        ordering = ["display_order", "id"]
        verbose_name = "Product List Lower Section"
        verbose_name_plural = "Product List Lower Sections"

    def __str__(self):
        return self.title


class ProductListTrustBenefit(BaseModel):
    section = models.ForeignKey(
        ProductListLowerSection,
        on_delete=models.CASCADE,
        related_name="trust_benefits",
        limit_choices_to={"section_type": "why_buy"},
    )
    title = models.CharField(max_length=100)
    description = models.CharField(max_length=220, blank=True)
    icon = models.CharField(
        max_length=80,
        default="fas fa-shield-alt",
        help_text="Font Awesome class, e.g. fas fa-shield-alt",
    )
    display_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["display_order", "id"]

    def __str__(self):
        return self.title

# =============================================================================
# BACKWARD COMPATIBILITY ALIAS
# =============================================================================


ProductQnA = ProductQuestion
