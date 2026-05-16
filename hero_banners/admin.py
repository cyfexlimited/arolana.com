from django.contrib import admin
from django import forms
from django.utils.html import format_html
from .models import HeroBanner, HeroBannerAnalytics

class HeroBannerAdminForm(forms.ModelForm):
    class Meta:
        model = HeroBanner
        fields = '__all__'
        widgets = {
            'overlay_opacity': forms.NumberInput(attrs={
                'min': '0',
                'max': '1',
                'step': '0.05',
            }),
        }

@admin.register(HeroBanner)
class HeroBannerAdmin(admin.ModelAdmin):
    form = HeroBannerAdminForm
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
        ('Size, Fit & Focal Position', {
            'fields': (
                ('desktop_height', 'tablet_height', 'mobile_height'),
                ('image_fit_desktop', 'image_position_desktop'),
                ('image_fit_tablet', 'image_position_tablet'),
                ('image_fit_mobile', 'image_position_mobile'),
                'mobile_content_layout',
            ),
            'description': 'Control the banner frame size and how each image fills it. Use mobile image-only for a B&H-style mobile banner.'
        }),
        ('Animation', {
            'fields': ('animation_effect', 'animation_duration', 'autoplay_delay'),
            'classes': ('collapse',)
        }),
        ('Buttons', {
            'fields': (('button1_text', 'button1_url', 'button1_style'), 
                      ('button2_text', 'button2_url', 'button2_style'),
                      ('button3_text', 'button3_url', 'button3_style')),
            'description': 'Leave the button text or URL empty to hide that button. A # URL is treated as hidden.'
        }),
        ('Styling', {
            'fields': ('overlay_color', 'overlay_opacity', 'text_color', 'text_alignment', 'content_position'),
            'description': 'Overlay opacity is controlled here: 0 = no overlay, 1 = fully dark.',
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
