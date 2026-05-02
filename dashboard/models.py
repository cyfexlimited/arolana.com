from django.db import models

# Create your models here.
from django.db import models
from core.models import BaseModel
from accounts.models import User
from products.models import Product, Category
from orders.models import Order
from vendors.models import VendorProfile

class DashboardWidget(BaseModel):
    """Customizable dashboard widgets"""
    WIDGET_TYPES = [
        ('stats', 'Statistics Card'),
        ('chart', 'Chart'),
        ('table', 'Data Table'),
        ('activity', 'Activity Feed'),
        ('map', 'Map'),
        ('custom', 'Custom HTML'),
    ]
    
    title = models.CharField(max_length=100)
    widget_type = models.CharField(max_length=20, choices=WIDGET_TYPES)
    position = models.IntegerField(default=0)
    width = models.CharField(max_length=10, choices=[('full', 'Full Width'), ('half', 'Half Width'), ('third', 'One Third')], default='half')
    settings = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    roles = models.CharField(max_length=200, blank=True, help_text="Comma-separated role names")
    
    class Meta:
        ordering = ['position']
    
    def __str__(self):
        return self.title

class AdminActivityLog(BaseModel):
    """Track admin actions"""
    ACTION_TYPES = [
        ('create', 'Create'),
        ('update', 'Update'),
        ('delete', 'Delete'),
        ('login', 'Login'),
        ('logout', 'Logout'),
        ('export', 'Export'),
        ('import', 'Import'),
    ]
    
    admin = models.ForeignKey(User, on_delete=models.CASCADE, related_name='admin_actions')
    action_type = models.CharField(max_length=20, choices=ACTION_TYPES)
    model_name = models.CharField(max_length=100)
    object_id = models.CharField(max_length=50, blank=True)
    object_repr = models.CharField(max_length=200, blank=True)
    changes = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = "Admin Activity Logs"
    
    def __str__(self):
        return f"{self.admin.username} - {self.action_type} - {self.model_name}"

class SystemAlert(BaseModel):
    """System alerts and notifications"""
    ALERT_LEVELS = [
        ('info', 'Info'),
        ('warning', 'Warning'),
        ('error', 'Error'),
        ('success', 'Success'),
    ]
    
    title = models.CharField(max_length=200)
    message = models.TextField()
    level = models.CharField(max_length=20, choices=ALERT_LEVELS, default='info')
    is_read = models.BooleanField(default=False)
    is_dismissed = models.BooleanField(default=False)
    link = models.CharField(max_length=500, blank=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return self.title
