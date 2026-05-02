from django.contrib import admin
from django.utils.html import format_html
from .models import HeroBanner, HeroBannerAnalytics

@admin.register(HeroBanner)
class HeroBannerAdmin(admin.ModelAdmin):
    list_display = ['title', 'display_order', 'is_active', 'image_preview', 'views_count', 'clicks_count']
    list_editable = ['display_order', 'is_active']
    list_filter = ['is_active']
    search_fields = ['title']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('title', 'subtitle', 'description', 'display_order', 'is_active')
        }),
        ('Media', {
            'fields': ('image_desktop', 'image_tablet', 'image_mobile'),
            'description': 'Upload images here. Desktop image is required.'
        }),
        ('Animation', {
            'fields': ('animation_effect', 'animation_duration', 'autoplay_delay'),
            'classes': ('collapse',)
        }),
        ('Buttons', {
            'fields': (('button1_text', 'button1_url', 'button1_style'), 
                      ('button2_text', 'button2_url', 'button2_style'))
        }),
        ('Styling', {
            'fields': ('overlay_color', 'overlay_opacity', 'text_color', 'text_alignment', 'content_position'),
            'classes': ('collapse',)
        }),
        ('Scheduling', {
            'fields': ('start_date', 'end_date'),
            'classes': ('collapse',)
        }),
    )
    
    def image_preview(self, obj):
        if obj.image_desktop:
            return format_html('<img src="{}" width="80" height="45" style="object-fit: cover; border-radius: 4px;" />', obj.image_desktop.url)
        return "No Image"
    image_preview.short_description = 'Preview'

@admin.register(HeroBannerAnalytics)
class HeroBannerAnalyticsAdmin(admin.ModelAdmin):
    list_display = ['banner', 'action', 'timestamp']
    list_filter = ['action', 'banner']
    readonly_fields = ['banner', 'session_id', 'user', 'action', 'timestamp']
    
    def has_add_permission(self, request):
        return False