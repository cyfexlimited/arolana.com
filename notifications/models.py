from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
from core.models import BaseModel
from django.db.models import Q
import json
from django.utils.timesince import timesince

User = get_user_model()

class Notification(BaseModel):
    NOTIFICATION_TYPES = [
        ('cart', '🛒 Cart Update'),
        ('order', '📦 Order Update'),
        ('payment', '💰 Payment'),
        ('message', '💬 New Message'),
        ('review', '⭐ New Review'),
        ('vendor', '🏪 Vendor Update'),
        ('product', '📱 Product Update'),
        ('promotion', '🎉 Promotion'),
        ('shipping', '🚚 Shipping Update'),
        ('system', '⚙️ System Alert'),
        ('security', '🔒 Security Alert'),
        ('wishlist', '❤️ Wishlist'),
        ('follow', '👥 New Follower'),
        ('achievement', '🏆 Achievement'),
        ('reminder', '⏰ Reminder'),
        ('newsletter', '📰 Newsletter'),
        ('success', 'Success'),
        ('error', 'Error'),
        ('warning', 'Warning'),
        ('info', 'Information'),
    ]
    
    PRIORITY_LEVELS = [
        (1, 'Low'),
        (2, 'Normal'),
        (3, 'High'),
        (4, 'Urgent'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    notification_type = models.CharField(max_length=20, choices=NOTIFICATION_TYPES, default='system')
    priority = models.IntegerField(choices=PRIORITY_LEVELS, default=2, help_text="Notification priority level")
    title = models.CharField(max_length=200)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    is_archived = models.BooleanField(default=False, help_text="Archive instead of delete")
    archived_at = models.DateTimeField(null=True, blank=True)
    link = models.CharField(max_length=500, blank=True, help_text="URL to redirect when clicked")
    metadata = models.JSONField(default=dict, blank=True, help_text="Additional data like product_id, order_id")
    
    # For email notifications
    email_sent = models.BooleanField(default=False)
    email_sent_at = models.DateTimeField(null=True, blank=True)
    
    # For push notifications
    push_sent = models.BooleanField(default=False)
    push_sent_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-priority', '-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['user', 'is_read']),
            models.Index(fields=['notification_type']),
            models.Index(fields=['priority']),
            models.Index(fields=['user', 'is_archived']),
        ]
    
    def __str__(self):
        return f"{self.user.username} - {self.title[:50]}"
    
    def mark_as_read(self):
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=['is_read', 'read_at'])
    
    def archive(self):
        if not self.is_archived:
            self.is_archived = True
            self.archived_at = timezone.now()
            self.save(update_fields=['is_archived', 'archived_at'])
    
    @property
    def time_ago(self):
        delta = timezone.now() - self.created_at
        if delta.days > 30:
            return f"{delta.days // 30} month{'s' if delta.days // 30 > 1 else ''} ago"
        elif delta.days > 0:
            return f"{delta.days} day{'s' if delta.days > 1 else ''} ago"
        elif delta.seconds > 3600:
            hours = delta.seconds // 3600
            return f"{hours} hour{'s' if hours > 1 else ''} ago"
        elif delta.seconds > 60:
            minutes = delta.seconds // 60
            return f"{minutes} minute{'s' if minutes > 1 else ''} ago"
        else:
            return "Just now"
    
    @property
    def priority_class(self):
        classes = {
            1: 'bg-gray-100 text-gray-600',
            2: 'bg-blue-100 text-blue-600',
            3: 'bg-orange-100 text-orange-600',
            4: 'bg-red-100 text-red-600 animate-pulse',
        }
        return classes.get(self.priority, 'bg-gray-100 text-gray-600')
    
    @property
    def icon_class(self):
        icons = {
            'cart': 'fa-shopping-cart',
            'order': 'fa-truck',
            'payment': 'fa-credit-card',
            'message': 'fa-envelope',
            'review': 'fa-star',
            'vendor': 'fa-store',
            'product': 'fa-box',
            'promotion': 'fa-tag',
            'shipping': 'fa-shipping-fast',
            'system': 'fa-cog',
            'security': 'fa-shield-alt',
            'wishlist': 'fa-heart',
            'follow': 'fa-user-plus',
            'achievement': 'fa-trophy',
            'reminder': 'fa-bell',
            'newsletter': 'fa-newspaper',
        }
        return icons.get(self.notification_type, 'fa-bell')
    
    @property
    def icon_color(self):
        colors = {
            'cart': 'blue',
            'order': 'green',
            'payment': 'purple',
            'message': 'yellow',
            'review': 'orange',
            'vendor': 'indigo',
            'product': 'teal',
            'promotion': 'pink',
            'shipping': 'cyan',
            'system': 'gray',
            'security': 'red',
            'wishlist': 'red',
            'follow': 'green',
            'achievement': 'yellow',
            'reminder': 'blue',
            'newsletter': 'purple',
        }
        return colors.get(self.notification_type, 'gray')
    
    @classmethod
    def send(cls, user, notification_type, title, message, link='', metadata=None, priority=2):
        """Create and send notification"""
        return cls.objects.create(
            user=user,
            notification_type=notification_type,
            title=title,
            message=message,
            link=link,
            metadata=metadata or {},
            priority=priority
        )
    
    @classmethod
    def cart_update(cls, user, product_name, quantity, action='updated'):
        return cls.send(
            user=user,
            notification_type='cart',
            title='Cart Updated',
            message=f'{product_name} quantity {action} to {quantity}',
            link='/products/cart/',
            metadata={'product_name': product_name, 'quantity': quantity}
        )
    
    @classmethod
    def order_created(cls, user, order_number):
        return cls.send(
            user=user,
            notification_type='success',
            title='Order Created',
            message=f'Order #{order_number} has been created successfully',
            link=f'/orders/{order_number}/',
            metadata={'order_number': order_number}
        )
    
    @classmethod
    def order_shipped(cls, user, order_number, tracking_number):
        return cls.send(
            user=user,
            notification_type='shipping',
            title='Order Shipped',
            message=f'Order #{order_number} has been shipped. Tracking: {tracking_number}',
            link=f'/orders/{order_number}/track/',
            metadata={'order_number': order_number, 'tracking_number': tracking_number}
        )
    
    @classmethod
    def create_cart_notification(cls, user, product_name, quantity, action='added'):
        if action == 'added':
            title = 'Added to Cart 🛒'
            message = f'{product_name} added to your cart'
            priority = 2
        elif action == 'updated':
            title = 'Cart Updated 🔄'
            message = f'{product_name} quantity updated to {quantity}'
            priority = 2
        else:
            title = 'Cart Update'
            message = f'{product_name} removed from cart'
            priority = 1
        
        return cls.send(
            user=user,
            notification_type='cart',
            title=title,
            message=message,
            link='/products/cart/',
            metadata={'product_name': product_name, 'quantity': quantity},
            priority=priority
        )
    
    @classmethod
    def bulk_create(cls, users, notification_type, title, message, link='', metadata=None):
        """Create notifications for multiple users"""
        notifications = []
        for user in users:
            notifications.append(
                cls(
                    user=user,
                    notification_type=notification_type,
                    title=title,
                    message=message,
                    link=link,
                    metadata=metadata or {}
                )
            )
        return cls.objects.bulk_create(notifications)
    
    @classmethod
    def cleanup_old_notifications(cls, days=30):
        """Archive old notifications"""
        cutoff_date = timezone.now() - timezone.timedelta(days=days)
        old_notifications = cls.objects.filter(
            created_at__lt=cutoff_date,
            is_archived=False
        )
        count = old_notifications.count()
        for notification in old_notifications:
            notification.archive()
        return count


