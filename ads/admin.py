from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from .models import (
    AdPlacement, AdCampaign, AdCreative, AdBanner, 
    AdImpression, AdClick, AdConversion, AdAnalytics, Advertisement,
    AdvertiserIdentity, CampaignAsset, ExternalAdvertisingAccount,
    AdvertisingCredential, AdvertisingOAuthState, AdvertisingConnectionAuditLog,
    AdChannelExecution, AdChannelReportingSnapshot, AdEvent, AdAttribution
)


class OptionalColorFieldAdminMixin:
    optional_color_fields = set()

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        formfield = super().formfield_for_dbfield(db_field, request, **kwargs)
        if db_field.name in self.optional_color_fields and formfield:
            formfield.widget.attrs.update({
                'placeholder': '#2563eb',
                'style': 'max-width: 9rem;',
            })
        return formfield


@admin.register(AdPlacement)
class AdPlacementAdmin(admin.ModelAdmin):
    list_display = ['name', 'placement_type', 'width', 'height', 'is_active', 'priority']
    list_filter = ['placement_type', 'is_active']
    search_fields = ['name', 'description']
    prepopulated_fields = {'slug': ('name',)}
    readonly_fields = ['created_at', 'updated_at']
    fieldsets = (
        ('Basic Info', {'fields': ('name', 'slug', 'placement_type', 'description')}),
        ('Dimensions', {'fields': ('width', 'height')}),
        ('Targeting', {'fields': ('allowed_devices', 'allowed_countries', 'min_visit_count', 'requires_login')}),
        ('Settings', {'fields': ('is_active', 'priority', 'rotation_weight', 'max_impressions_per_session')}),
    )

@admin.register(AdCampaign)
class AdCampaignAdmin(admin.ModelAdmin):
    list_display = ['name', 'campaign_id', 'advertiser_identity', 'objective', 'campaign_type', 'status', 'approved', 'budget_status', 'performance_metrics']
    list_filter = ['status', 'campaign_type', 'objective', 'approved', 'advertiser_identity__owner_type']
    search_fields = ['name', 'campaign_id', 'advertiser_identity__display_name']
    readonly_fields = ['campaign_id', 'spent', 'impressions', 'clicks', 'ctr', 'quality_score', 
                       'created_at', 'updated_at', 'start_date', 'approved_at']
    
    fieldsets = (
        ('Campaign Info', {'fields': ('name', 'campaign_id', 'campaign_type', 'objective', 'advertiser_identity')}),
        ('Budget', {'fields': ('budget_type', 'daily_budget', 'total_budget', 'spent', 'bid_strategy', 'target_cpa', 'max_bid')}),
        ('Schedule', {'fields': ('start_date', 'end_date', 'timezone', 'dayparting')}),
        ('Targeting', {'fields': ('targeting', 'geo_targeting', 'device_targeting', 'browser_targeting', 'os_targeting', 'interest_targeting', 'custom_segments')}),
        ('Frequency Capping', {'fields': ('impressions_per_user', 'clicks_per_user', 'frequency_cap')}),
        ('Conversion Tracking', {'fields': ('conversion_value', 'conversion_rate', 'roas')}),
        ('Tracking', {'fields': ('utm_source', 'utm_medium', 'utm_campaign')}),
        ('Status', {'fields': ('status', 'approved', 'approved_by', 'approved_at')}),
    )
    actions = ['approve_campaigns', 'reject_campaigns', 'pause_campaigns']
    
    def budget_status(self, obj):
        percentage = float(obj.budget_used_percentage)
        color = 'green' if percentage < 80 else 'orange' if percentage < 95 else 'red'
        return mark_safe(f'<span style="color: {color}">{percentage:.1f}% used</span>')
    budget_status.short_description = 'Budget Used'
    
    def performance_metrics(self, obj):
        ctr_val = float(obj.ctr)
        quality_val = str(obj.quality_score)
        return mark_safe(f'<div><strong>CTR:</strong> {ctr_val:.2f}%<br><strong>Quality:</strong> {quality_val}</div>')
    performance_metrics.short_description = 'Performance'

    def approve_campaigns(self, request, queryset):
        updated = queryset.update(approved=True, status='active')
        self.message_user(request, f"{updated} campaign(s) approved.")
    approve_campaigns.short_description = "Approve selected campaigns"

    def reject_campaigns(self, request, queryset):
        updated = queryset.update(approved=False, status='rejected')
        self.message_user(request, f"{updated} campaign(s) rejected.")
    reject_campaigns.short_description = "Reject selected campaigns"

    def pause_campaigns(self, request, queryset):
        updated = queryset.update(status='paused')
        self.message_user(request, f"{updated} campaign(s) paused.")
    pause_campaigns.short_description = "Pause selected campaigns"

