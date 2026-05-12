from decimal import Decimal
from django.db import models
from django.urls import reverse
from django.utils.text import slugify
from django.core.validators import MinValueValidator, MaxValueValidator, URLValidator
from django.core.exceptions import ValidationError
from django.utils.timezone import now
from django_ckeditor_5.fields import CKEditor5Field
from taggit.managers import TaggableManager
from core.models import BaseModel
from accounts.models import User
import uuid
import random
import string
from phonenumber_field.modelfields import PhoneNumberField

# =========================
# 🔥 VENDOR MODEL
# =========================
class Vendor(BaseModel):
    """Vendor/Seller profile"""
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='vendor'
    )
    shop_name = models.CharField(max_length=200, unique=True, db_index=True)
    shop_slug = models.SlugField(max_length=255, unique=True, db_index=True)
    shop_logo = models.ImageField(upload_to='vendors/logos/%Y/%m/', null=True, blank=True)
    shop_banner = models.ImageField(upload_to='vendors/banners/%Y/%m/', null=True, blank=True)
    shop_description = models.TextField(blank=True)
    
    # Contact Information
    shop_phone = PhoneNumberField(null=True, blank=True)
    shop_email = models.EmailField(null=True, blank=True)
    shop_website = models.URLField(blank=True)
    
    # Business Information
    business_address = models.TextField(blank=True)
    business_license = models.CharField(max_length=100, blank=True)
    tax_id = models.CharField(max_length=100, blank=True)
    
    # Verification & Status
    is_verified = models.BooleanField(default=False, db_index=True)
    verification_date = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    
    # Statistics
    total_products = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    total_sales = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    rating_avg = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(5)]
    )
    rating_count = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    total_reviews = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    
    # Commission & Policies
    commission_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=5.00,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Commission percentage"
    )
    response_time = models.CharField(
        max_length=50,
        blank=True,
        help_text="Average response time"
    )
    return_policy = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['is_verified', 'is_active']),
            models.Index(fields=['-rating_avg']),
        ]
    
    def save(self, *args, **kwargs):
        if not self.shop_slug:
            self.shop_slug = slugify(self.shop_name)
        super().save(*args, **kwargs)
    
    def __str__(self):
        return self.shop_name
    
    def get_absolute_url(self):
        return reverse('products:vendor', kwargs={'slug': self.shop_slug})


# =========================
# 🔥 CATEGORY MODEL
# =========================
class Category(BaseModel):
    """Product categories with hierarchical support"""
    name = models.CharField(max_length=100, unique=True, db_index=True)
    slug = models.SlugField(max_length=255, unique=True, db_index=True)
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='children'
    )
    image = models.ImageField(upload_to='categories/%Y/%m/', null=True, blank=True, help_text="Category thumbnail image (for cards)")
    background_image = models.ImageField(
        upload_to='categories/backgrounds/%Y/%m/', 
        null=True, 
        blank=True, 
        help_text="Hero background image for category landing page (1920x400 recommended)"
    )
    icon = models.CharField(max_length=50, blank=True, help_text="CSS icon class or icon name")
    description = models.TextField(blank=True, help_text="Category description for SEO")
    hero_title = models.CharField(
        max_length=200, 
        blank=True, 
        null=True, 
        help_text="Custom hero title (overrides default category name)"
    )
    hero_subtitle = models.CharField(
        max_length=500, 
        blank=True, 
        null=True, 
        help_text="Hero subtitle text displayed on category landing page"
    )
    meta_title = models.CharField(max_length=200, blank=True, help_text="SEO title")
    meta_description = models.TextField(blank=True, help_text="SEO description (160 chars)")
    meta_keywords = models.CharField(max_length=200, blank=True)
    order = models.IntegerField(default=0, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    
    class Meta:
        verbose_name_plural = 'Categories'
        ordering = ['order', 'name']
        indexes = [
            models.Index(fields=['is_active', 'order']),
            models.Index(fields=['parent', 'is_active']),
        ]
    
    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)
    
    def __str__(self):
        return self.name
    
    def get_absolute_url(self):
        return reverse('products:category', kwargs={'slug': self.slug})
    
    def get_ancestors(self):
        """Get all parent categories"""
        ancestors = []
        current = self.parent
        while current:
            ancestors.append(current)
            current = current.parent
        return reversed(ancestors)
    
    @property
    def product_count(self):
        """Get total products in this category including subcategories"""
        from products.models import Product
        category_ids = [self.id]
        for child in self.children.filter(is_active=True):
            category_ids.append(child.id)
            for grandchild in child.children.filter(is_active=True):
                category_ids.append(grandchild.id)
        return Product.objects.filter(
            category_id__in=category_ids,
            is_active=True
        ).count()
    
    @property
    def display_hero_title(self):
        """Get hero title with fallback to category name"""
        return self.hero_title if self.hero_title else self.name
    
    @property
    def display_hero_subtitle(self):
        """Get hero subtitle with fallback to description"""
        if self.hero_subtitle:
            return self.hero_subtitle
        if self.description:
            return self.description
        return f"Discover our curated collection of {self.name.lower()} products"
    
    @property
    def has_background_image(self):
        """Check if category has a background image"""
        return bool(self.background_image)


