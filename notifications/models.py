from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
from core.models import BaseModel

User = get_user_model()

class Notification(BaseModel):
    NOTIFICATION_TYPES = [
        ('login', 'Login'),
        ('logout', 'Logout'),
        ('signup', 'Sign Up'),
        ('order', 'Order Update'),
        ('payment', 'Payment'),
        ('message', 'New Message'),
        ('review', 'New Review'),
        ('follow', 'New Follower'),
        ('vendor', 'Vendor Update'),
        ('system', 'System Alert'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    notification_type = models.CharField(max_length=20, choices=NOTIFICATION_TYPES, default='system')
    title = models.CharField(max_length=200)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    link = models.CharField(max_length=500, blank=True, help_text="URL to redirect when clicked")
    metadata = models.JSONField(default=dict, blank=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['user', 'is_read']),
        ]
    
    def __str__(self):
        return f"{self.user.username} - {self.title[:50]}"
    
    def mark_as_read(self):
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save()

class UserNotificationSettings(BaseModel):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='notification_settings')
    email_notifications = models.BooleanField(default=True)
    push_notifications = models.BooleanField(default=True)
    login_alerts = models.BooleanField(default=True)
    order_updates = models.BooleanField(default=True)
    marketing_emails = models.BooleanField(default=False)
    vendor_alerts = models.BooleanField(default=True)
    
    class Meta:
        verbose_name = 'User Notification Setting'
        verbose_name_plural = 'User Notification Settings'
    
    def __str__(self):
        return f"Settings for {self.user.username}"