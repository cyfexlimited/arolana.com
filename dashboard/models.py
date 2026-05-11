from django.db import models
from django.conf import settings
from django.utils import timezone
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

class VendorAdminMessage(BaseModel):
    """Messages between admin and vendors"""
    MESSAGE_TYPES = [
        ('general', 'General'),
        ('product_approval', 'Product Approval'),
        ('product_update', 'Product Update'),
        ('payment', 'Payment'),
        ('dispute', 'Dispute'),
        ('announcement', 'Announcement'),
    ]
    
    STATUS_CHOICES = [
        ('unread', 'Unread'),
        ('read', 'Read'),
        ('replied', 'Replied'),
        ('resolved', 'Resolved'),
    ]
    
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='dashboard_sent_messages'
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='dashboard_received_messages'
    )
    subject = models.CharField(max_length=200)
    message = models.TextField()
    message_type = models.CharField(max_length=20, choices=MESSAGE_TYPES, default='general')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='unread')
    
    # Optional link to specific product
    product = models.ForeignKey('products.Product', on_delete=models.SET_NULL, null=True, blank=True)
    
    # For replies
    parent_message = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='replies')
    
    read_at = models.DateTimeField(null=True, blank=True)
    
    # Soft delete fields
    is_deleted_by_sender = models.BooleanField(default=False)
    is_deleted_by_recipient = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.sender.username} -> {self.recipient.username}: {self.subject[:50]}"
    
    def mark_as_read(self):
        if not self.read_at:
            self.read_at = timezone.now()
            self.status = 'read'
            self.save()
    
    def delete_for_user(self, user):
        """Delete message for specific user (soft delete)"""
        if user == self.sender:
            self.is_deleted_by_sender = True
        elif user == self.recipient:
            self.is_deleted_by_recipient = True
        else:
            return False
        
        self.deleted_at = timezone.now()
        self.save()
        
        # If both have deleted, hard delete
        if self.is_deleted_by_sender and self.is_deleted_by_recipient:
            self.delete()
        
        return True
    
    def is_visible_for_user(self, user):
        """Check if message is visible for user"""
        if user == self.sender and self.is_deleted_by_sender:
            return False
        if user == self.recipient and self.is_deleted_by_recipient:
            return False
        return True


class VendorNotification(BaseModel):
    """Notifications for vendors"""
    NOTIFICATION_TYPES = [
        ('product_approved', 'Product Approved'),
        ('product_rejected', 'Product Rejected'),
        ('product_changes', 'Product Changes Required'),
        ('order_new', 'New Order'),
        ('order_shipped', 'Order Shipped'),
        ('payment_received', 'Payment Received'),
        ('message', 'New Message'),
        ('announcement', 'Announcement'),
    ]
    
    vendor = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='dashboard_vendor_notifications'
    )
    title = models.CharField(max_length=200)
    message = models.TextField()
    notification_type = models.CharField(max_length=30, choices=NOTIFICATION_TYPES)
    is_read = models.BooleanField(default=False)
    action_url = models.CharField(max_length=200, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.vendor.username}: {self.title[:50]}"