# =========================
# 🔥 BRAND MODEL
# =========================
class Brand(BaseModel):
    """Product brands/manufacturers"""
    name = models.CharField(max_length=100, unique=True, db_index=True)
    slug = models.SlugField(max_length=255, unique=True, db_index=True)
    logo = models.ImageField(upload_to='brands/%Y/%m/', null=True, blank=True)
    description = models.TextField(blank=True)
    website = models.URLField(blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    featured = models.BooleanField(default=False)
    
    class Meta:
        ordering = ['name']
        indexes = [
            models.Index(fields=['is_active', 'featured']),
        ]
    
    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)
    
    def __str__(self):
        return self.name
    
    def get_absolute_url(self):
        return reverse('products:brand', kwargs={'slug': self.slug})


# =========================
# 🔥 PRODUCT MODEL WITH APPROVAL SYSTEM
# =========================
class Product(BaseModel):
    """Enhanced product model with comprehensive features and approval system"""
    
    # Basic Info
    sku = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text="Unique product identifier"
    )
    name = models.CharField(max_length=200, db_index=True)
    slug = models.SlugField(max_length=255, unique=True, db_index=True)
    description = CKEditor5Field()
    specifications = CKEditor5Field(
        blank=True,
        null=True,
        help_text="Product specifications and technical details"
    )
    
    # Relationships
    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name='products',
        db_index=True
    )
    brand = models.ForeignKey(
        Brand,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='products'
    )
    vendor = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='products',
        limit_choices_to={'user_type': 'vendor'},
        db_index=True
    )
    
    # Pricing
    price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
        db_index=True
    )
    compare_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.01'))],
        help_text="Original price before discount"
    )
    cost_per_item = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.01'))],
        help_text="Your cost per item (for profit calculation)"
    )
    
    # Inventory
    stock_quantity = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        db_index=True,
        help_text="Current stock quantity"
    )
    low_stock_threshold = models.IntegerField(
        default=5,
        validators=[MinValueValidator(0)],
        help_text="Alert when stock reaches this level"
    )
    is_in_stock = models.BooleanField(default=True, db_index=True)
    allow_backorder = models.BooleanField(
        default=False,
        help_text="Allow customers to order when out of stock"
    )
    reserved_quantity = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Quantity reserved for pending orders"
    )
    
    # Physical Attributes
    weight = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.001'))],
        help_text="Product weight"
    )
    weight_unit = models.CharField(
        max_length=10,
        choices=[('kg', 'Kilograms'), ('lbs', 'Pounds'), ('g', 'Grams'), ('oz', 'Ounces')],
        default='kg'
    )
    dimensions_length = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.01'))],
        help_text="Length"
    )
    dimensions_width = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.01'))],
        help_text="Width"
    )
    dimensions_height = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.01'))],
        help_text="Height"
    )
    dimension_unit = models.CharField(
        max_length=10,
        choices=[('cm', 'Centimeters'), ('in', 'Inches'), ('mm', 'Millimeters')],
        default='cm'
    )
    
    # Warranty
    warranty_years = models.IntegerField(
        default=1,
        validators=[MinValueValidator(0)],
        help_text="Warranty period in years"
    )
    warranty_description = models.TextField(blank=True, help_text="Warranty terms")
    extended_warranty_available = models.BooleanField(default=False)
    extended_warranty_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.01'))]
    )
    
    # Media
    main_image = models.ImageField(
        upload_to='products/%Y/%m/',
        null=True,
        blank=True,
        help_text="Main product image (featured)"
    )
    
    # Video
    VIDEO_TYPE_CHOICES = [
        ('youtube', 'YouTube'),
        ('vimeo', 'Vimeo'),
        ('local', 'Local Video'),
    ]
    video_type = models.CharField(
        max_length=20,
        choices=VIDEO_TYPE_CHOICES,
        default='youtube',
        blank=True
    )
    video_url = models.URLField(blank=True, help_text="YouTube or Vimeo URL")
    local_video = models.FileField(
        upload_to='products/videos/%Y/%m/',
        null=True,
        blank=True,
        help_text="Local video file (MP4, WebM)"
    )
    video_thumbnail = models.ImageField(
        upload_to='products/video_thumbs/%Y/%m/',
        null=True,
        blank=True
    )
    video_title = models.CharField(max_length=200, blank=True)
    
    # SEO
    meta_title = models.CharField(max_length=200, blank=True, help_text="SEO title (60 chars)")
    meta_description = models.TextField(
        blank=True,
        max_length=160,
        help_text="SEO description (160 chars)"
    )
    meta_keywords = models.CharField(
        max_length=200,
        blank=True,
        help_text="Comma-separated SEO keywords"
    )
    
    # Statistics
    views_count = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    sales_count = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    rating_avg = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(5)]
    )
    rating_count = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    
    # Features & Status
    is_featured = models.BooleanField(default=False, db_index=True, help_text="Show on homepage")
    is_new = models.BooleanField(default=False, db_index=True, help_text="New arrival")
    is_bestseller = models.BooleanField(default=False, db_index=True, help_text="Bestseller")
    is_active = models.BooleanField(default=True, db_index=True)
    
    # ========== APPROVAL SYSTEM ==========
    APPROVAL_STATUS_CHOICES = [
        ('pending', 'Pending Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('requires_changes', 'Requires Changes'),
    ]
    
    approval_status = models.CharField(
        max_length=20, 
        choices=APPROVAL_STATUS_CHOICES, 
        default='pending',
        db_index=True
    )
    approval_notes = models.TextField(blank=True, help_text="Notes from admin about approval/rejection")
    approved_by = models.ForeignKey(
        'accounts.User', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='approved_products'
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    submitted_for_review_at = models.DateTimeField(auto_now_add=True)
    resubmitted_at = models.DateTimeField(null=True, blank=True)
    
    # Tags
    tags = TaggableManager(blank=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['sku']),
            models.Index(fields=['slug']),
            models.Index(fields=['category', 'is_active', 'approval_status']),
            models.Index(fields=['-created_at']),
            models.Index(fields=['vendor', 'is_active']),
            models.Index(fields=['is_featured', '-created_at']),
            models.Index(fields=['is_bestseller', '-sales_count']),
            models.Index(fields=['rating_avg', '-rating_count']),
            models.Index(fields=['approval_status', '-submitted_for_review_at']),
        ]
    
    def clean(self):
        """Validate product data"""
        if self.compare_price and self.compare_price <= self.price:
            raise ValidationError("Compare price must be greater than price")
        if self.stock_quantity < 0:
            raise ValidationError("Stock quantity cannot be negative")
    
    def save(self, *args, **kwargs):
        self.clean()
        
        if not self.sku:
            self.sku = self._generate_sku()
        
        # Always slugify - this removes parentheses and special chars
        if not self.slug:
            self.slug = slugify(self.name)
        else:
            # Re-sanitize existing slugs to remove invalid characters
            self.slug = slugify(self.slug)
        
        # Update stock status
        self.is_in_stock = self.get_available_stock() > 0
        
        super().save(*args, **kwargs)
    
    def _generate_sku(self):
        """Generate unique SKU"""
        prefix = f"{self.category.slug[:3]}-{self.brand.slug[:3] if self.brand else 'XXX'}".upper()
        random_part = ''.join(random.choices(string.digits, k=8))
        return f"{prefix}{random_part}"
    
    def __str__(self):
        return f"{self.name} ({self.sku})"
    
    def get_absolute_url(self):
        return reverse('products:detail', kwargs={'slug': self.slug})
    
    @property
    def discount_percent(self):
        """Calculate discount percentage"""
        if self.compare_price and self.compare_price > self.price:
            discount = ((self.compare_price - self.price) / self.compare_price) * 100
            return int(discount)
        return 0
    
    @property
    def is_low_stock(self):
        """Check if stock is low"""
        return self.stock_quantity <= self.low_stock_threshold and self.stock_quantity > 0
    
    @property
    def available_stock(self):
        """Get available stock (total - reserved)"""
        return max(0, self.stock_quantity - self.reserved_quantity)
    
    def get_available_stock(self):
        """Get available stock"""
        return self.available_stock
    
    @property
    def profit_margin(self):
        """Calculate profit margin percentage"""
        if self.cost_per_item and self.price > self.cost_per_item:
            margin = ((self.price - self.cost_per_item) / self.price) * 100
            return round(margin, 2)
        return 0
    
    @property
    def dimensions(self):
        """Return formatted dimensions"""
        if all([self.dimensions_length, self.dimensions_width, self.dimensions_height]):
            return f"{self.dimensions_length}×{self.dimensions_width}×{self.dimensions_height} {self.dimension_unit}"
        return None
    
    @property
    def formatted_weight(self):
        """Return formatted weight"""
        if self.weight:
            return f"{self.weight} {self.weight_unit}"
        return None
    
    # ========== APPROVAL SYSTEM METHODS ==========
    def needs_approval(self):
        """Check if product needs approval"""
        return self.approval_status == 'pending'
    
    def is_approved(self):
        """Check if product is approved"""
        return self.approval_status == 'approved'
    
    def is_rejected(self):
        """Check if product is rejected"""
        return self.approval_status in ['rejected', 'requires_changes']
    
    def resubmit_for_approval(self):
        """Resubmit product for approval after changes"""
        self.approval_status = 'pending'
        self.approval_notes = ''
        self.resubmitted_at = now()
        self.save()
    
    def get_video_embed_url(self):
        """Get embed URL for video"""
        if not self.video_type:
            return None
        
        if self.video_type == 'local' and self.local_video:
            return self.local_video.url
        
        elif self.video_type == 'youtube' and self.video_url:
            return self._extract_youtube_embed(self.video_url)
        
        elif self.video_type == 'vimeo' and self.video_url:
            return self._extract_vimeo_embed(self.video_url)
        
        return None
    
    @staticmethod
    def _extract_youtube_embed(url):
        """Extract YouTube embed URL"""
        if 'youtu.be/' in url:
            video_id = url.split('youtu.be/')[1].split('?')[0]
        elif 'youtube.com/watch' in url:
            video_id = url.split('v=')[1].split('&')[0]
        elif 'youtube.com/embed/' in url:
            return url
        else:
            return None
        return f"https://www.youtube.com/embed/{video_id}"
    
    @staticmethod
    def _extract_vimeo_embed(url):
        """Extract Vimeo embed URL"""
        try:
            video_id = url.split('vimeo.com/')[1].split('?')[0]
            return f"https://player.vimeo.com/video/{video_id}"
        except (IndexError, ValueError):
            return None
    
    def increment_views(self):
        """Increment view count"""
        Product.objects.filter(pk=self.pk).update(views_count=models.F('views_count') + 1)


# =========================
# 🔥 ACCESSORY MODEL
# =========================
class Accessory(BaseModel):
    """Standalone accessories/add-ons"""
    name = models.CharField(max_length=200, db_index=True)
    slug = models.SlugField(max_length=255, unique=True, blank=True)
    description = models.TextField(blank=True)
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))]
    )
    compare_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.01'))]
    )
    image = models.ImageField(upload_to='accessories/%Y/%m/', null=True, blank=True)
    stock_quantity = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    is_active = models.BooleanField(default=True, db_index=True)
    display_order = models.IntegerField(default=0)
    
    class Meta:
        ordering = ['display_order', 'name']
        verbose_name_plural = 'Accessories'
        indexes = [
            models.Index(fields=['is_active', 'display_order']),
        ]
    
    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"{self.name} - ${self.price}"
    
    @property
    def discount_percent(self):
        """Calculate discount percentage"""
        if self.compare_price and self.compare_price > self.price:
            return int(((self.compare_price - self.price) / self.compare_price) * 100)
        return 0


