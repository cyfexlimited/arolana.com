from django.contrib import admin
from django.utils.html import format_html
from .models import AdPlacement, AdCampaign, AdBanner

@admin.register(AdPlacement)
class AdPlacementAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'width', 'height', 'is_active']
    prepopulated_fields = {'slug': ['name']}
    list_editable = ['is_active']
    list_filter = ['is_active']
    search_fields = ['name']

@admin.register(AdCampaign)
class AdCampaignAdmin(admin.ModelAdmin):
    list_display = ['name', 'start_date', 'end_date', 'is_running', 'banner_count', 'is_active']
    list_filter = ['is_active', 'start_date', 'end_date']
    search_fields = ['name']
    list_editable = ['is_active']
    
    def banner_count(self, obj):
        return obj.banners.filter(is_active=True).count()
    banner_count.short_description = 'Active Banners'
    
    def is_running(self, obj):
        return obj.is_running()
    is_running.boolean = True
    is_running.short_description = 'Running'

@admin.register(AdBanner)
class AdBannerAdmin(admin.ModelAdmin):
    list_display = ['title', 'placement', 'campaign', 'priority', 'impressions', 'clicks', 'ctr_display', 'image_preview', 'is_active']
    list_filter = ['placement', 'campaign', 'is_active']
    search_fields = ['title', 'description']
    list_editable = ['priority', 'is_active']
    readonly_fields = ['impressions', 'clicks']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('title', 'description', 'placement', 'campaign')
        }),
        ('Media', {
            'fields': ('image',)
        }),
        ('Links', {
            'fields': ('url', 'button_text')
        }),
        ('Settings', {
            'fields': ('priority', 'is_active')
        }),
        ('Statistics', {
            'fields': ('impressions', 'clicks'),
            'classes': ('collapse',)
        }),
    )
    
    def image_preview(self, obj):
        if obj.image:
            return format_html('<img src="{}" width="100" height="auto" style="border-radius: 4px;" />', obj.image.url)
        return "No Image"
    image_preview.short_description = 'Preview'
    
    def ctr_display(self, obj):
        return f"{obj.ctr:.2f}%"
    ctr_display.short_description = 'CTR'
