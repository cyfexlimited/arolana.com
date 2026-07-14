from django import forms
from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html

from vendors.models import VendorProfile

from .models import (
    SubscriptionHistory,
    SubscriptionPayment,
    SubscriptionPlan,
    SubscriptionReminderLog,
    VendorSubscription,
    apply_vendor_subscription_benefits,
)
from .lifecycle import sync_account_role_subscription
from .services import sync_vendor_subscription_profile


class VendorSubscriptionAdminForm(forms.ModelForm):
    override_reason = forms.CharField(
        required=False,
        label="Administrative override reason",
        help_text="Required for every manual subscription change. This is stored in the immutable audit history.",
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    class Meta:
        model = VendorSubscription
        fields = "__all__"

    def clean(self):
        cleaned_data = super().clean()
        changed_model_fields = [name for name in self.changed_data if name != "override_reason"]
        if changed_model_fields and not (cleaned_data.get("override_reason") or "").strip():
            self.add_error("override_reason", "Explain why this subscription is being changed manually.")
        return cleaned_data

@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = [
        'display_name', 'tier_key', 'price_monthly', 'max_products',
        'max_images_per_product', 'max_variants_per_product', 'priority_score',
        'commission_rate', 'chat_enabled', 'can_access_rfq', 'can_show_phone',
        'can_show_whatsapp', 'can_receive_callback_requests', 'can_show_on_homepage',
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
                'commission_rate', 'feature_bullets', 'role_entitlements'
            )
        }),
        ('Benefits', {
            'fields': (
                'can_upload_video', 'can_upload_pdf', 'can_upload_certificates',
                'can_access_rfq', 'can_receive_direct_enquiries',
                'can_show_phone', 'can_show_whatsapp', 'can_receive_callback_requests',
                'can_show_direct_contact_badge', 'lead_tracking_enabled', 'hide_phone_until_click',
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
                f"Updated subscription benefits for {synced} active vendor(s) on this plan.",
            )

@admin.register(VendorSubscription)
class VendorSubscriptionAdmin(admin.ModelAdmin):
    form = VendorSubscriptionAdminForm
    list_display = [
        'vendor', 'plan', 'status', 'billing_cycle', 'payment_state',
        'start_date', 'end_date', 'is_active', 'auto_renew',
        'cancel_at_period_end', 'days_remaining',
    ]
    list_filter = [
        'plan', 'status', 'billing_cycle', 'payment_state', 'is_active',
        'auto_renew', 'cancel_at_period_end',
    ]
    search_fields = ['vendor__username', 'vendor__email']
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        ('Subscription Info', {
            'fields': (
                'vendor', 'plan', 'status', 'billing_cycle', 'currency',
                'start_date', 'end_date', 'is_active', 'auto_renew',
                'trial_ends_at', 'grace_period_ends_at',
            )
        }),
        ('Payment Info', {
            'fields': ('payment_state', 'payment_method', 'transaction_id', 'source_platform')
        }),
        ('Cancellation & Scheduled Changes', {
            'fields': (
                'cancel_at_period_end', 'cancellation_requested_at', 'cancelled_at',
                'cancellation_reason', 'pending_plan', 'pending_change_type',
                'pending_change_effective_at',
            )
        }),
        ('Administrative Override Audit', {
            'fields': ('override_reason',),
            'description': 'All manual changes are recorded with the signed-in staff member and this reason.',
        }),
    )
    
    def days_remaining(self, obj):
        if obj.end_date:
            delta = obj.end_date - timezone.now()
            return f"{delta.days} days"
        return "-"
    days_remaining.short_description = 'Days Left'

    def save_model(self, request, obj, form, change):
        previous = VendorSubscription.objects.filter(pk=obj.pk).select_related('plan').first() if change else None
        super().save_model(request, obj, form, change)
        changed_fields = [name for name in form.changed_data if name != 'override_reason']
        if changed_fields:
            SubscriptionHistory.objects.create(
                user=obj.vendor,
                subscription=obj,
                event_type='staff_override',
                previous_plan=previous.plan if previous else None,
                new_plan=obj.plan,
                previous_status=previous.status if previous else '',
                new_status=obj.status,
                actor=request.user,
                source_platform='django_admin',
                metadata={
                    'reason': (form.cleaned_data.get('override_reason') or '').strip(),
                    'changed_fields': changed_fields,
                },
            )
        sync_account_role_subscription(obj.vendor, obj if obj.is_current else None)

    def delete_model(self, request, obj):
        vendor = obj.vendor
        super().delete_model(request, obj)
        sync_account_role_subscription(vendor)

    def delete_queryset(self, request, queryset):
        vendors = list(queryset.values_list('vendor_id', flat=True).distinct())
        super().delete_queryset(request, queryset)
        for profile in VendorProfile.objects.filter(
            user_id__in=vendors
        ).select_related('user'):
            sync_account_role_subscription(profile.user)


class ImmutableSubscriptionRecordAdmin(admin.ModelAdmin):
    actions = None

    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SubscriptionPayment)
class SubscriptionPaymentAdmin(ImmutableSubscriptionRecordAdmin):
    list_display = (
        'reference', 'user', 'plan', 'billing_cycle', 'amount', 'currency',
        'gateway', 'status', 'verified_at', 'activated_at', 'created_at',
    )
    list_filter = ('status', 'plan', 'billing_cycle', 'currency', 'gateway', 'created_at')
    search_fields = ('reference', 'user__email', 'user__username')
    date_hierarchy = 'created_at'


@admin.register(SubscriptionHistory)
class SubscriptionHistoryAdmin(ImmutableSubscriptionRecordAdmin):
    list_display = (
        'created_at', 'user', 'event_type', 'previous_plan', 'new_plan',
        'previous_status', 'new_status', 'source_platform',
    )
    list_filter = ('event_type', 'previous_status', 'new_status', 'source_platform', 'created_at')
    search_fields = ('user__email', 'user__username', 'payment_reference')
    date_hierarchy = 'created_at'


@admin.register(SubscriptionReminderLog)
class SubscriptionReminderLogAdmin(ImmutableSubscriptionRecordAdmin):
    list_display = ('subscription', 'event_key', 'channel', 'sent_at')
    list_filter = ('channel', 'event_key', 'sent_at')
    search_fields = ('subscription__vendor__email', 'subscription__vendor__username', 'event_key')
    date_hierarchy = 'sent_at'
