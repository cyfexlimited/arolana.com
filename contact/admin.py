from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone
from .models import ContactMessage

@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ['subject', 'name', 'email', 'vendor_short', 'created_at', 'is_read', 'replied']
    list_filter = ['is_read', 'replied', 'created_at']
    search_fields = ['name', 'email', 'subject', 'message']
    readonly_fields = ['created_at', 'ip_address', 'user_agent']
    
    fieldsets = (
        ('Message Information', {
            'fields': ('name', 'email', 'subject', 'message')
        }),
        ('Vendor Information', {
            'fields': ('vendor',)
        }),
        ('User Information', {
            'fields': ('user', 'ip_address', 'user_agent')
        }),
        ('Status', {
            'fields': ('is_read', 'replied', 'replied_at', 'reply_message')
        }),
        ('Metadata', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )
    
    actions = ['mark_as_read', 'mark_as_unread']
    
    def vendor_short(self, obj):
        if obj.vendor:
            return obj.vendor.store_name
        return "-"
    vendor_short.short_description = 'Vendor'
    
    def mark_as_read(self, request, queryset):
        updated = queryset.update(is_read=True)
        self.message_user(request, f'{updated} message(s) marked as read.')
    mark_as_read.short_description = "Mark selected messages as read"
    
    def mark_as_unread(self, request, queryset):
        updated = queryset.update(is_read=False)
        self.message_user(request, f'{updated} message(s) marked as unread.')
    mark_as_unread.short_description = "Mark selected messages as unread"
    
    def save_model(self, request, obj, form, change):
        if 'replied' in form.changed_data and obj.replied and not obj.replied_at:
            obj.replied_at = timezone.now()
        super().save_model(request, obj, form, change)

# Register the app in admin
admin.site.site_header = "Arolana Admin"
admin.site.site_title = "Arolana Admin Portal"
admin.site.index_title = "Welcome to Arolana Admin Dashboard"
