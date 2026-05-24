from django.contrib import admin
from django.utils.html import format_html
from .models import VendorProfile, VendorSubscription, VendorReview

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
        ('Delivery Pickup Location', {
            'fields': ('pickup_contact_name', 'pickup_phone', 'pickup_address', 'pickup_latitude', 'pickup_longitude'),
            'description': 'Used to calculate checkout delivery from this vendor/store to the customer address.'
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


@admin.register(VendorReview)
class VendorReviewAdmin(admin.ModelAdmin):
    list_display = ['vendor', 'user', 'rating', 'is_verified_customer', 'is_active', 'created_at']
    list_filter = ['rating', 'is_verified_customer', 'is_active', 'created_at']
    search_fields = ['vendor__store_name', 'user__email', 'user__username', 'title', 'comment']
    readonly_fields = ['created_at', 'updated_at', 'helpful_count']
    actions = ['approve_reviews', 'hide_reviews']

    def approve_reviews(self, request, queryset):
        queryset.update(is_active=True)
        for review in queryset.select_related('vendor'):
            review.vendor.update_rating()
        self.message_user(request, f'{queryset.count()} vendor review(s) approved.')
    approve_reviews.short_description = 'Approve selected vendor reviews'

    def hide_reviews(self, request, queryset):
        queryset.update(is_active=False)
        for review in queryset.select_related('vendor'):
            review.vendor.update_rating()
        self.message_user(request, f'{queryset.count()} vendor review(s) hidden.')
    hide_reviews.short_description = 'Hide selected vendor reviews'
