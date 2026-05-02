from django.db import models
from core.models import BaseModel
from accounts.models import User
from django.utils import timezone

class SubscriptionPlan(BaseModel):
    """Subscription plans for vendors"""
    name = models.CharField(max_length=50, unique=True)
    display_name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    
    # Pricing
    price_monthly = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    price_yearly = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    # Features
    max_products = models.IntegerField(default=10)
    featured_products = models.IntegerField(default=0)
    commission_rate = models.DecimalField(max_digits=5, decimal_places=2, default=10.00)
    
    # Benefits
    priority_support = models.BooleanField(default=False)
    analytics_access = models.BooleanField(default=False)
    promotion_opportunities = models.BooleanField(default=False)
    dedicated_account_manager = models.BooleanField(default=False)
    
    # Display
    icon = models.CharField(max_length=50, blank=True)
    color = models.CharField(max_length=20, default='gray')
    is_popular = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    order = models.IntegerField(default=0)
    
    class Meta:
        ordering = ['order', 'price_monthly']
    
    def __str__(self):
        return self.display_name

class VendorSubscription(BaseModel):
    """Vendor's active subscription"""
    vendor = models.ForeignKey(User, on_delete=models.CASCADE, related_name='subscriptions')
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.CASCADE)
    start_date = models.DateTimeField(default=timezone.now)
    end_date = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    auto_renew = models.BooleanField(default=True)
    payment_method = models.CharField(max_length=50, blank=True)
    transaction_id = models.CharField(max_length=200, blank=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.vendor.username} - {self.plan.display_name}"
