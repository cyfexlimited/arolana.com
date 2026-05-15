from django.contrib import admin
from django.utils.html import format_html
from .models import VendorProfile, VendorSubscription

@admin.register(VendorProfile)
class VendorProfileAdmin(admin.ModelAdmin):
    list_display = ['store_name', 'user', 'is_verified', 'kyc_status', 'subscription_tier', 'priority_score', 'rating_avg', 'total_sales', 'logo_preview']
    list_filter = ['is_verified', 'is_active', 'subscription_tier']
    search_fields = ['store_name', 'user__email']
    prepopulated_fields = {'store_slug': ['store_name']}
    readonly_fields = ['rating_avg', 'total_sales', 'followers_count', 'priority_score']
    actions = ['mark_verified', 'mark_unverified']

    fieldsets = (
        ('Store', {
            'fields': ('user', 'store_name', 'store_slug', 'description', 'store_logo', 'store_banner')
        }),
        ('Verification', {
            'fields': ('is_verified', 'verification_documents')
        }),
        ('Subscription Controls', {
            'fields': ('subscription_tier', 'subscription_expiry', 'priority_score')
        }),
        ('Performance', {
            'fields': ('rating_avg', 'total_sales', 'total_reviews', 'followers_count', 'response_time', 'fulfillment_rate', 'return_rate')
        }),
        ('Badges', {
            'fields': ('is_top_rated', 'is_best_seller', 'is_trusted')
        }),
        ('Status', {
            'fields': ('is_active',)
        }),
    )
    
    def logo_preview(self, obj):
        if obj.store_logo:
            return format_html('<img src="{}" width="50" height="50" style="border-radius: 50%;" />', obj.store_logo.url)
        return "No Logo"
    logo_preview.short_description = 'Logo'

    def mark_verified(self, request, queryset):
        queryset.update(is_verified=True)
        self.message_user(request, f'{queryset.count()} seller profile(s) marked verified.')
    mark_verified.short_description = 'Mark selected sellers verified'

    def mark_unverified(self, request, queryset):
        queryset.update(is_verified=False)
        self.message_user(request, f'{queryset.count()} seller profile(s) marked unverified.')
    mark_unverified.short_description = 'Mark selected sellers unverified'

@admin.register(VendorSubscription)
class VendorSubscriptionAdmin(admin.ModelAdmin):
    list_display = ['vendor', 'plan', 'start_date', 'end_date', 'is_active']
    list_filter = ['plan', 'is_active']
    search_fields = ['vendor__username']
