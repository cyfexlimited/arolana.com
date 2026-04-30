from django.db import models
from django.db.models import Avg
from django.utils import timezone
from accounts.models import User
from core.models import BaseModel

class VendorProfile(BaseModel):
    SUBSCRIPTION_TIERS = [
        ('free', 'Free'),
        ('basic', 'Basic'),
        ('premium', 'Premium'),
        ('enterprise', 'Enterprise'),
        ('featured', 'Featured'),
    ]
    
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='vendor_profile')
    store_name = models.CharField(max_length=200)
    store_slug = models.SlugField(unique=True)
    store_logo = models.ImageField(upload_to='vendors/logos/', null=True, blank=True)
    store_banner = models.ImageField(upload_to='vendors/banners/', null=True, blank=True)
    description = models.TextField()
    is_verified = models.BooleanField(default=False)
    verification_documents = models.FileField(upload_to='vendors/documents/', null=True, blank=True)
    
    # Subscription tier for priority sorting
    subscription_tier = models.CharField(max_length=20, choices=SUBSCRIPTION_TIERS, default='free')
    subscription_expiry = models.DateTimeField(null=True, blank=True)
    priority_score = models.IntegerField(default=0, help_text="Higher score = better placement")
    
    # Ratings and sales
    rating_avg = models.DecimalField(max_digits=3, decimal_places=2, default=0)
    total_sales = models.IntegerField(default=0)
    total_reviews = models.IntegerField(default=0)
    
    # Subscription/Followers
    followers_count = models.IntegerField(default=0)
    
    # Vendor performance metrics
    response_time = models.CharField(max_length=50, default='< 1 hour', blank=True)
    fulfillment_rate = models.DecimalField(max_digits=5, decimal_places=2, default=99.5)
    return_rate = models.DecimalField(max_digits=5, decimal_places=2, default=2.5)
    
    # Badges
    is_top_rated = models.BooleanField(default=False)
    is_best_seller = models.BooleanField(default=False)
    is_trusted = models.BooleanField(default=False)
    
    class Meta:
        ordering = ['-priority_score', '-subscription_tier', '-rating_avg', '-total_sales']
    
    def __str__(self):
        return self.store_name
    
    def get_absolute_url(self):
        from django.urls import reverse
        return reverse('vendors:detail', args=[self.store_slug])
    
    def get_subscription_display(self):
        """Get formatted subscription display"""
        displays = {
            'free': {'color': 'gray', 'icon': 'fa-user', 'text': 'Free', 'badge_class': 'bg-gray-500'},
            'basic': {'color': 'blue', 'icon': 'fa-chart-line', 'text': 'Basic', 'badge_class': 'bg-blue-500'},
            'premium': {'color': 'purple', 'icon': 'fa-gem', 'text': 'Premium', 'badge_class': 'bg-purple-500'},
            'enterprise': {'color': 'indigo', 'icon': 'fa-building', 'text': 'Enterprise', 'badge_class': 'bg-indigo-600'},
            'featured': {'color': 'yellow', 'icon': 'fa-crown', 'text': 'Featured', 'badge_class': 'bg-yellow-500'},
        }
        return displays.get(self.subscription_tier, displays['free'])
    
    def get_priority_multiplier(self):
        """Get multiplier for display priority based on subscription"""
        multipliers = {
            'free': 1,
            'basic': 2,
            'premium': 3,
            'enterprise': 4,
            'featured': 5,
        }
        return multipliers.get(self.subscription_tier, 1)
    
    def has_active_subscription(self):
        """Check if vendor has an active paid subscription"""
        if self.subscription_expiry:
            return self.subscription_expiry > timezone.now() and self.subscription_tier != 'free'
        return self.subscription_tier != 'free'
    
    def update_rating(self):
        """Update vendor rating based on product reviews"""
        from products.models import ProductReview
        reviews = ProductReview.objects.filter(product__vendor=self.user, is_active=True)
        if reviews.exists():
            self.rating_avg = reviews.aggregate(Avg('rating'))['rating__avg'] or 0
            self.total_reviews = reviews.count()
            self.save()
    
    def update_followers_count(self):
        """Update followers count"""
        self.followers_count = self.followers.count()
        self.save()
    
    def get_badges(self):
        """Get all applicable badges for this vendor"""
        badges = []
        if self.is_verified:
            badges.append({'text': 'Verified', 'color': 'green', 'icon': 'fa-check-circle'})
        if self.is_top_rated:
            badges.append({'text': 'Top Rated', 'color': 'yellow', 'icon': 'fa-star'})
        if self.is_best_seller:
            badges.append({'text': 'Best Seller', 'color': 'orange', 'icon': 'fa-trophy'})
        if self.is_trusted:
            badges.append({'text': 'Trusted', 'color': 'blue', 'icon': 'fa-shield-alt'})
        if self.has_active_subscription():
            badge = self.get_subscription_display()
            badges.append({'text': badge['text'], 'color': badge['color'], 'icon': badge['icon']})
        return badges

