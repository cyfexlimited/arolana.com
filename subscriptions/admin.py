from django.contrib import admin
from django.utils.html import format_html
from .models import SubscriptionPlan, VendorSubscription

@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = [
        'display_name', 'tier_key', 'price_monthly', 'max_products',
        'max_images_per_product', 'max_variants_per_product', 'priority_score',
        'commission_rate', 'chat_enabled', 'can_access_rfq', 'can_show_on_homepage',
        'is_popular', 'is_active', 'icon_preview'
    ]
    list_filter = ['is_active', 'is_popular']
    list_editable = [
        'price_monthly', 'max_products', 'max_images_per_product',
        'max_variants_per_product', 'priority_score', 'commission_rate',
        'is_popular', 'is_active'
    ]
    search_fields = ['display_name', 'description']
    ordering = ['order', 'price_monthly']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'display_name', 'description')
        }),
        ('Pricing', {
            'fields': ('price_monthly', 'price_yearly')
        }),
        ('Features', {
            'fields': (
                'max_products', 'featured_products',
                'max_images_per_product', 'max_variants_per_product',
                'commission_rate', 'feature_bullets'
            )
        }),
        ('Benefits', {
            'fields': (
                'can_upload_video', 'can_upload_pdf', 'can_upload_certificates',
                'can_access_rfq', 'can_receive_direct_enquiries',
                'can_use_boosting', 'can_show_on_homepage',
                'can_access_analytics', 'can_access_advanced_analytics',
                'can_access_ads', 'priority_support', 'analytics_access',
                'promotion_opportunities', 'dedicated_account_manager',
                'priority_score', 'support_level', 'badge_label'
            )
        }),
        ('Display Settings', {
            'fields': ('icon', 'color', 'is_popular', 'is_active', 'order')
        }),
    )
    
    def icon_preview(self, obj):
        if obj.icon:
            return format_html('<i class="{} fa-2x"></i>', obj.icon)
        return "-"
    icon_preview.short_description = 'Icon'

    def chat_enabled(self, obj):
        return obj.limits['chat_enabled']
    chat_enabled.boolean = True
    chat_enabled.short_description = 'Chat'

@admin.register(VendorSubscription)
class VendorSubscriptionAdmin(admin.ModelAdmin):
    list_display = ['vendor', 'plan', 'start_date', 'end_date', 'is_active', 'auto_renew', 'days_remaining']
    list_filter = ['plan', 'is_active', 'auto_renew']
    search_fields = ['vendor__username', 'vendor__email']
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        ('Subscription Info', {
            'fields': ('vendor', 'plan', 'start_date', 'end_date', 'is_active', 'auto_renew')
        }),
        ('Payment Info', {
            'fields': ('payment_method', 'transaction_id')
        }),
    )
    
    def days_remaining(self, obj):
        if obj.end_date:
            from django.utils import timezone
            delta = obj.end_date - timezone.now()
            return f"{delta.days} days"
        return "-"
    days_remaining.short_description = 'Days Left'
