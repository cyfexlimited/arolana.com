from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils import timezone
from django.db.models import Count, Q
from .models import Notification, NotificationPreference

@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    # Add the actual field to list_display so it can be editable
    list_display = ['user_badge', 'title_preview', 'notification_type_badge', 'priority_badge', 
                    'is_read', 'time_ago', 'action_buttons']
    list_filter = ['notification_type', 'is_read', 'priority', 'created_at']
    search_fields = ['title', 'message', 'user__username', 'user__email']
    readonly_fields = ['created_at', 'updated_at', 'read_at', 'metadata_display']
    list_editable = ['is_read']  # This is an actual field and is in list_display
    list_per_page = 25
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('user', 'notification_type', 'priority', 'title', 'message')
        }),
        ('Status', {
            'fields': ('is_read', 'read_at', 'is_archived', 'archived_at'),
            'classes': ('collapse',)
        }),
        ('Delivery', {
            'fields': ('email_sent', 'email_sent_at', 'push_sent', 'push_sent_at'),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('link', 'metadata_display'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def user_badge(self, obj):
        """Display user with avatar and link"""
        avatar_url = obj.user.avatar.url if hasattr(obj.user, 'avatar') and obj.user.avatar else None
        if avatar_url:
            return format_html(
                '<div style="display:flex;align-items:center;gap:8px;">'
                '<img src="{}" style="width:32px;height:32px;border-radius:999px;object-fit:cover;">'
                '<a href="{}" target="_blank">{}</a></div>',
                avatar_url, reverse('admin:accounts_user_change', args=[obj.user.id]), obj.user.username
            )
        return format_html(
            '<a href="{}" target="_blank">{}</a>',
            reverse('admin:accounts_user_change', args=[obj.user.id]), obj.user.username
        )
    user_badge.short_description = 'User'
    user_badge.admin_order_field = 'user__username'
    
    def title_preview(self, obj):
        """Truncate long titles"""
        return obj.title[:60] + '...' if len(obj.title) > 60 else obj.title
    title_preview.short_description = 'Title'
    title_preview.admin_order_field = 'title'
    
    def notification_type_badge(self, obj):
        """Display type with colored badge"""
        colors = {
            'cart': ('#dbeafe', '#1d4ed8'),
            'order': ('#d1fae5', '#047857'),
            'payment': ('#ede9fe', '#6d28d9'),
            'message': ('#fef3c7', '#92400e'),
            'review': ('#ffedd5', '#c2410c'),
            'vendor': ('#e0e7ff', '#4338ca'),
            'product': ('#ccfbf1', '#0f766e'),
            'promotion': ('#fce7f3', '#be185d'),
            'shipping': ('#cffafe', '#0e7490'),
            'system': ('#f1f5f9', '#475569'),
            'security': ('#fee2e2', '#b91c1c'),
            'wishlist': ('#fee2e2', '#be123c'),
            'follow': ('#d1fae5', '#047857'),
            'achievement': ('#fef3c7', '#a16207'),
            'reminder': ('#dbeafe', '#1d4ed8'),
            'newsletter': ('#ede9fe', '#6d28d9'),
            'success': ('#d1fae5', '#047857'),
            'error': ('#fee2e2', '#b91c1c'),
            'warning': ('#fef3c7', '#92400e'),
            'info': ('#dbeafe', '#1d4ed8'),
        }
        bg, fg = colors.get(obj.notification_type, ('#f1f5f9', '#475569'))
        return format_html(
            '<span style="background:{};color:{};padding:4px 8px;border-radius:999px;font-size:11px;font-weight:700;">{}</span>',
            bg, fg, obj.get_notification_type_display().split()[0] if obj.get_notification_type_display() else obj.notification_type
        )
    notification_type_badge.short_description = 'Type'
    notification_type_badge.admin_order_field = 'notification_type'
    
    def priority_badge(self, obj):
        """Display priority with color-coded badge"""
        colors = {
            1: ('#f1f5f9', '#475569'),
            2: ('#dbeafe', '#1d4ed8'),
            3: ('#fef3c7', '#92400e'),
            4: ('#fee2e2', '#b91c1c'),
        }
        bg, fg = colors.get(obj.priority, ('#f1f5f9', '#475569'))
        return format_html(
            '<span style="background:{};color:{};padding:4px 8px;border-radius:999px;font-size:11px;font-weight:800;">P{}</span>',
            bg, fg, obj.priority
        )
    priority_badge.short_description = 'Priority'
    priority_badge.admin_order_field = 'priority'
    
    def time_ago(self, obj):
        """Display time ago with tooltip"""
        return format_html(
            '<span title="{}">{}</span>',
            obj.created_at.strftime('%Y-%m-%d %H:%M:%S') if obj.created_at else '',
            obj.time_ago
        )
    time_ago.short_description = 'Created'
    time_ago.admin_order_field = 'created_at'
    
    def metadata_display(self, obj):
        """Display metadata as formatted JSON"""
        if obj.metadata:
            import json
            return format_html(
                '<pre style="background:#f8fafc;border:1px solid #e5e7eb;border-radius:8px;max-height:180px;overflow:auto;padding:10px;font-size:12px;">{}</pre>',
                json.dumps(obj.metadata, indent=2)
            )
        return '-'
    metadata_display.short_description = 'Metadata'
    
    def action_buttons(self, obj):
        """Display action buttons"""
        return format_html(
            '<div style="display:flex;gap:6px;flex-wrap:wrap;">'
            '<a href="{}" style="background:#2563eb;color:#fff;border-radius:6px;padding:4px 8px;font-size:12px;" target="_blank">'
            '<i class="fas fa-eye"></i> View</a>'
            '<a href="{}" style="background:#059669;color:#fff;border-radius:6px;padding:4px 8px;font-size:12px;">'
            '<i class="fas fa-edit"></i> Edit</a>'
            '</div>',
            reverse('admin:notifications_notification_change', args=[obj.id]),
            reverse('admin:notifications_notification_change', args=[obj.id]),
        )
    action_buttons.short_description = 'Actions'
    
    actions = ['mark_as_read', 'mark_as_unread', 'archive_selected', 'delete_old_notifications']
    
    def mark_as_read(self, request, queryset):
        count = queryset.update(is_read=True, read_at=timezone.now())
        self.message_user(request, f"✅ {count} notifications marked as read.")
    mark_as_read.short_description = "📖 Mark selected as read"
    
    def mark_as_unread(self, request, queryset):
        count = queryset.update(is_read=False, read_at=None)
        self.message_user(request, f"📭 {count} notifications marked as unread.")
    mark_as_unread.short_description = "📭 Mark selected as unread"
    
    def archive_selected(self, request, queryset):
        count = queryset.update(is_archived=True, archived_at=timezone.now())
        self.message_user(request, f"📦 {count} notifications archived.")
    archive_selected.short_description = "📦 Archive selected"
    
    def delete_old_notifications(self, request, queryset):
        days = 30
        cutoff = timezone.now() - timezone.timedelta(days=days)
        count = queryset.filter(created_at__lt=cutoff).count()
        queryset.filter(created_at__lt=cutoff).delete()
        self.message_user(request, f"🗑️ Deleted {count} notifications older than {days} days.")
    delete_old_notifications.short_description = "🗑️ Delete notifications older than 30 days"
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user')
    
    class Media:
        css = {
            'all': ('https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css',)
        }


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    # Use the correct model name: NotificationPreference
    list_display = ['user_link', 'email_notifications', 'push_notifications', 
                    'cart_updates', 'order_updates', 'promotions_display',
                    'vendor_alerts_display', 'quiet_hours_display', 'dnd_status']
    list_editable = ['email_notifications', 'push_notifications', 'cart_updates', 'order_updates']
    search_fields = ['user__username', 'user__email']
    list_filter = ['email_notifications', 'push_notifications', 'quiet_hours_enabled', 'do_not_disturb']
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        ('User Information', {
            'fields': ('user',)
        }),
        ('Notification Channels', {
            'fields': ('email_notifications', 'push_notifications', 'sound_enabled', 'desktop_notifications'),
            'description': 'Choose how you want to receive notifications'
        }),
        ('Notification Types', {
            'fields': ('cart_updates', 'order_updates', 'promotions', 'vendor_alerts', 
                      'security_alerts', 'product_updates', 'review_alerts', 'message_alerts'),
            'description': 'Select which types of notifications you want to receive'
        }),
        ('Quiet Hours & Do Not Disturb', {
            'fields': ('quiet_hours_enabled', 'quiet_hours_start', 'quiet_hours_end', 
                      'do_not_disturb', 'dnd_until'),
            'classes': ('collapse',),
            'description': 'Configure quiet hours and do not disturb mode'
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )
    
    def user_link(self, obj):
        return format_html(
            '<a href="{}" target="_blank">{}</a>',
            reverse('admin:accounts_user_change', args=[obj.user.id]), obj.user.username
        )
    user_link.short_description = 'User'
    user_link.admin_order_field = 'user__username'
    
    def promotions_display(self, obj):
        """Display promotions with colored badge (read-only)"""
        icon = '✅' if obj.promotions else '❌'
        bg, fg = ('#d1fae5', '#047857') if obj.promotions else ('#fee2e2', '#b91c1c')
        return format_html(
            '<span style="background:{};color:{};padding:4px 8px;border-radius:999px;font-size:11px;font-weight:700;">{} Promos</span>',
            bg, fg, icon
        )
    promotions_display.short_description = 'Promotions'
    
    def vendor_alerts_display(self, obj):
        """Display vendor alerts with colored badge (read-only)"""
        icon = '✅' if obj.vendor_alerts else '❌'
        bg, fg = ('#d1fae5', '#047857') if obj.vendor_alerts else ('#fee2e2', '#b91c1c')
        return format_html(
            '<span style="background:{};color:{};padding:4px 8px;border-radius:999px;font-size:11px;font-weight:700;">{} Vendor</span>',
            bg, fg, icon
        )
    vendor_alerts_display.short_description = 'Vendor Alerts'
    
    def quiet_hours_display(self, obj):
        if obj.quiet_hours_enabled:
            return format_html(
                '<span class="text-blue-600">🔕 {} - {}</span>',
                obj.quiet_hours_start.strftime('%I:%M %p') if obj.quiet_hours_start else '--:--',
                obj.quiet_hours_end.strftime('%I:%M %p') if obj.quiet_hours_end else '--:--'
            )
        return format_html('<span class="text-gray-400">Disabled</span>')
    quiet_hours_display.short_description = 'Quiet Hours'
    
    def dnd_status(self, obj):
        if obj.do_not_disturb:
            if obj.dnd_until and obj.dnd_until > timezone.now():
                return format_html(
                    '<span class="text-orange-600">🔇 Until {}</span>',
                    obj.dnd_until.strftime('%Y-%m-%d %H:%M')
                )
            return format_html('<span class="text-orange-600">🔇 Enabled</span>')
        return format_html('<span class="text-gray-400">Off</span>')
    dnd_status.short_description = 'DND'
    
    actions = ['enable_email_for_all', 'disable_email_for_all', 'reset_to_defaults']
    
    def enable_email_for_all(self, request, queryset):
        count = queryset.update(email_notifications=True)
        self.message_user(request, f"✅ Email notifications enabled for {count} users.")
    enable_email_for_all.short_description = "📧 Enable email for selected"
    
    def disable_email_for_all(self, request, queryset):
        count = queryset.update(email_notifications=False)
        self.message_user(request, f"❌ Email notifications disabled for {count} users.")
    disable_email_for_all.short_description = "📧 Disable email for selected"
    
    def reset_to_defaults(self, request, queryset):
        for settings in queryset:
            settings.email_notifications = True
            settings.push_notifications = True
            settings.cart_updates = True
            settings.order_updates = True
            settings.promotions = False
            settings.vendor_alerts = True
            settings.save()
        self.message_user(request, f"🔄 Reset settings to defaults for {queryset.count()} users.")
    reset_to_defaults.short_description = "🔄 Reset to default settings"
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user')
    
    class Media:
        css = {
            'all': ('https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css',)
        }