class VendorFollow(BaseModel):
    """Track users who follow vendors"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='following_vendors')
    vendor = models.ForeignKey(VendorProfile, on_delete=models.CASCADE, related_name='followers')
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['user', 'vendor']
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.user.username} follows {self.vendor.store_name}"

class VendorSubscriptionPlan(BaseModel):
    """Vendor subscription plans for premium features"""
    TIER_CHOICES = [
        ('basic', 'Basic'),
        ('premium', 'Premium'),
        ('enterprise', 'Enterprise'),
        ('featured', 'Featured'),
    ]
    
    tier = models.CharField(max_length=20, choices=TIER_CHOICES, unique=True)
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    price_monthly = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    price_yearly = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    # Features
    product_limit = models.IntegerField(default=10)
    featured_products = models.IntegerField(default=0)
    priority_support = models.BooleanField(default=False)
    analytics_access = models.BooleanField(default=False)
    promoted_listing = models.BooleanField(default=False)
    dedicated_account_manager = models.BooleanField(default=False)
    
    # Display
    icon = models.CharField(max_length=50, default='fa-store')
    color = models.CharField(max_length=50, default='blue')
    is_popular = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    order = models.IntegerField(default=0)
    
    class Meta:
        ordering = ['order', 'price_monthly']
    
    def __str__(self):
        return f"{self.name} - ${self.price_monthly}/mo"
    
    def get_features_list(self):
        features = []
        if self.product_limit:
            features.append(f"Up to {self.product_limit} products")
        if self.featured_products:
            features.append(f"{self.featured_products} featured product slots")
        if self.priority_support:
            features.append("Priority support")
        if self.analytics_access:
            features.append("Advanced analytics")
        if self.promoted_listing:
            features.append("Promoted listing")
        if self.dedicated_account_manager:
            features.append("Dedicated account manager")
        return features

class VendorSubscription(BaseModel):
    """Active vendor subscriptions"""
    vendor = models.ForeignKey(User, on_delete=models.CASCADE, related_name='active_subscriptions')
    plan = models.ForeignKey(VendorSubscriptionPlan, on_delete=models.CASCADE)
    start_date = models.DateTimeField(default=timezone.now)
    end_date = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    auto_renew = models.BooleanField(default=False)
    payment_method = models.CharField(max_length=50, blank=True)
    transaction_id = models.CharField(max_length=200, blank=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.vendor.username} - {self.plan.name}"
    
    def is_valid(self):
        return self.is_active and self.end_date >= timezone.now()
    
    def days_remaining(self):
        delta = self.end_date - timezone.now()
        return delta.days
    
    def activate(self):
        """Activate this subscription and update vendor profile"""
        self.is_active = True
        self.save()
        
        # Update vendor profile with subscription tier
        profile = self.vendor.vendor_profile
        profile.subscription_tier = self.plan.tier
        profile.subscription_expiry = self.end_date
        profile.priority_score = self.get_priority_score()
        profile.save()
    
    def get_priority_score(self):
        """Calculate priority score based on plan"""
        scores = {
            'basic': 100,
            'premium': 200,
            'enterprise': 300,
            'featured': 500,
        }
        return scores.get(self.plan.tier, 0)