# =========================
# 🔥 ACCESSORY-PRODUCT RELATIONSHIP
# =========================
class AccessoryProduct(BaseModel):
    """Many-to-many relationship for product accessories with additional metadata"""
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='product_accessories'
    )
    accessory = models.ForeignKey(
        Accessory,
        on_delete=models.CASCADE,
        related_name='linked_products'
    )
    required = models.BooleanField(default=False, help_text="Is this accessory required?")
    discount_when_bought_together = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Discount % when bought together"
    )
    display_order = models.IntegerField(default=0)
    
    class Meta:
        unique_together = ['product', 'accessory']
        ordering = ['display_order']
        verbose_name = 'Product Accessory'
        verbose_name_plural = 'Product Accessories'
    
    def __str__(self):
        return f"{self.product.name} + {self.accessory.name}"


# =========================
# 🔥 PRODUCT IMAGE MODEL
# =========================
class ProductImage(BaseModel):
    """Product gallery images"""
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='images'
    )
    image = models.ImageField(
        upload_to='products/gallery/%Y/%m/',
        help_text="Product gallery image"
    )
    alt_text = models.CharField(max_length=200, blank=True, help_text="Alt text for SEO")
    is_main = models.BooleanField(default=False, help_text="Set as main product image")
    order = models.IntegerField(default=0)
    
    class Meta:
        ordering = ['order']
        verbose_name = 'Product Image'
        verbose_name_plural = 'Product Images'
        indexes = [
            models.Index(fields=['product', 'order']),
        ]
    
    def save(self, *args, **kwargs):
        if self.is_main:
            ProductImage.objects.filter(
                product=self.product,
                is_main=True
            ).exclude(pk=self.pk).update(is_main=False)
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"Image for {self.product.name}"