@admin.register(AdCreative)
class AdCreativeAdmin(OptionalColorFieldAdminMixin, admin.ModelAdmin):
    optional_color_fields = {'cta_background_color', 'cta_text_color'}
    list_display = ['name', 'campaign', 'creative_type', 'headline', 'ctr_display', 'is_active']
    list_filter = ['creative_type', 'is_active']
    search_fields = ['name', 'headline']
    readonly_fields = ['impressions', 'clicks', 'ctr', 'created_at', 'updated_at']
    fieldsets = (
        ('Campaign', {'fields': ('campaign', 'name', 'creative_type')}),
        ('Content', {'fields': ('headline', 'description', 'cta_text', ('cta_background_color', 'cta_text_color'))}),
        ('Media', {'fields': ('image', 'image_mobile', 'video_url', 'html_content')}),
        ('Carousel & Dynamic', {'fields': ('carousel_items', 'dynamic_fields'), 'classes': ('collapse',)}),
        ('Tracking', {'fields': ('clickthrough_url', 'tracking_url')}),
        ('A/B Testing', {'fields': ('ab_variant', 'ab_weight')}),
        ('Performance', {'fields': ('impressions', 'clicks', 'ctr'), 'classes': ('collapse',)}),
        ('Publishing', {'fields': ('is_active',)}),
    )
    
    def ctr_display(self, obj):
        return f"{float(obj.ctr):.2f}%" if float(obj.ctr) > 0 else "0%"
    ctr_display.short_description = 'CTR'

@admin.register(AdBanner)
class AdBannerAdmin(OptionalColorFieldAdminMixin, admin.ModelAdmin):
    optional_color_fields = {'cta_background_color', 'cta_text_color'}
    list_display = ['title', 'campaign', 'placement', 'banner_size', 'priority', 'performance', 'is_active']
    list_filter = ['is_active', 'priority', 'placement', 'animation']
    search_fields = ['title', 'description']
    readonly_fields = ['impressions', 'clicks', 'ctr', 'conversion_rate', 'created_at', 'updated_at']
    autocomplete_fields = ['campaign', 'creative', 'placement']
    fieldsets = (
        ('Campaign & Placement', {
            'fields': ('campaign', 'creative', 'placement')
        }),
        ('Content', {
            'fields': ('title', 'description', 'cta_text', 'cta_url', ('cta_background_color', 'cta_text_color'), 'alt_text')
        }),
        ('Media', {
            'fields': ('image', 'image_mobile', 'video_url')
        }),
        ('Size, Fit & Focal Position', {
            'fields': (
                ('width_override', 'height_override'),
                ('mobile_width_override', 'mobile_height_override'),
                ('image_fit', 'image_position'),
                ('mobile_image_fit', 'mobile_image_position'),
            ),
            'description': 'Leave size overrides empty to use the selected placement dimensions.'
        }),
        ('Animation & Effects', {
            'fields': ('animation', 'hover_effect'),
            'classes': ('collapse',)
        }),
        ('Schedule & Status', {
            'fields': ('priority', 'start_date', 'end_date', 'is_active')
        }),
        ('Performance', {
            'fields': ('impressions', 'clicks', 'ctr', 'conversion_rate'),
            'classes': ('collapse',)
        }),
    )

    def banner_size(self, obj):
        width = obj.width_override or (obj.placement.width if obj.placement else 1200)
        height = obj.height_override or (obj.placement.height if obj.placement else 320)
        return f"{width}x{height}"
    banner_size.short_description = 'Size'
    
    def performance(self, obj):
        if obj.impressions > 0:
            ctr_val = float(obj.ctr)
            return mark_safe(
                f'<span style="color: {"green" if ctr_val > 2 else "orange"}">{ctr_val:.2f}% CTR</span>'
            )
        return "No data"
    performance.short_description = 'Performance'

