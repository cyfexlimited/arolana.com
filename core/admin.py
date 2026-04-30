from django.contrib import admin
from django.utils.html import format_html
from .models import SiteSettings, PromoBanner

@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    list_display = ['site_name', 'site_tagline', 'is_active', 'logo_preview']
    list_editable = ['is_active']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('site_name', 'site_tagline', 'site_description', 'site_keywords', 'is_active')
        }),
        ('Branding', {
            'fields': ('site_logo', 'site_favicon', 'footer_logo'),
        }),
        ('Contact Information', {
            'fields': ('contact_email', 'contact_phone', 'address'),
        }),
        ('Social Media Links', {
            'fields': ('facebook_url', 'twitter_url', 'instagram_url', 'linkedin_url', 'youtube_url'),
            'classes': ('collapse',)
        }),
        ('Colors & Styling', {
            'fields': ('primary_color', 'secondary_color'),
        }),
        ('Footer Content', {
            'fields': ('footer_copyright', 'shipping_note', 'return_policy', 'warranty_note'),
            'classes': ('collapse',)
        }),
        ('SEO & Meta', {
            'fields': ('meta_author', 'meta_robots'),
            'classes': ('collapse',)
        }),
    )
    
    def logo_preview(self, obj):
        if obj.site_logo:
            return format_html('<img src="{}" width="50" height="50" style="border-radius: 4px;" />', obj.site_logo.url)
        return "No Logo"
    logo_preview.short_description = 'Logo Preview'
    
    def has_delete_permission(self, request, obj=None):
        return False

@admin.register(PromoBanner)
class PromoBannerAdmin(admin.ModelAdmin):
    list_display = ['title', 'button_text', 'order', 'is_active', 'preview']
    list_editable = ['order', 'is_active']
    list_filter = ['is_active']
    search_fields = ['title']
    
    fieldsets = (
        ('Content', {
            'fields': ('title', 'subtitle', 'button_text', 'button_url')
        }),
        ('Styling', {
            'fields': ('background_color_start', 'background_color_end', 'image')
        }),
        ('Settings', {
            'fields': ('order', 'is_active')
        }),
    )
    
    def preview(self, obj):
        return format_html(
            '<div style="background: linear-gradient(to right, {}, {}); padding: 10px; border-radius: 8px; color: white; text-align: center; max-width: 200px;">'
            '<strong>{}</strong><br><small>{}</small>'
            '</div>',
            obj.background_color_start, obj.background_color_end, obj.title, (obj.subtitle[:50] if obj.subtitle else '')
        )
    preview.short_description = 'Preview'

# Custom Admin Site
class CustomAdminSite(admin.AdminSite):
    def each_context(self, request):
        context = super().each_context(request)
        context['site_header'] = 'Arolana Admin'
        context['site_title'] = 'Arolana Admin Panel'
        return context

# Create admin site instance
admin_site = CustomAdminSite(name='admin')

# Register your models with the custom admin site
from django.contrib.auth.models import Group, User
admin_site.register(Group)
admin_site.register(User)