# =========================
# 🔥 PRODUCT VARIANT MODEL
# =========================
class ProductVariant(BaseModel):
    """Product variants (size, color, material, etc.)"""
    
    VARIANT_TYPES = [
        ('size', 'Size'),
        ('color', 'Color'),
        ('material', 'Material'),
        ('style', 'Style'),
        ('pattern', 'Pattern'),
        ('finish', 'Finish'),
        ('capacity', 'Capacity'),
        ('other', 'Other'),
    ]
    
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='variants'
    )
    variant_type = models.CharField(
        max_length=20,
        choices=VARIANT_TYPES,
        default='other'
    )
    name = models.CharField(max_length=100, help_text="Variant name (Size, Color, etc.)")
    value = models.CharField(max_length=100, help_text="Variant value (Large, Red, etc.)")
    sku = models.CharField(max_length=50, unique=True, blank=True)
    price_adjustment = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Price adjustment (positive or negative)"
    )
    stock_quantity = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)]
    )
    image = models.ImageField(
        upload_to='products/variants/%Y/%m/',
        null=True,
        blank=True
    )
    is_active = models.BooleanField(default=True, db_index=True)
    
    class Meta:
        ordering = ['variant_type', 'name', 'value']
        unique_together = ['product', 'name', 'value']
        verbose_name = 'Product Variant'
        verbose_name_plural = 'Product Variants'
        indexes = [
            models.Index(fields=['product', 'is_active']),
        ]
    
    def save(self, *args, **kwargs):
        if not self.sku:
            self.sku = self._generate_variant_sku()
        super().save(*args, **kwargs)
    
    def _generate_variant_sku(self):
        """Generate unique SKU for variant"""
        base_sku = f"{self.product.sku}-{self.name[:2]}{self.value[:2]}".upper()
        base_sku = ''.join(c for c in base_sku if c.isalnum() or c == '-')
        
        random_suffix = ''.join(random.choices(string.digits, k=6))
        sku = f"{base_sku}-{random_suffix}"
        
        # Ensure uniqueness
        while ProductVariant.objects.filter(sku=sku).exists():
            random_suffix = ''.join(random.choices(string.digits, k=6))
            sku = f"{base_sku}-{random_suffix}"
        
        return sku
    
    def __str__(self):
        return f"{self.product.name} - {self.name}: {self.value}"
    
    @property
    def final_price(self):
        """Calculate final price with adjustment"""
        return self.product.price + self.price_adjustment
    
    @property
    def is_available(self):
        """Check if variant is available"""
        return self.is_active and self.stock_quantity > 0