@admin.register(AdImpression)
class AdImpressionAdmin(admin.ModelAdmin):
    list_display = ['banner', 'campaign', 'device_type', 'country', 'was_visible', 'short_timestamp']
    list_filter = ['device_type', 'was_visible', 'browser', 'country']
    search_fields = ['session_id', 'ip_address', 'impression_id']
    readonly_fields = ['impression_id', 'timestamp']
    date_hierarchy = 'timestamp'
    
    def short_timestamp(self, obj):
        return obj.timestamp.strftime('%Y-%m-%d %H:%M')
    short_timestamp.short_description = 'Time'

@admin.register(AdClick)
class AdClickAdmin(admin.ModelAdmin):
    list_display = ['banner', 'campaign', 'device_type', 'converted', 'is_bot', 'short_timestamp']
    list_filter = ['converted', 'is_bot', 'device_type', 'browser']
    search_fields = ['click_id', 'session_id', 'ip_address']
    readonly_fields = ['click_id', 'timestamp']
    date_hierarchy = 'timestamp'
    
    def short_timestamp(self, obj):
        return obj.timestamp.strftime('%Y-%m-%d %H:%M')
    short_timestamp.short_description = 'Time'

@admin.register(AdConversion)
class AdConversionAdmin(admin.ModelAdmin):
    list_display = ['click', 'campaign', 'conversion_type', 'value', 'short_timestamp']
    list_filter = ['conversion_type', 'timestamp']
    search_fields = ['order_id']
    readonly_fields = ['timestamp']
    
    def short_timestamp(self, obj):
        return obj.timestamp.strftime('%Y-%m-%d %H:%M')
    short_timestamp.short_description = 'Time'

@admin.register(AdAnalytics)
class AdAnalyticsAdmin(admin.ModelAdmin):
    list_display = ['campaign', 'date', 'impressions', 'clicks', 'conversions', 'roas_display', 'roi_display']
    list_filter = ['date']
    readonly_fields = ['ctr', 'conversion_rate', 'cpc', 'cpm', 'roas', 'roi']
    
    def roas_display(self, obj):
        return f"{float(obj.roas):.2f}x"
    roas_display.short_description = 'ROAS'
    
    def roi_display(self, obj):
        return f"{float(obj.roi):.1f}%"
    roi_display.short_description = 'ROI'

@admin.register(Advertisement)
class AdvertisementAdmin(OptionalColorFieldAdminMixin, admin.ModelAdmin):
    optional_color_fields = {'button_background_color', 'button_text_color'}
    list_display = ['title', 'placement', 'views', 'clicks', 'ctr_display', 'is_active', 'is_featured']
    list_filter = ['placement', 'is_featured', 'is_active', 'show_to_logged_in', 'show_to_guests']
    search_fields = ['title', 'description', 'target_audience']
    readonly_fields = ['views', 'clicks', 'ctr', 'created_at', 'updated_at']
    fieldsets = (
        ('Content', {
            'fields': ('title', 'description', 'image', 'url', 'button_text', ('button_background_color', 'button_text_color'))
        }),
        ('Placement', {
            'fields': ('placement', 'is_featured')
        }),
        ('Schedule', {
            'fields': ('start_date', 'end_date')
        }),
        ('Targeting', {
            'fields': ('target_audience', 'show_to_logged_in', 'show_to_guests')
        }),
        ('Status & Analytics', {
            'fields': ('is_active', 'views', 'clicks', 'ctr')
        })
    )
    actions = ['activate_ads', 'deactivate_ads']
    
    def activate_ads(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f"{updated} advertisement(s) activated.")
    activate_ads.short_description = "Activate selected advertisements"
    
    def deactivate_ads(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"{updated} advertisement(s) deactivated.")
    deactivate_ads.short_description = "Deactivate selected advertisements"
    
    def ctr_display(self, obj):
        return f"{float(obj.ctr):.2f}%" if float(obj.ctr) > 0 else "0%"
    ctr_display.short_description = 'CTR'


@admin.register(AdvertiserIdentity)
class AdvertiserIdentityAdmin(admin.ModelAdmin):
    list_display = ['display_name', 'owner_type', 'vendor', 'provider', 'user', 'is_active']
    list_filter = ['owner_type', 'is_active']
    search_fields = ['display_name', 'vendor__store_name', 'provider__business_name', 'user__username']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(CampaignAsset)
class CampaignAssetAdmin(admin.ModelAdmin):
    list_display = ['campaign', 'asset_type', 'advertiser_identity', 'title', 'object_id', 'is_active']
    list_filter = ['asset_type', 'is_active']
    search_fields = ['title', 'campaign__name', 'advertiser_identity__display_name']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(ExternalAdvertisingAccount)
