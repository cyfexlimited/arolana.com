from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html

from vendors.models import VendorProfile

from .models import (
    SubscriptionPlan,
    VendorSubscription,
    apply_vendor_subscription_benefits,
)
from .services import enforce_vendor_product_visibility


def sync_vendor_subscription_profile(user):
    profile = getattr(user, 'vendor_profile', None)
    if not profile:
        return None

    current = (
        VendorSubscription.objects
        .filter(vendor=user, is_active=True, end_date__gt=timezone.now())
        .select_related('plan')
        .order_by('-end_date', '-created_at')
        .first()
    )
    if current:
        profile.subscription_active = True
        profile.subscription_started_at = current.start_date
        profile.subscription_expires_at = current.end_date
        profile.subscription_expiry = current.end_date
        profile.save(update_fields=[
            'subscription_active',
            'subscription_started_at',
            'subscription_expires_at',
            'subscription_expiry',
            'updated_at',
        ])
        apply_vendor_subscription_benefits(profile, current.plan)
    else:
        profile.subscription_active = False
        profile.subscription_started_at = None
        profile.subscription_expires_at = None
        profile.subscription_expiry = None
        profile.save(update_fields=[
            'subscription_active',
            'subscription_started_at',
            'subscription_expires_at',
            'subscription_expiry',
            'updated_at',
        ])
        apply_vendor_subscription_benefits(profile, 'free')

    enforce_vendor_product_visibility(profile)
    return profile

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

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        profiles = VendorProfile.objects.filter(
            subscription_tier=obj.tier_key,
            subscription_active=True,
        ).select_related('user')
        synced = 0
        for profile in profiles:
            apply_vendor_subscription_benefits(profile, obj)
            synced += 1
        if synced:
            self.message_user(
                request,
                f"Updated visibility and benefits for {synced} active vendor(s) on this plan.",
            )

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
            delta = obj.end_date - timezone.now()
            return f"{delta.days} days"
        return "-"
    days_remaining.short_description = 'Days Left'

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        sync_vendor_subscription_profile(obj.vendor)

    def delete_model(self, request, obj):
        vendor = obj.vendor
        super().delete_model(request, obj)
        sync_vendor_subscription_profile(vendor)

    def delete_queryset(self, request, queryset):
        vendors = list(queryset.values_list('vendor_id', flat=True).distinct())
        super().delete_queryset(request, queryset)
        for profile in VendorProfile.objects.filter(
            user_id__in=vendors
        ).select_related('user'):
            sync_vendor_subscription_profile(profile.user)