# =========================
# 🔥 VARIANT IMAGE MODEL
# =========================
class ProductVariantImage(BaseModel):
    """Multiple images per variant"""
    variant = models.ForeignKey(
        ProductVariant,
        on_delete=models.CASCADE,
        related_name='images'
    )
    image = models.ImageField(upload_to='products/variants/gallery/%Y/%m/')
    alt_text = models.CharField(max_length=200, blank=True)
    order = models.IntegerField(default=0)
    is_main = models.BooleanField(default=False)
    
    class Meta:
        ordering = ['order']
        verbose_name = 'Variant Image'
        verbose_name_plural = 'Variant Images'
    
    def save(self, *args, **kwargs):
        if self.is_main:
            ProductVariantImage.objects.filter(
                variant=self.variant,
                is_main=True
            ).exclude(pk=self.pk).update(is_main=False)
        super().save(*args, **kwargs)


# =========================
# 🔥 PRODUCT VIDEO MODEL
# =========================
class ProductVideo(BaseModel):
    """Multiple videos per product"""
    
    VIDEO_SOURCE_CHOICES = [
        ('youtube', 'YouTube'),
        ('vimeo', 'Vimeo'),
        ('local', 'Local Video'),
    ]
    
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='additional_videos'
    )
    title = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    source = models.CharField(
        max_length=20,
        choices=VIDEO_SOURCE_CHOICES,
        default='youtube'
    )
    youtube_url = models.URLField(blank=True, help_text="YouTube video URL")
    vimeo_url = models.URLField(blank=True, help_text="Vimeo video URL")
    local_video = models.FileField(
        upload_to='products/videos/additional/%Y/%m/',
        null=True,
        blank=True,
        help_text="MP4, WebM, or Ogg format"
    )
    thumbnail = models.ImageField(
        upload_to='products/video_thumbs/additional/%Y/%m/',
        null=True,
        blank=True
    )
    is_main = models.BooleanField(default=False)
    display_order = models.IntegerField(default=0)
    
    class Meta:
        ordering = ['display_order']
        verbose_name = 'Product Video'
        verbose_name_plural = 'Product Videos'
    
    def __str__(self):
        return f"{self.product.name} - {self.title or 'Video'}"
    
    def get_embed_url(self):
        """Get embed URL for video"""
        if self.source == 'youtube' and self.youtube_url:
            return Product._extract_youtube_embed(self.youtube_url)
        elif self.source == 'vimeo' and self.vimeo_url:
            return Product._extract_vimeo_embed(self.vimeo_url)
        elif self.source == 'local' and self.local_video:
            return self.local_video.url
        return None


