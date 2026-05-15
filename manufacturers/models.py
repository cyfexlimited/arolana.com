from django.db import models
from core.models import BaseModel
from accounts.models import User
from products.models import Product, Category
from django.utils.text import slugify
from django.utils import timezone

SUBSCRIPTION_TIERS = [
    ('free', 'Free'),
    ('basic', 'Basic'),
    ('plus', 'Plus'),
    ('pro', 'Pro'),
    ('special', 'Special'),
    ('enterprise', 'Enterprise'),
]

class Manufacturer(BaseModel):
    """Manufacturer/Brand model"""
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    logo = models.ImageField(upload_to='manufacturers/logos/', null=True, blank=True)
    banner = models.ImageField(upload_to='manufacturers/banners/', null=True, blank=True)
    description = models.TextField(blank=True)
    
    # Contact Information
    website = models.URLField(blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    address = models.TextField(blank=True)
    
    # Social Media
    facebook_url = models.URLField(blank=True)
    twitter_url = models.URLField(blank=True)
    instagram_url = models.URLField(blank=True)
    linkedin_url = models.URLField(blank=True)
    
    # Statistics
    total_products = models.IntegerField(default=0)
    total_sales = models.IntegerField(default=0)
    rating_avg = models.DecimalField(max_digits=3, decimal_places=2, default=0)
    
    # Display settings
    is_featured = models.BooleanField(default=False, help_text="Show on homepage")
    is_active = models.BooleanField(default=True)
    display_order = models.IntegerField(default=0)
    subscription_tier = models.CharField(max_length=20, choices=SUBSCRIPTION_TIERS, default='free')
    subscription_expiry = models.DateTimeField(null=True, blank=True)
    priority_score = models.IntegerField(default=0, help_text="Higher score = better placement")
    
    class Meta:
        ordering = ['display_order', 'name']
        verbose_name = "Manufacturer"
        verbose_name_plural = "Manufacturers"
    
    def __str__(self):
        return self.name
    
    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)
    
    def get_absolute_url(self):
        from django.urls import reverse
        return reverse('manufacturers:detail', args=[self.slug])
    
    def update_statistics(self):
        """Update manufacturer statistics"""
        products = Product.objects.filter(manufacturer_links__manufacturer=self, is_active=True).distinct()
        self.total_products = products.count()
        self.total_sales = products.aggregate(total=models.Sum('sales_count'))['total'] or 0
        self.rating_avg = products.aggregate(avg=models.Avg('rating_avg'))['avg'] or 0
        self.save()

    def get_subscription_display(self):
        displays = {
            'free': {'color': 'gray', 'icon': 'fa-user', 'text': 'Free', 'badge_class': 'bg-gray-500'},
            'basic': {'color': 'blue', 'icon': 'fa-chart-line', 'text': 'Basic', 'badge_class': 'bg-blue-500'},
            'plus': {'color': 'cyan', 'icon': 'fa-layer-group', 'text': 'Plus', 'badge_class': 'bg-cyan-500'},
            'pro': {'color': 'purple', 'icon': 'fa-gem', 'text': 'Pro', 'badge_class': 'bg-purple-500'},
            'special': {'color': 'yellow', 'icon': 'fa-crown', 'text': 'Special', 'badge_class': 'bg-yellow-500'},
            'enterprise': {'color': 'indigo', 'icon': 'fa-building', 'text': 'Enterprise', 'badge_class': 'bg-indigo-600'},
        }
        try:
            from subscriptions.models import normalize_subscription_tier
            tier = normalize_subscription_tier(self.subscription_tier)
        except Exception:
            tier = self.subscription_tier
        return displays.get(tier, displays['free'])

    def has_active_subscription(self):
        try:
            from subscriptions.models import tier_is_paid, normalize_subscription_tier
            tier = normalize_subscription_tier(self.subscription_tier)
            if self.subscription_expiry and self.subscription_expiry <= timezone.now():
                return False
            return tier_is_paid(tier)
        except Exception:
            if self.subscription_expiry:
                return self.subscription_expiry > timezone.now() and self.subscription_tier != 'free'
            return self.subscription_tier != 'free'

class ManufacturerApplication(BaseModel):
    """Vendor applications to represent manufacturers"""
    STATUS_CHOICES = [
        ('pending', 'Pending Review'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]
    
    vendor = models.ForeignKey(User, on_delete=models.CASCADE, related_name='manufacturer_applications')
    manufacturer = models.ForeignKey(Manufacturer, on_delete=models.CASCADE, related_name='applications')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    notes = models.TextField(blank=True, help_text="Admin notes")
    approved_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        unique_together = ['vendor', 'manufacturer']
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.vendor.username} - {self.manufacturer.name} ({self.status})"

class ManufacturerCategory(BaseModel):
    """Categories for manufacturers (Electronics, Clothing, etc.)"""
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    icon = models.CharField(max_length=50, blank=True, help_text="FontAwesome icon class")
    description = models.TextField(blank=True)
    display_order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['display_order', 'name']
        verbose_name = "Manufacturer Category"
        verbose_name_plural = "Manufacturer Categories"
    
    def __str__(self):
        return self.name
    
    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

class ManufacturerProduct(BaseModel):
    """Products from manufacturers (for vendor representation)"""
    manufacturer = models.ForeignKey(Manufacturer, on_delete=models.CASCADE, related_name='products')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='manufacturer_links')
    vendor = models.ForeignKey(User, on_delete=models.CASCADE, related_name='manufacturer_products')
    is_approved = models.BooleanField(default=False)
    commission_rate = models.DecimalField(max_digits=5, decimal_places=2, default=10.0, help_text="Commission percentage")
    
    class Meta:
        unique_together = ['manufacturer', 'product']
    
    def __str__(self):
        return f"{self.manufacturer.name} - {self.product.name}"
