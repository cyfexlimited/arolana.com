from django.contrib import admin
from django.utils.html import format_html, mark_safe
from django.urls import reverse
from django.db.models import Sum
from .models import AdPlacement, AdCampaign, AdBanner, AdImpression, AdClick


class AdBannerInline(admin.TabularInline):
    model = AdBanner
    extra = 1
    fields = ['title', 'image', 'placement', 'cta_url', 'priority', 'is_active', 'preview']
    readonly_fields = ['preview']
    show_change_link = True

    def preview(self, obj):
        if obj.image:
            return format_html('<img src="{}" width="60" style="border-radius:4px;" />', obj.image.url)
        return "No image"


@admin.register(AdPlacement)
class AdPlacementAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'size', 'ad_count', 'is_active']
    list_editable = ['is_active']
    list_filter = ['is_active']
    search_fields = ['name', 'slug']
    prepopulated_fields = {'slug': ['name']}

    def size(self, obj):
        return f"{obj.width}x{obj.height}"
    
    def ad_count(self, obj):
        return obj.banners.filter(is_active=True).count()


@admin.register(AdCampaign)
class AdCampaignAdmin(admin.ModelAdmin):
    list_display = ['name', 'campaign_id', 'status_badge', 'budget', 'spent', 'impressions', 'clicks', 'ctr_display']
    list_filter = ['status', 'approved', 'campaign_type']
    search_fields = ['name', 'campaign_id']
    readonly_fields = ['campaign_id', 'spent', 'impressions', 'clicks', 'ctr']
    inlines = [AdBannerInline]

    def status_badge(self, obj):
        if obj.status == 'active' and obj.approved:
            html = '<span style="background:#10b981; color:white; padding:2px 8px; border-radius:12px;">● Active</span>'
        elif obj.status == 'paused':
            html = '<span style="background:#f97316; color:white; padding:2px 8px; border-radius:12px;">⏸ Paused</span>'
        else:
            html = f'<span style="background:#ef4444; color:white; padding:2px 8px; border-radius:12px;">● {obj.get_status_display()}</span>'
        return mark_safe(html)
    status_badge.short_description = "Status"

    def ctr_display(self, obj):
        if obj.impressions > 0:
            return f"{(obj.clicks / obj.impressions * 100):.2f}%"
        return "0%"
    ctr_display.short_description = "CTR"

    actions = ['approve_campaigns', 'pause_campaigns', 'activate_campaigns']

    def approve_campaigns(self, request, queryset):
        queryset.update(approved=True, status='active')
    approve_campaigns.short_description = "Approve"

    def pause_campaigns(self, request, queryset):
        queryset.update(status='paused')
    pause_campaigns.short_description = "Pause"

    def activate_campaigns(self, request, queryset):
        queryset.update(status='active')
    activate_campaigns.short_description = "Activate"


@admin.register(AdBanner)
class AdBannerAdmin(admin.ModelAdmin):
    list_display = ['title', 'campaign', 'placement', 'priority', 'image_preview', 'impressions', 'clicks', 'is_active']
    list_filter = ['campaign__campaign_type', 'placement', 'is_active']
    search_fields = ['title']
    list_editable = ['priority', 'is_active']
    readonly_fields = ['impressions', 'clicks', 'ctr']

    def image_preview(self, obj):
        if obj.image:
            return format_html('<img src="{}" width="50" style="border-radius:4px;" />', obj.image.url)
        return "No Image"
    image_preview.short_description = "Preview"


@admin.register(AdImpression)
class AdImpressionAdmin(admin.ModelAdmin):
    list_display = ['banner', 'campaign', 'timestamp']
    list_filter = ['timestamp']
    readonly_fields = ['banner', 'campaign', 'user', 'session_id', 'ip_address', 'user_agent', 'timestamp']
    
    def has_add_permission(self, request):
        return False


@admin.register(AdClick)
class AdClickAdmin(admin.ModelAdmin):
    list_display = ['banner', 'campaign', 'timestamp']
    list_filter = ['timestamp']
    readonly_fields = ['banner', 'campaign', 'user', 'session_id', 'ip_address', 'user_agent', 'timestamp']
    
    def has_add_permission(self, request):
        return False


admin.site.site_header = "Arolana Ad Manager"
