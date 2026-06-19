from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html
from .models import (
    VendorBankAccount,
    VendorCallbackRequest,
    VendorFactoryPhoto,
    VendorLead,
    VendorProfile,
    VendorRFQ,
    VendorReview,
    VendorSubscription,
    VendorTransaction,
    VendorWallet,
    VendorWithdrawal,
)


class VendorFactoryPhotoInline(admin.TabularInline):
    model = VendorFactoryPhoto
    extra = 0

@admin.register(VendorProfile)
class VendorProfileAdmin(admin.ModelAdmin):
    list_display = ['store_name', 'user', 'vendor_type', 'approval_status', 'is_verified', 'manufacturer_verified', 'marketplace_location', 'direct_contact_status', 'kyc_status', 'pickup_ready', 'subscription_tier', 'subscription_active', 'subscription_expires_at', 'priority_score', 'profile_completion_display', 'rating_avg', 'total_sales', 'logo_preview', 'banner_preview']
    list_filter = ['vendor_type', 'approval_status', 'is_verified', 'manufacturer_verified', 'allow_phone_display', 'allow_whatsapp_display', 'allow_callback_requests', 'is_active', 'subscription_tier', 'subscription_active']
    search_fields = ['store_name', 'company_name', 'user__email', 'user__username', 'support_phone', 'business_phone', 'whatsapp_number', 'pickup_phone']
    prepopulated_fields = {'store_slug': ['store_name']}
    readonly_fields = ['rating_avg', 'total_sales', 'followers_count', 'priority_score', 'pickup_map_preview', 'approved_at', 'profile_completion_display', 'logo_preview', 'banner_preview', 'created_at', 'updated_at']
    inlines = [VendorFactoryPhotoInline]
    actions = ['approve_vendors', 'reject_vendors', 'suspend_vendors', 'activate_vendors', 'mark_verified', 'mark_unverified', 'mark_manufacturer_verified']

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        for field_name in ("address_line_1", "city", "state", "country"):
            if field_name in form.base_fields:
                form.base_fields[field_name].required = True
                form.base_fields[field_name].widget.attrs.setdefault("required", "required")
        return form

    fieldsets = (
        ('Business Identity', {
            'fields': ('user', 'store_name', 'store_slug', 'company_name', 'vendor_type', 'description', 'website', 'preferred_language', 'preferred_currency', 'profile_completion_display')
        }),
        ('Storefront Design', {
            'fields': ('store_slogan', 'storefront_accent_color', 'featured_categories', 'featured_products_note')
        }),
        ('Storefront Media', {
            'fields': ('store_logo', 'logo_preview', 'store_banner', 'banner_preview', 'store_video_url', 'store_gallery_notes')
        }),
        ('Address & Location', {
            'fields': ('address_line_1', 'city', 'state', 'country', 'business_address', 'manufacturer_address', 'warehouse_address')
        }),
        ('Policies & Support', {
            'fields': ('support_email', 'support_phone', 'business_phone', 'whatsapp_number', 'business_hours', 'return_policy', 'warranty_note', 'delivery_note')
        }),
        ('Manufacturer Profile', {
            'fields': (
                'factory_name', 'factory_video_url', 'years_in_business', 'number_of_employees',
                'production_capacity', 'quality_control_details', 'export_countries', 'main_product_categories',
            )
        }),
        ('Verification & Plan', {
            'fields': (
                'approval_status', 'approval_note', 'rejection_reason', 'approved_by', 'approved_at',
                'is_verified', 'verification_documents', 'manufacturer_verified', 'manufacturer_badge_label',
                'subscription_tier', 'subscription_active', 'subscription_started_at', 'subscription_expires_at', 'subscription_expiry',
                'product_limit', 'image_limit', 'variant_limit',
                'can_upload_video', 'can_upload_pdf', 'can_upload_certificates', 'can_access_rfq',
                'can_receive_direct_enquiries', 'can_use_boosting', 'can_show_on_homepage',
                'can_access_analytics', 'can_access_advanced_analytics', 'can_access_ads',
                'priority_score', 'support_level', 'badge_level',
            )
        }),
        ('Controlled Direct Contact', {
            'fields': (
                'allow_phone_display', 'allow_whatsapp_display', 'allow_callback_requests',
            ),
            'description': 'Backend-gated customer contact. Phone/WhatsApp are exposed only when vendor opts in, the subscription plan allows it, and the vendor is approved, verified, and active.'
        }),
        ('Performance Metrics', {
            'fields': ('rating_avg', 'total_sales', 'total_reviews', 'followers_count', 'response_time', 'fulfillment_rate', 'return_rate')
        }),
        ('Delivery Pickup Location', {
            'fields': ('pickup_contact_name', 'pickup_phone', 'pickup_address', 'pickup_latitude', 'pickup_longitude', 'pickup_map_preview'),
            'description': 'Exact vendor pickup pin used for checkout pricing, nearby rider assignment, and rider navigation.'
        }),
        ('Badges', {
            'fields': ('is_top_rated', 'is_best_seller', 'is_trusted')
        }),
        ('Timestamps', {
            'fields': ('is_active', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def logo_preview(self, obj):
        if obj.store_logo:
            return format_html('<img src="{}" width="50" height="50" style="border-radius: 50%;" />', obj.store_logo.url)
        return "No Logo"
    logo_preview.short_description = 'Logo'

    def banner_preview(self, obj):
        if obj.store_banner:
            return format_html('<img src="{}" width="160" height="52" style="border-radius: 12px; object-fit: cover;" />', obj.store_banner.url)
        return "No Banner"
    banner_preview.short_description = 'Banner'

    def profile_completion_display(self, obj):
        if not obj:
            return "0%"
        return f"{obj.profile_completion_percent}%"
    profile_completion_display.short_description = 'Profile completion'

    def marketplace_location(self, obj):
        if getattr(obj, 'address_is_complete', False):
            return format_html('<span style="color:#16a34a;font-weight:700;">{}</span>', obj.location_label or obj.country)
        return format_html('<span style="color:#dc2626;font-weight:700;">Missing address</span>')
    marketplace_location.short_description = 'Location'

    def pickup_ready(self, obj):
        if obj.pickup_location_is_ready:
            return format_html('<span style="color:#16a34a;font-weight:700;">Ready</span>')
        return format_html('<span style="color:#dc2626;font-weight:700;">Missing pin</span>')
    pickup_ready.short_description = 'Pickup'

    def direct_contact_status(self, obj):
        if getattr(obj, 'direct_contact_eligible', False):
            return format_html('<span style="color:#16a34a;font-weight:700;">Eligible</span>')
        return format_html('<span style="color:#dc2626;font-weight:700;">Blocked</span>')
    direct_contact_status.short_description = 'Contact gate'

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

    def approve_vendors(self, request, queryset):
        queryset.update(approval_status='approved', approved_by=request.user, approved_at=timezone.now(), is_active=True)
        self.message_user(request, f'{queryset.count()} vendor profile(s) approved.')
    approve_vendors.short_description = 'Approve selected vendors'

    def reject_vendors(self, request, queryset):
        queryset.update(approval_status='rejected', is_verified=False)
        self.message_user(request, f'{queryset.count()} vendor profile(s) rejected.')
    reject_vendors.short_description = 'Reject selected vendors'

    def suspend_vendors(self, request, queryset):
        queryset.update(approval_status='suspended', is_active=False)
        self.message_user(request, f'{queryset.count()} vendor profile(s) suspended.')
    suspend_vendors.short_description = 'Suspend selected vendors'

    def activate_vendors(self, request, queryset):
        queryset.update(is_active=True)
        self.message_user(request, f'{queryset.count()} vendor profile(s) activated.')
    activate_vendors.short_description = 'Activate selected vendors'

    def mark_manufacturer_verified(self, request, queryset):
        queryset.update(manufacturer_verified=True, is_verified=True)
        self.message_user(request, f'{queryset.count()} vendor profile(s) marked manufacturer verified.')
    mark_manufacturer_verified.short_description = 'Mark selected vendors manufacturer verified'

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


@admin.register(VendorCallbackRequest)
class VendorCallbackRequestAdmin(admin.ModelAdmin):
    list_display = ['id', 'vendor', 'product', 'customer_name', 'customer_phone', 'status', 'urgency', 'assigned_to', 'created_at']
    list_filter = ['status', 'urgency', 'created_at', 'vendor__subscription_tier']
    search_fields = ['vendor__store_name', 'product__name', 'customer_name', 'customer_phone', 'customer_email', 'message']
    readonly_fields = ['created_at', 'updated_at']
    autocomplete_fields = ['vendor', 'product', 'customer_user', 'assigned_to']
    actions = ['assign_to_me', 'mark_contacted', 'mark_resolved', 'mark_closed']

    fieldsets = (
        ('Request', {
            'fields': ('vendor', 'product', 'customer_user', 'customer_name', 'customer_phone', 'customer_email', 'message')
        }),
        ('Support Workflow', {
            'fields': ('status', 'urgency', 'assigned_to', 'contacted_at', 'resolved_at', 'admin_note')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at')
        }),
    )

    def assign_to_me(self, request, queryset):
        queryset.update(assigned_to=request.user, status='assigned')
        self.message_user(request, f'{queryset.count()} callback request(s) assigned to you.')
    assign_to_me.short_description = 'Assign selected callback requests to me'

    def mark_contacted(self, request, queryset):
        queryset.update(status='contacted', contacted_at=timezone.now())
        self.message_user(request, f'{queryset.count()} callback request(s) marked contacted.')
    mark_contacted.short_description = 'Mark selected callback requests contacted'

    def mark_resolved(self, request, queryset):
        queryset.update(status='resolved', resolved_at=timezone.now())
        self.message_user(request, f'{queryset.count()} callback request(s) marked resolved.')
    mark_resolved.short_description = 'Mark selected callback requests resolved'

    def mark_closed(self, request, queryset):
        queryset.update(status='closed')
        self.message_user(request, f'{queryset.count()} callback request(s) closed.')
    mark_closed.short_description = 'Close selected callback requests'


@admin.register(VendorLead)
class VendorLeadAdmin(admin.ModelAdmin):
    list_display = ['id', 'vendor', 'product', 'action_type', 'source', 'country', 'currency', 'customer_name', 'customer_phone', 'created_at']
    list_filter = ['action_type', 'source', 'country', 'currency', 'created_at', 'vendor__subscription_tier']
    search_fields = ['vendor__store_name', 'product__name', 'customer_name', 'customer_phone', 'customer_email', 'page_url', 'product_url', 'guest_session_key']
    readonly_fields = [
        'vendor', 'product', 'customer_user', 'guest_session_key', 'action_type',
        'customer_name', 'customer_phone', 'customer_email', 'source', 'page_url',
        'product_url', 'ip_address', 'country', 'currency', 'user_agent', 'metadata',
        'extra_data', 'created_at', 'updated_at'
    ]
    autocomplete_fields = ['vendor', 'product', 'customer_user']


@admin.register(VendorBankAccount)
class VendorBankAccountAdmin(admin.ModelAdmin):
    list_display = ['vendor', 'bank_name', 'account_name', 'bank_country', 'preferred_currency', 'is_default', 'is_verified']
    list_filter = ['bank_country', 'preferred_currency', 'is_default', 'is_verified']
    search_fields = ['vendor__store_name', 'account_name', 'account_number', 'bank_name']
    actions = ['verify_accounts']

    def verify_accounts(self, request, queryset):
        queryset.update(is_verified=True, verified_by=request.user, verified_at=timezone.now())
        self.message_user(request, f'{queryset.count()} bank account(s) verified.')
    verify_accounts.short_description = 'Verify selected bank accounts'


@admin.register(VendorWallet)
class VendorWalletAdmin(admin.ModelAdmin):
    list_display = ['vendor', 'available_balance', 'pending_balance', 'withdrawable_balance', 'total_earnings', 'total_withdrawn', 'currency']
    search_fields = ['vendor__store_name', 'vendor__user__email']


@admin.register(VendorTransaction)
class VendorTransactionAdmin(admin.ModelAdmin):
    list_display = ['vendor', 'transaction_type', 'amount', 'balance_after', 'reference', 'created_at']
    list_filter = ['transaction_type', 'created_at']
    search_fields = ['vendor__store_name', 'reference', 'description']


@admin.register(VendorWithdrawal)
class VendorWithdrawalAdmin(admin.ModelAdmin):
    list_display = ['vendor', 'amount', 'currency', 'status', 'bank_account', 'requested_at', 'paid_at']
    list_filter = ['status', 'currency', 'requested_at']
    search_fields = ['vendor__store_name', 'vendor__user__email']
    actions = ['approve_withdrawals', 'reject_withdrawals', 'mark_paid']

    def approve_withdrawals(self, request, queryset):
        queryset.update(status='approved', reviewed_by=request.user, reviewed_at=timezone.now())
        self.message_user(request, f'{queryset.count()} withdrawal(s) approved.')
    approve_withdrawals.short_description = 'Approve selected withdrawals'

    def reject_withdrawals(self, request, queryset):
        queryset.update(status='rejected', reviewed_by=request.user, reviewed_at=timezone.now())
        self.message_user(request, f'{queryset.count()} withdrawal(s) rejected.')
    reject_withdrawals.short_description = 'Reject selected withdrawals'

    def mark_paid(self, request, queryset):
        queryset.update(status='paid', reviewed_by=request.user, reviewed_at=timezone.now(), paid_at=timezone.now())
        self.message_user(request, f'{queryset.count()} withdrawal(s) marked paid.')
    mark_paid.short_description = 'Mark selected withdrawals as paid'


@admin.register(VendorRFQ)
class VendorRFQAdmin(admin.ModelAdmin):
    list_display = ['id', 'vendor', 'product', 'quantity', 'status', 'quote_price', 'quote_lead_time_days', 'created_at']
    list_filter = ['status', 'country', 'created_at']
    search_fields = ['vendor__store_name', 'product__name', 'message', 'delivery_location']
