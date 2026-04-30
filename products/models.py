from django.db import models
from django.urls import reverse
from django.utils.text import slugify
from django_ckeditor_5.fields import CKEditor5Field
from core.models import BaseModel
from accounts.models import User

class Category(BaseModel):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='children')
    image = models.ImageField(upload_to='categories/', null=True, blank=True)
    icon = models.CharField(max_length=50, blank=True)
    description = models.TextField(blank=True)
    order = models.IntegerField(default=0)
    
    class Meta:
        verbose_name_plural = 'Categories'
        ordering = ['order', 'name']
    
    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)
    
    def __str__(self):
        return self.name

class Brand(BaseModel):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    logo = models.ImageField(upload_to='brands/', null=True, blank=True)
    description = models.TextField(blank=True)
    
    class Meta:
        ordering = ['name']
    
    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)
    
    def __str__(self):
        return self.name

class Product(BaseModel):
    sku = models.CharField(max_length=50, unique=True, blank=True)
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    description = CKEditor5Field()
    specifications = CKEditor5Field(blank=True, null=True, help_text="Product specifications and technical details")
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='products')
    brand = models.ForeignKey(Brand, on_delete=models.SET_NULL, null=True, blank=True, related_name='products')
    vendor = models.ForeignKey(User, on_delete=models.CASCADE, related_name='products', limit_choices_to={'user_type': 'vendor'})
    
    # Pricing
    price = models.DecimalField(max_digits=10, decimal_places=2)
    compare_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="Original price before discount")
    cost_per_item = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="Your cost per item")
    
    # Inventory
    stock_quantity = models.IntegerField(default=0, help_text="Current stock quantity")
    low_stock_threshold = models.IntegerField(default=5, help_text="Alert when stock reaches this level")
    is_in_stock = models.BooleanField(default=True)
    allow_backorder = models.BooleanField(default=False, help_text="Allow customers to order when out of stock")
    
    # Media
    main_image = models.ImageField(upload_to='products/%Y/%m/', null=True, blank=True, help_text="Main product image")
    video_url = models.URLField(blank=True, help_text="YouTube or Vimeo URL")
    
    # SEO
    meta_title = models.CharField(max_length=200, blank=True, help_text="SEO title")
    meta_description = models.TextField(blank=True, help_text="SEO description")
    meta_keywords = models.CharField(max_length=200, blank=True, help_text="SEO keywords, comma separated")
    
    # Statistics
    views_count = models.IntegerField(default=0)
    sales_count = models.IntegerField(default=0)
    rating_avg = models.DecimalField(max_digits=3, decimal_places=2, default=0)
    rating_count = models.IntegerField(default=0)
    
    # Features
    is_featured = models.BooleanField(default=False, help_text="Show on homepage")
    is_new = models.BooleanField(default=False, help_text="Mark as new arrival")
    is_bestseller = models.BooleanField(default=False, help_text="Mark as bestseller")
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['sku']),
            models.Index(fields=['slug']),
            models.Index(fields=['category', 'is_active']),
            models.Index(fields=['-created_at']),
        ]
    
    def save(self, *args, **kwargs):
        if not self.sku:
            import random
            self.sku = f"ARO-{random.randint(100000, 999999)}"
        if not self.slug:
            self.slug = slugify(self.name)
        
        # Update stock status
        self.is_in_stock = self.stock_quantity > 0
        
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"{self.name} ({self.sku})"
    
    def get_absolute_url(self):
        return reverse('products:detail', kwargs={'slug': self.slug})
    
    @property
    def discount_percent(self):
        if self.compare_price and self.compare_price > self.price:
            return int(((self.compare_price - self.price) / self.compare_price) * 100)
        return 0
    
    @property
    def is_low_stock(self):
        return self.stock_quantity <= self.low_stock_threshold and self.stock_quantity > 0
    
    @property
    def final_price(self):
        return self.price

class ProductImage(BaseModel):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='products/gallery/%Y/%m/', help_text="Product gallery image")
    alt_text = models.CharField(max_length=200, blank=True, help_text="Image alt text for SEO")
    is_main = models.BooleanField(default=False, help_text="Set as main product image")
    order = models.IntegerField(default=0, help_text="Display order")
    
    class Meta:
        ordering = ['order']
        verbose_name = 'Product Image'
        verbose_name_plural = 'Product Images'
    
    def save(self, *args, **kwargs):
        # If this is set as main, unset other main images for this product
        if self.is_main:
            ProductImage.objects.filter(product=self.product, is_main=True).update(is_main=False)
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"Image for {self.product.name}"

