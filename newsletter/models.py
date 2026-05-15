from django.db import models
from django.conf import settings
from core.models import BaseModel

class NewsletterSubscriber(BaseModel):
    """Unified newsletter subscriber model"""
    email = models.EmailField(unique=True)
    name = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True)
    subscribed_at = models.DateTimeField(auto_now_add=True)
    unsubscribed_at = models.DateTimeField(null=True, blank=True)
    
    # Source tracking
    source = models.CharField(max_length=50, choices=[
        ('homepage', 'Homepage'),
        ('blog', 'Blog'),
        ('footer', 'Footer'),
        ('checkout', 'Checkout'),
        ('other', 'Other'),
    ], default='homepage')
    
    # Preferences
    preferences = models.JSONField(default=dict, blank=True, help_text="User preferences for newsletters")
    
    class Meta:
        ordering = ['-subscribed_at']
        verbose_name = "Newsletter Subscriber"
        verbose_name_plural = "Newsletter Subscribers"
    
    def __str__(self):
        return self.email
    
    def unsubscribe(self):
        self.is_active = False
        from django.utils import timezone
        self.unsubscribed_at = timezone.now()
        self.save()

class NewsletterCampaign(BaseModel):
    """Newsletter campaigns"""
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('scheduled', 'Scheduled'),
        ('sending', 'Sending'),
        ('sent', 'Sent'),
        ('cancelled', 'Cancelled'),
    ]

    RECIPIENT_CHOICES = [
        ('subscribers', 'Active newsletter subscribers'),
        ('registered', 'Registered user emails'),
        ('all', 'Subscribers and registered users'),
    ]

    FREQUENCY_CHOICES = [
        ('once', 'One time'),
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly'),
        ('custom', 'Custom schedule'),
    ]
    
    name = models.CharField(max_length=200)
    subject = models.CharField(max_length=200)
    content = models.TextField()
    html_content = models.TextField(blank=True, help_text="HTML version of the newsletter")
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    recipient_scope = models.CharField(max_length=20, choices=RECIPIENT_CHOICES, default='all')
    send_frequency = models.CharField(max_length=20, choices=FREQUENCY_CHOICES, default='once')
    scheduled_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    last_sent_at = models.DateTimeField(null=True, blank=True)
    
    # Statistics
    sent_count = models.IntegerField(default=0)
    open_count = models.IntegerField(default=0)
    click_count = models.IntegerField(default=0)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.name} - {self.subject}"


class EmailAudienceMember(BaseModel):
    """Unified admin email box for registered users and newsletter subscribers."""
    SOURCE_CHOICES = [
        ('registered', 'Registered user'),
        ('newsletter', 'Newsletter subscriber'),
        ('both', 'Registered and newsletter'),
        ('manual', 'Manual'),
    ]

    email = models.EmailField(unique=True)
    name = models.CharField(max_length=200, blank=True)
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='manual')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='email_audience_memberships')
    subscriber = models.ForeignKey(NewsletterSubscriber, on_delete=models.SET_NULL, null=True, blank=True, related_name='audience_memberships')
    is_active = models.BooleanField(default=True)
    accepts_promos = models.BooleanField(default=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['email']
        verbose_name = 'Email Audience Member'
        verbose_name_plural = 'Email Audience'

    def __str__(self):
        return self.email

class NewsletterTracking(BaseModel):
    """Track newsletter opens and clicks"""
    campaign = models.ForeignKey(NewsletterCampaign, on_delete=models.CASCADE, related_name='tracking')
    subscriber = models.ForeignKey(NewsletterSubscriber, on_delete=models.CASCADE, related_name='tracking')
    opened_at = models.DateTimeField(null=True, blank=True)
    clicked_at = models.DateTimeField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    
    class Meta:
        unique_together = ['campaign', 'subscriber']
    
    def __str__(self):
        return f"{self.subscriber.email} - {self.campaign.name}"
