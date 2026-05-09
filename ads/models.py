from django.db import models
from core.models import BaseModel
from django.utils import timezone

class AdPlacement(BaseModel):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    width = models.IntegerField(default=300)
    height = models.IntegerField(default=250)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['name']
    
    def __str__(self):
        return f"{self.name} ({self.width}x{self.height})"

class AdCampaign(BaseModel):
    name = models.CharField(max_length=200)
    campaign_id = models.CharField(max_length=50, unique=True, blank=True)
    campaign_type = models.CharField(max_length=20, choices=[
        ('sponsored', 'Sponsored Product'),
        ('display', 'Display Banner'),
        ('video', 'Video Ad'),
        ('native', 'Native Ad'),
    ], default='display')
    
    budget = models.DecimalField(max_digits=10, decimal_places=2, default=100.00)
    spent = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    cost_per_click = models.DecimalField(max_digits=10, decimal_places=2, default=0.50)
    cost_per_impression = models.DecimalField(max_digits=10, decimal_places=4, default=0.01)
    
    start_date = models.DateTimeField(default=timezone.now)
    end_date = models.DateTimeField(null=True, blank=True)
    
    targeting = models.CharField(max_length=20, choices=[
        ('all', 'All Visitors'),
        ('logged_in', 'Logged In Users'),
        ('guest', 'Guest Users'),
    ], default='all')
    
    sponsor_name = models.CharField(max_length=200, blank=True)
    sponsor_logo = models.ImageField(upload_to='ads/sponsors/', null=True, blank=True)
    sponsor_website = models.URLField(blank=True)
    
    impressions = models.IntegerField(default=0)
    clicks = models.IntegerField(default=0)
    ctr = models.FloatField(default=0.0)
    
    status = models.CharField(max_length=20, choices=[
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('paused', 'Paused'),
        ('completed', 'Completed'),
    ], default='draft')
    approved = models.BooleanField(default=False)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.name} - {self.status}"
    
    def save(self, *args, **kwargs):
        if not self.campaign_id:
            import random
            import string
            self.campaign_id = f"AD-{''.join(random.choices(string.ascii_uppercase + string.digits, k=8))}"
        super().save(*args, **kwargs)

class AdBanner(BaseModel):
    campaign = models.ForeignKey(AdCampaign, on_delete=models.CASCADE, related_name='banners')
    placement = models.ForeignKey(AdPlacement, on_delete=models.SET_NULL, null=True, related_name='banners')
    
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    
    image = models.ImageField(upload_to='ads/banners/', null=True, blank=True)
    mobile_image = models.ImageField(upload_to='ads/banners/mobile/', null=True, blank=True)
    video_url = models.URLField(blank=True)
    
    cta_text = models.CharField(max_length=50, default='Learn More')
    cta_url = models.URLField(blank=True, default='/products/')
    alt_text = models.CharField(max_length=200, blank=True)
    priority = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    
    impressions = models.IntegerField(default=0)
    clicks = models.IntegerField(default=0)
    ctr = models.FloatField(default=0.0)
    
    class Meta:
        ordering = ['-priority', '-created_at']
    
    def __str__(self):
        return f"{self.title} - {self.campaign.name}"
    
    def increment_click(self):
        self.clicks += 1
        self.campaign.clicks += 1
        self.ctr = (self.clicks / self.impressions * 100) if self.impressions > 0 else 0
        self.campaign.ctr = (self.campaign.clicks / self.campaign.impressions * 100) if self.campaign.impressions > 0 else 0
        self.save()
        self.campaign.save()
    
    def increment_impression(self):
        self.impressions += 1
        self.campaign.impressions += 1
        self.ctr = (self.clicks / self.impressions * 100) if self.impressions > 0 else 0
        self.campaign.ctr = (self.campaign.clicks / self.campaign.impressions * 100) if self.campaign.impressions > 0 else 0
        self.save()
        self.campaign.save()

class AdImpression(BaseModel):
    banner = models.ForeignKey(AdBanner, on_delete=models.CASCADE, related_name='impression_records')
    campaign = models.ForeignKey(AdCampaign, on_delete=models.CASCADE)
    user = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True)
    session_id = models.CharField(max_length=200, blank=True, null=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-timestamp']
    
    def __str__(self):
        return f"{self.banner.title} - {self.timestamp}"

class AdClick(BaseModel):
    banner = models.ForeignKey(AdBanner, on_delete=models.CASCADE, related_name='click_records')
    campaign = models.ForeignKey(AdCampaign, on_delete=models.CASCADE)
    user = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True)
    session_id = models.CharField(max_length=200, blank=True, null=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-timestamp']
    
    def __str__(self):
        return f"{self.banner.title} - Click at {self.timestamp}"