# =========================
# 🔥 PRODUCT REVIEW MODEL
# =========================
class ProductReview(BaseModel):
    """Customer product reviews with rich media support"""
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='reviews',
        db_index=True
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='product_reviews'
    )
    rating = models.IntegerField(
        choices=[(i, f"{i} Star{'s' if i > 1 else ''}") for i in range(1, 6)],
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    title = models.CharField(max_length=200, help_text="Review title")
    review = models.TextField(help_text="Your detailed review")
    verified_purchase = models.BooleanField(default=False, db_index=True)
    helpful_count = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    unhelpful_count = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    video_review = models.FileField(
        upload_to='reviews/videos/%Y/%m/',
        null=True,
        blank=True,
        help_text="Optional review video"
    )
    
    class Meta:
        unique_together = ['product', 'user']
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['product', '-created_at']),
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['rating']),
            models.Index(fields=['verified_purchase', '-helpful_count']),
        ]
    
    def __str__(self):
        return f"{self.user.username} - {self.product.name} - {self.rating}★"
    
    def helpful_ratio(self):
        """Get helpful/unhelpful ratio"""
        total = self.helpful_count + self.unhelpful_count
        return (self.helpful_count / total * 100) if total > 0 else 0


# =========================
# 🔥 PRODUCT Q&A MODEL
# =========================
class ProductQuestion(BaseModel):
    """Product Q&A system"""
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='questions'
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='product_questions'
    )
    question = models.TextField()
    answer = models.TextField(blank=True, null=True)
    answered_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='answered_product_questions'
    )
    answered_at = models.DateTimeField(null=True, blank=True)
    helpful_count = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    is_public = models.BooleanField(default=True, db_index=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = "Product Question"
        verbose_name_plural = "Product Questions"
        indexes = [
            models.Index(fields=['product', 'is_public']),
            models.Index(fields=['user', '-created_at']),
        ]
    
    def __str__(self):
        return f"Q: {self.question[:50]}..."
    
    def is_answered(self):
        """Check if question is answered"""
        return bool(self.answer and self.answered_at)
    
    def mark_as_answered(self, user, answer_text):
        """Mark question as answered"""
        self.answer = answer_text
        self.answered_by = user
        self.answered_at = now()
        self.save()


# =========================
# 🔥 RECENTLY VIEWED
# =========================
class RecentlyViewed(BaseModel):
    """Track recently viewed products"""
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='recently_viewed'
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='recently_viewed_by'
    )
    viewed_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-viewed_at']
        unique_together = ['user', 'product']
        indexes = [
            models.Index(fields=['user', '-viewed_at']),
        ]
    
    def __str__(self):
        return f"{self.user.username} viewed {self.product.name}"