class ProductVariant(BaseModel):
    VARIANT_TYPES = [
        ('size', 'Size'),
        ('color', 'Color'),
        ('material', 'Material'),
        ('style', 'Style'),
        ('other', 'Other'),
    ]
    
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='variants')
    variant_type = models.CharField(max_length=20, choices=VARIANT_TYPES, default='other', help_text="Type of variant")
    name = models.CharField(max_length=100, help_text="Variant name (Size, Color, etc.)")
    value = models.CharField(max_length=100, help_text="Variant value (Large, Red, etc.)")
    sku = models.CharField(max_length=50, unique=True, blank=True, help_text="Unique SKU for this variant")
    price_adjustment = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Additional cost (positive) or discount (negative)")
    stock_quantity = models.IntegerField(default=0, help_text="Stock quantity for this variant")
    image = models.ImageField(upload_to='products/variants/%Y/%m/', null=True, blank=True, help_text="Variant specific image")
    is_active = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['variant_type', 'name', 'value']
        unique_together = ['product', 'name', 'value']
        verbose_name = 'Product Variant'
        verbose_name_plural = 'Product Variants'
    
    def save(self, *args, **kwargs):
        if not self.sku:
            import random
            import string
            # Create a base SKU from product SKU and variant info
            base_sku = f"{self.product.sku}-{self.name[:2]}{self.value[:2]}".upper()
            # Remove any special characters
            base_sku = ''.join(c for c in base_sku if c.isalnum() or c == '-')
            # Add random numbers to ensure uniqueness
            random_suffix = ''.join(random.choices(string.digits, k=6))
            self.sku = f"{base_sku}-{random_suffix}"
            
            # Ensure the SKU is unique (in case of collision)
            while ProductVariant.objects.filter(sku=self.sku).exists():
                random_suffix = ''.join(random.choices(string.digits, k=6))
                self.sku = f"{base_sku}-{random_suffix}"
        
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"{self.product.name} - {self.name}: {self.value}"
    
    @property
    def final_price(self):
        return self.product.price + self.price_adjustment

class ProductVariantImage(BaseModel):
    """Multiple images per variant"""
    variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='products/variants/gallery/%Y/%m/')
    alt_text = models.CharField(max_length=200, blank=True)
    order = models.IntegerField(default=0)
    is_main = models.BooleanField(default=False)
    
    class Meta:
        ordering = ['order']
    
    def save(self, *args, **kwargs):
        if self.is_main:
            ProductVariantImage.objects.filter(variant=self.variant, is_main=True).update(is_main=False)
        super().save(*args, **kwargs)

class ProductReview(BaseModel):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='reviews')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reviews')
    rating = models.IntegerField(choices=[(i, i) for i in range(1, 6)], help_text="Rating from 1 to 5 stars")
    title = models.CharField(max_length=200, help_text="Review title")
    review = models.TextField(help_text="Your review")
    verified_purchase = models.BooleanField(default=False)
    helpful_count = models.IntegerField(default=0, help_text="Number of users who found this helpful")
    video_review = models.FileField(upload_to='reviews/videos/%Y/%m/', null=True, blank=True)
    images = models.JSONField(default=list, blank=True, help_text="List of image URLs")
    
    class Meta:
        unique_together = ['product', 'user']
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['product', '-created_at']),
            models.Index(fields=['rating']),
        ]
    
    def __str__(self):
        return f"{self.user.username} - {self.product.name} - {self.rating}★"

class RecentlyViewed(BaseModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='recently_viewed')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='recently_viewed_by')
    viewed_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-viewed_at']
        unique_together = ['user', 'product']
        indexes = [
            models.Index(fields=['user', '-viewed_at']),
        ]
    
    def __str__(self):
        return f"{self.user.username} viewed {self.product.name}"

class Wishlist(BaseModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='wishlist_items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='in_wishlists')
    
    class Meta:
        unique_together = ['user', 'product']
        indexes = [
            models.Index(fields=['user', 'product']),
        ]
    
    def __str__(self):
        return f"{self.user.username} - {self.product.name}"

class ProductVideo(BaseModel):
    """Product videos (multiple per product)"""
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='videos')
    video = models.ForeignKey('videos.Video', on_delete=models.CASCADE, related_name='product_videos')
    title = models.CharField(max_length=200, blank=True)
    is_main = models.BooleanField(default=False)
    display_order = models.IntegerField(default=0)    
    class Meta:
        ordering = ['display_order']
    
    def __str__(self):
        return f"{self.product.name} - {self.video.title if self.video.title else 'Video'}"

class ReviewVideo(BaseModel):
    """Customer review videos"""
    review = models.ForeignKey(ProductReview, on_delete=models.CASCADE, related_name='review_videos')
    video = models.ForeignKey('videos.Video', on_delete=models.CASCADE, related_name='review_videos')
    title = models.CharField(max_length=200, blank=True)
    
    def __str__(self):
        return f"Review video for {self.review.product.name}"
class ProductQnA(BaseModel):
    """Product Questions and Answers"""
    product = models.ForeignKey('Product', on_delete=models.CASCADE, related_name='qna')
    user = models.ForeignKey('accounts.User', on_delete=models.CASCADE, related_name='product_questions')
    question = models.TextField()
    answer = models.TextField(blank=True, null=True)
    answered_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='answered_questions')
    answered_at = models.DateTimeField(null=True, blank=True)
    is_public = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = "Product Q&A"
        verbose_name_plural = "Product Q&As"
    
    def __str__(self):
        return f"Q: {self.question[:50]}..."
    
    def is_answered(self):
        return bool(self.answer)