class ExternalAdvertisingAccountAdmin(admin.ModelAdmin):
    list_display = ['display_name', 'channel', 'advertiser_identity', 'status', 'last_sync_at']
    list_filter = ['channel', 'status', 'is_active']
    search_fields = ['display_name', 'external_account_id', 'advertiser_identity__display_name']
    readonly_fields = ['created_at', 'updated_at', 'connected_at', 'last_sync_at']
    exclude = []


@admin.register(AdvertisingCredential)
class AdvertisingCredentialAdmin(admin.ModelAdmin):
    list_display = ['external_account', 'provider', 'access_token_expires_at', 'refresh_token_expires_at', 'revoked_at', 'credential_version']
    list_filter = ['provider', 'revoked_at']
    search_fields = ['external_account__display_name', 'external_account__external_account_id']
    readonly_fields = ['external_account', 'provider', 'access_token_expires_at', 'refresh_token_expires_at', 'revoked_at', 'credential_version', 'scopes', 'metadata', 'created_at', 'updated_at']
    exclude = ['encrypted_access_token', 'encrypted_refresh_token']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(AdvertisingOAuthState)
class AdvertisingOAuthStateAdmin(admin.ModelAdmin):
    list_display = ['provider', 'advertiser_identity', 'user', 'expires_at', 'used_at']
    list_filter = ['provider', 'expires_at', 'used_at']
    search_fields = ['advertiser_identity__display_name', 'user__username']
    readonly_fields = ['provider', 'advertiser_identity', 'user', 'session_key', 'expires_at', 'used_at', 'redirect_uri', 'metadata', 'created_at', 'updated_at']
    exclude = ['state']

    def has_add_permission(self, request):
        return False


@admin.register(AdvertisingConnectionAuditLog)
class AdvertisingConnectionAuditLogAdmin(admin.ModelAdmin):
    list_display = ['provider', 'event_type', 'advertiser_identity', 'external_account', 'user', 'status', 'created_at']
    list_filter = ['provider', 'event_type', 'status']
    search_fields = ['advertiser_identity__display_name', 'external_account__display_name', 'user__username', 'message']
    readonly_fields = ['provider', 'event_type', 'advertiser_identity', 'external_account', 'user', 'status', 'message', 'metadata', 'created_at', 'updated_at']

    def has_add_permission(self, request):
        return False


@admin.register(AdChannelExecution)
class AdChannelExecutionAdmin(admin.ModelAdmin):
    list_display = ['campaign', 'channel', 'advertiser_identity', 'status', 'external_status', 'budget_allocation', 'currency', 'last_synced_at']
    list_filter = ['channel', 'status', 'is_active']
    search_fields = ['campaign__name', 'external_campaign_id', 'advertiser_identity__display_name']
    readonly_fields = ['created_at', 'updated_at', 'last_synced_at']


@admin.register(AdChannelReportingSnapshot)
class AdChannelReportingSnapshotAdmin(admin.ModelAdmin):
    list_display = ['execution', 'provider', 'reporting_start', 'reporting_end', 'impressions', 'clicks', 'spend', 'currency']
    list_filter = ['provider', 'reporting_start', 'reporting_end']
    search_fields = ['execution__campaign__name', 'execution__external_campaign_id']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(AdEvent)
class AdEventAdmin(admin.ModelAdmin):
    list_display = ['event_uuid', 'event_type', 'campaign', 'asset', 'event_source', 'occurred_at']
    list_filter = ['event_type', 'event_source', 'occurred_at']
    search_fields = ['event_uuid', 'session_id', 'request_id']
    readonly_fields = ['event_uuid', 'created_at', 'updated_at']
    date_hierarchy = 'occurred_at'


@admin.register(AdAttribution)
class AdAttributionAdmin(admin.ModelAdmin):
    list_display = ['source_event', 'advertiser_identity', 'campaign', 'attribution_type', 'lifecycle_status', 'revenue_amount', 'net_revenue_amount', 'currency', 'created_at']
    list_filter = ['attribution_type', 'lifecycle_status', 'currency']
    search_fields = ['source_event__event_uuid', 'campaign__name', 'advertiser_identity__display_name']
    readonly_fields = ['created_at', 'updated_at']