# =========================
# 🔥 WISHLIST
# =========================
class Wishlist(BaseModel):
    """User wishlist"""
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='wishlist_items'
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='in_wishlists'
    )
    added_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    
    class Meta:
        unique_together = ['user', 'product']
        ordering = ['-added_at']
        indexes = [
            models.Index(fields=['user', '-added_at']),
        ]
    
    def __str__(self):
        return f"{self.user.username} - {self.product.name}"


# =========================
# 🔥 MANUFACTURER WARRANTY
# =========================
class ManufacturerWarranty(BaseModel):
    """Manufacturer warranty information"""
    product = models.OneToOneField(
        Product,
        on_delete=models.CASCADE,
        related_name='manufacturer_warranty'
    )
    provider = models.CharField(max_length=200, help_text="Warranty provider name")
    duration_years = models.IntegerField(
        default=1,
        validators=[MinValueValidator(0)]
    )
    duration_months = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(11)]
    )
    coverage_details = models.TextField(blank=True, help_text="What's covered")
    exclusions = models.TextField(blank=True, help_text="What's not covered")
    terms_url = models.URLField(blank=True, help_text="Link to warranty terms")
    registration_required = models.BooleanField(default=False)
    registration_url = models.URLField(blank=True, help_text="Warranty registration URL")
    customer_support_phone = models.CharField(max_length=50, blank=True)
    customer_support_email = models.EmailField(blank=True)
    
    class Meta:
        verbose_name = "Manufacturer Warranty"
        verbose_name_plural = "Manufacturer Warranties"
    
    def __str__(self):
        return f"Warranty for {self.product.name}"
    
    def duration_text(self):
        """Return human-readable duration"""
        if self.duration_years and self.duration_months:
            return f"{self.duration_years} year{'s' if self.duration_years > 1 else ''} {self.duration_months} month{'s' if self.duration_months > 1 else ''}"
        elif self.duration_years:
            return f"{self.duration_years} year{'s' if self.duration_years > 1 else ''}"
        elif self.duration_months:
            return f"{self.duration_months} month{'s' if self.duration_months > 1 else ''}"
        return "No warranty"


