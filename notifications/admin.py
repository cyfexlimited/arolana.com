from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from .models import Notification, UserNotificationSettings

@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ['user', 'title', 'notification_type', 'is_read', 'created_at', 'view_link']
    list_filter = ['notification_type', 'is_read', 'created_at']
    search_fields = ['title', 'message', 'user__username']
    readonly_fields = ['created_at', 'updated_at']
    list_editable = ['is_read']
    
    def view_link(self, obj):
        """Create a clickable view link"""
        url = reverse('admin:notifications_notification_change', args=[obj.id])
        return format_html('<a href="{}" target="_blank">👁️ View</a>', url)
    view_link.short_description = 'Link'
    
    actions = ['mark_as_read', 'mark_as_unread', 'delete_selected']
    
    def mark_as_read(self, request, queryset):
        queryset.update(is_read=True)
        self.message_user(request, f"{queryset.count()} notifications marked as read.")
    mark_as_read.short_description = "Mark selected as read"
    
    def mark_as_unread(self, request, queryset):
        queryset.update(is_read=False)
        self.message_user(request, f"{queryset.count()} notifications marked as unread.")
    mark_as_unread.short_description = "Mark selected as unread"

@admin.register(UserNotificationSettings)
class UserNotificationSettingsAdmin(admin.ModelAdmin):
    list_display = ['user', 'email_notifications', 'push_notifications', 'login_alerts', 'order_updates']
    list_editable = ['email_notifications', 'push_notifications', 'login_alerts', 'order_updates']
    search_fields = ['user__username', 'user__email']