class NotificationPreference(BaseModel):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='notification_prefs')
    
    # Push notifications
    email_notifications = models.BooleanField(default=True)
    push_notifications = models.BooleanField(default=True)
    sound_enabled = models.BooleanField(default=True)
    desktop_notifications = models.BooleanField(default=True)
    
    # Type-specific settings
    cart_updates = models.BooleanField(default=True)
    order_updates = models.BooleanField(default=True)
    promotions = models.BooleanField(default=False)
    vendor_alerts = models.BooleanField(default=True)
    security_alerts = models.BooleanField(default=True)
    product_updates = models.BooleanField(default=False)
    review_alerts = models.BooleanField(default=True)
    message_alerts = models.BooleanField(default=True)
    
    # Quiet hours
    quiet_hours_enabled = models.BooleanField(default=False)
    quiet_hours_start = models.TimeField(default='22:00', help_text="Start of quiet hours")
    quiet_hours_end = models.TimeField(default='08:00', help_text="End of quiet hours")
    
    # Do not disturb
    do_not_disturb = models.BooleanField(default=False)
    dnd_until = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        verbose_name = 'Notification Preference'
        verbose_name_plural = 'Notification Preferences'
    
    def __str__(self):
        return f"Settings for {self.user.username}"
    
    def is_in_quiet_hours(self):
        """Check if current time is within quiet hours"""
        if not self.quiet_hours_enabled:
            return False
        
        now = timezone.now().time()
        if self.quiet_hours_start <= self.quiet_hours_end:
            return self.quiet_hours_start <= now <= self.quiet_hours_end
        else:
            return now >= self.quiet_hours_start or now <= self.quiet_hours_end


# Signal to create notification preferences for new users
from django.db.models.signals import post_save
from django.dispatch import receiver

@receiver(post_save, sender=User)
def create_user_notification_preferences(sender, instance, created, raw=False, **kwargs):
    if raw:
        return
    if created:
        NotificationPreference.objects.get_or_create(user=instance)