# =========================
# 🔥 SHIPPING INFO
# =========================
class ShippingInfo(BaseModel):
    """Product shipping information"""
    product = models.OneToOneField(
        Product,
        on_delete=models.CASCADE,
        related_name='shipping_info'
    )
    weight_shipping = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.001'))],
        help_text="Shipping weight (kg/lbs)"
    )
    dimensions_package = models.CharField(
        max_length=100,
        blank=True,
        help_text="Package dimensions (L×W×H)"
    )
    shipping_restrictions = models.TextField(
        blank=True,
        help_text="Shipping restrictions or special handling notes"
    )
    hazmat = models.BooleanField(
        default=False,
        help_text="Is this a hazardous material?"
    )
    free_shipping = models.BooleanField(default=False)
    estimated_delivery_days_min = models.IntegerField(
        default=3,
        validators=[MinValueValidator(1)]
    )
    estimated_delivery_days_max = models.IntegerField(
        default=7,
        validators=[MinValueValidator(1)]
    )
    
    class Meta:
        verbose_name = "Shipping Information"
        verbose_name_plural = "Shipping Information"
    
    def __str__(self):
        return f"Shipping info for {self.product.name}"
    
    def delivery_estimate(self):
        """Return delivery time estimate"""
        if self.estimated_delivery_days_min == self.estimated_delivery_days_max:
            return f"{self.estimated_delivery_days_min} days"
        return f"{self.estimated_delivery_days_min}-{self.estimated_delivery_days_max} days"


# =========================
# 🔥 REVIEW VIDEO MODEL
# =========================
class ReviewVideo(BaseModel):
    """Customer review videos"""
    review = models.ForeignKey(ProductReview, on_delete=models.CASCADE, related_name='review_videos')
    title = models.CharField(max_length=200, blank=True)
    video_file = models.FileField(
        upload_to='reviews/videos/%Y/%m/',
        null=True,
        blank=True,
        help_text="Upload review video"
    )
    thumbnail = models.ImageField(upload_to='reviews/thumbs/%Y/%m/', null=True, blank=True)
    is_main = models.BooleanField(default=False)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Review video for {self.review.product.name}"


# =========================
# 🔥 BACKWARD COMPATIBILITY ALIAS
# =========================
ProductQnA = ProductQuestion