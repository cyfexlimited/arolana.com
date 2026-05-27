from django.contrib import admin
from django.utils.html import format_html
from .models import VendorProfile, VendorSubscription, VendorReview

@admin.register(VendorProfile)
class VendorProfileAdmin(admin.ModelAdmin):
    list_display = ['store_name', 'user', 'is_verified', 'kyc_status', 'pickup_ready', 'subscription_tier', 'priority_score', 'rating_avg', 'total_sales', 'logo_preview']
    list_filter = ['is_verified', 'is_active', 'subscription_tier']
    search_fields = ['store_name', 'user__email']
    prepopulated_fields = {'store_slug': ['store_name']}
    readonly_fields = ['rating_avg', 'total_sales', 'followers_count', 'priority_score', 'pickup_map_preview']
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
            'fields': ('pickup_contact_name', 'pickup_phone', 'pickup_address', 'pickup_latitude', 'pickup_longitude', 'pickup_map_preview'),
            'description': 'Exact vendor pickup pin used for checkout pricing, nearby rider assignment, and rider navigation.'
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

    def pickup_ready(self, obj):
        if obj.pickup_location_is_ready:
            return format_html('<span style="color:#16a34a;font-weight:700;">Ready</span>')
        return format_html('<span style="color:#dc2626;font-weight:700;">Missing pin</span>')
    pickup_ready.short_description = 'Pickup'

    def pickup_map_preview(self, obj):
        if not obj or not obj.pickup_latitude or not obj.pickup_longitude:
            return "Add pickup latitude and longitude to preview the vendor pickup map."
        return format_html(
            '<div style="max-width:720px;border:1px solid #dbe3ef;border-radius:14px;overflow:hidden;background:#f8fafc;">'
            '<iframe title="Vendor pickup map" width="100%" height="320" style="border:0;display:block;" loading="lazy" '
            'src="https://www.google.com/maps?q={},{}&output=embed"></iframe>'
            '<div style="padding:10px 12px;font-weight:700;">'
            '<a target="_blank" rel="noopener" href="https://www.google.com/maps?q={},{}">Open vendor pickup in Google Maps</a>'
            '</div></div>',
            obj.pickup_latitude,
            obj.pickup_longitude,
            obj.pickup_latitude,
            obj.pickup_longitude,
        )
    pickup_map_preview.short_description = 'Pickup map preview'

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
