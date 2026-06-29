from django.contrib import admin
from django.utils.html import format_html

from core.media_optimization import get_optimized_image_url

from .models import (
    ProviderKYCDocument,
    ProviderProfileChangeRequest,
    ProviderSubscriptionPlan,
    ProviderService,
    ServiceCategory,
    ServiceMarketplaceHomepageSection,
    ServicePortfolio,
    ServiceProviderProfile,
    ServiceQuoteRequest,
    ServiceReview,
)
from .services import (
    approve_profile_change_request,
    approve_provider,
    approve_provider_kyc,
    reject_profile_change_request,
    reject_provider,
    reject_provider_kyc,
    request_provider_changes,
    suspend_provider,
)


class ProviderServiceInline(admin.TabularInline):
    model = ProviderService
    extra = 0


class ServicePortfolioInline(admin.StackedInline):
    model = ServicePortfolio
    extra = 0


class ProviderKYCDocumentInline(admin.TabularInline):
    model = ProviderKYCDocument
    extra = 0


@admin.action(description="Approve selected providers")
def approve_provider_applications(modeladmin, request, queryset):
    for provider in queryset:
        approve_provider(provider, request.user, verify=False)


@admin.action(description="Approve and verify selected providers")
def approve_and_verify_providers(modeladmin, request, queryset):
    for provider in queryset:
        approve_provider(provider, request.user, verify=True)


@admin.action(description="Reject selected providers")
def reject_providers(modeladmin, request, queryset):
    for provider in queryset:
        reject_provider(provider, request.user, provider.rejection_reason or "Rejected by Arolana admin.")


@admin.action(description="Request changes from selected providers")
def request_changes_from_providers(modeladmin, request, queryset):
    for provider in queryset:
        request_provider_changes(
            provider,
            request.user,
            provider.changes_requested_note or "Please update the highlighted provider profile details.",
        )


@admin.action(description="Suspend selected providers")
def suspend_providers(modeladmin, request, queryset):
    for provider in queryset:
        suspend_provider(provider, request.user, provider.admin_note or "Provider account suspended by Arolana admin.")


@admin.action(description="Approve provider KYC")
def approve_kyc(modeladmin, request, queryset):
    for provider in queryset:
        approve_provider_kyc(provider, request.user)


@admin.action(description="Reject provider KYC")
def reject_kyc(modeladmin, request, queryset):
    for provider in queryset:
        reject_provider_kyc(provider, request.user, provider.kyc_note or "KYC rejected by Arolana admin.")


@admin.action(description="Unlock 14-day sensitive update cooldown")
def unlock_sensitive_update_cooldown(modeladmin, request, queryset):
    queryset.update(last_sensitive_update_approved_at=None, sensitive_update_cooldown_unlocked_until=None)


@admin.action(description="Activate selected records")
def activate_records(modeladmin, request, queryset):
    queryset.update(is_active=True)


@admin.action(description="Deactivate selected records")
def deactivate_records(modeladmin, request, queryset):
    queryset.update(is_active=False)


@admin.register(ServiceProviderProfile)
class ServiceProviderProfileAdmin(admin.ModelAdmin):
    list_display = (
        "profile_preview",
        "business_name",
        "provider_type",
        "location",
        "verification_status",
        "kyc_status",
        "subscription_status",
        "is_verified",
        "review_due_at",
        "average_rating",
        "total_reviews",
        "is_active",
    )
    list_filter = (
        "verification_status",
        "kyc_status",
        "subscription_status",
        "is_verified",
        "provider_type",
        "country",
        "state",
        "city",
        "services__category",
        "is_active",
        "created_at",
    )
    search_fields = ("business_name", "contact_person", "phone_number", "email", "city", "state")
    prepopulated_fields = {"slug": ("business_name",)}
    readonly_fields = (
        "profile_preview",
        "average_rating",
        "total_reviews",
        "profile_completion_percent",
        "sensitive_update_available_at",
        "created_at",
        "updated_at",
    )
    inlines = [ProviderServiceInline, ServicePortfolioInline, ProviderKYCDocumentInline]
    actions = [
        approve_provider_applications,
        approve_and_verify_providers,
        reject_providers,
        request_changes_from_providers,
        suspend_providers,
        approve_kyc,
        reject_kyc,
        unlock_sensitive_update_cooldown,
        activate_records,
        deactivate_records,
    ]
    fieldsets = (
        ("Business Identity", {"fields": ("user", "business_name", "slug", "contact_person", "provider_type")}),
        ("Contact & Coverage", {"fields": ("phone_number", "whatsapp_number", "email", "website", "country", "state", "city", "address", "service_coverage")}),
        ("Profile & Media", {"fields": ("description", "years_of_experience", "profile_image", "business_logo", "business_banner", "profile_preview", "profile_completion_percent")}),
        ("Approval Timeline", {"fields": ("verification_status", "verification_note", "admin_note", "rejection_reason", "changes_requested_note", "submitted_at", "review_started_at", "approved_at", "rejected_at", "changes_requested_at", "review_due_at", "reviewed_by", "is_verified", "is_active")}),
        ("KYC", {"fields": ("kyc_status", "kyc_note", "kyc_reviewed_at", "kyc_expires_at", "cac_number", "government_id_upload", "cac_certificate_upload", "allow_limited_jobs_without_kyc")}),
        ("Subscription & Access", {"fields": ("subscription_plan", "subscription_status", "subscription_expires_at", "availability_status")}),
        ("Settings & Support", {"fields": ("preferred_language", "notification_preferences", "support_phone", "support_email", "support_whatsapp", "business_hours", "availability_note", "bank_details")}),
        ("Sensitive Update Control", {"fields": ("last_sensitive_update_approved_at", "sensitive_update_cooldown_unlocked_until", "sensitive_update_available_at")}),
        ("Performance", {"fields": ("average_rating", "total_reviews", "total_completed_jobs")}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )

    @admin.display(description="Image")
    def profile_preview(self, obj):
        image = getattr(obj, "profile_image", None) or getattr(obj, "business_logo", None)
        if not obj or not image:
            return "No image"
        url = get_optimized_image_url(image, "avatar")
        return format_html('<img src="{}" style="width:56px;height:56px;object-fit:cover;border-radius:14px">', url)

    @admin.display(description="Location")
    def location(self, obj):
        return obj.location_label


@admin.register(ServiceCategory)
class ServiceCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "image_preview", "provider_count", "is_active", "created_at")
    list_filter = ("is_active", "created_at")
    search_fields = ("name", "description", "matching_keywords")
    prepopulated_fields = {"slug": ("name",)}
    filter_horizontal = ("product_categories",)
    actions = [activate_records, deactivate_records]

    @admin.display(description="Image")
    def image_preview(self, obj):
        if not obj.image:
            return "No image"
        return format_html('<img src="{}" style="width:72px;height:48px;object-fit:cover;border-radius:10px">', get_optimized_image_url(obj.image, "category_card"))

    @admin.display(description="Providers")
    def provider_count(self, obj):
        return obj.provider_services.filter(provider__is_active=True).values("provider_id").distinct().count()


@admin.register(ServiceMarketplaceHomepageSection)
class ServiceMarketplaceHomepageSectionAdmin(admin.ModelAdmin):
    list_display = ("title", "display_order", "is_active", "updated_at")
    list_editable = ("display_order", "is_active")
    fieldsets = (
        ("Content", {"fields": ("eyebrow", "title", "subtitle", "customer_button_text", "provider_button_text")}),
        ("Design", {"fields": ("background_image", "background_color", "accent_color")}),
        ("Visibility", {"fields": ("display_order", "is_active")}),
    )


@admin.register(ProviderService)
class ProviderServiceAdmin(admin.ModelAdmin):
    list_display = ("service_name", "provider", "category", "starting_price", "is_active")
    list_filter = ("category", "is_active", "created_at")
    search_fields = ("service_name", "provider__business_name", "description")
    autocomplete_fields = ("provider", "category")
    actions = [activate_records, deactivate_records]


@admin.action(description="Approve selected profile changes")
def approve_profile_changes(modeladmin, request, queryset):
    for change in queryset:
        approve_profile_change_request(change, request.user, change.admin_note)


@admin.action(description="Reject selected profile changes")
def reject_profile_changes(modeladmin, request, queryset):
    for change in queryset:
        reject_profile_change_request(change, request.user, change.admin_note or "Rejected by Arolana admin.")


@admin.register(ProviderProfileChangeRequest)
class ProviderProfileChangeRequestAdmin(admin.ModelAdmin):
    list_display = ("provider", "status", "sensitive_fields_display", "requested_by", "reviewed_by", "created_at")
    list_filter = ("status", "created_at", "reviewed_at")
    search_fields = ("provider__business_name", "requested_by__email", "admin_note")
    autocomplete_fields = ("provider", "requested_by", "reviewed_by")
    readonly_fields = ("old_values", "proposed_values", "sensitive_fields", "created_at", "updated_at", "reviewed_at")
    actions = [approve_profile_changes, reject_profile_changes]

    @admin.display(description="Fields")
    def sensitive_fields_display(self, obj):
        return ", ".join(obj.sensitive_fields or [])


@admin.register(ProviderKYCDocument)
class ProviderKYCDocumentAdmin(admin.ModelAdmin):
    list_display = ("provider", "document_type", "is_active", "created_at")
    list_filter = ("document_type", "is_active", "created_at")
    search_fields = ("provider__business_name", "note")
    autocomplete_fields = ("provider",)


@admin.register(ProviderSubscriptionPlan)
class ProviderSubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = ("name", "price_monthly", "price_yearly", "display_order", "is_default", "is_active")
    list_editable = ("display_order", "is_active")
    list_filter = ("is_default", "is_active")
    search_fields = ("name", "description")


@admin.register(ServicePortfolio)
class ServicePortfolioAdmin(admin.ModelAdmin):
    list_display = ("portfolio_preview", "title", "provider", "project_location", "completed_at", "created_at")
    list_filter = ("completed_at", "created_at")
    search_fields = ("title", "provider__business_name", "project_location")
    autocomplete_fields = ("provider",)

    @admin.display(description="Image")
    def portfolio_preview(self, obj):
        if not obj.image:
            return "No image"
        return format_html('<img src="{}" style="width:80px;height:54px;object-fit:cover;border-radius:10px">', get_optimized_image_url(obj.image, "category_card"))


@admin.register(ServiceQuoteRequest)
class ServiceQuoteRequestAdmin(admin.ModelAdmin):
    list_display = ("name", "service_needed", "provider", "location", "urgency", "status", "assigned_at", "created_at")
    list_filter = ("status", "urgency", "state", "city", "category", "created_at")
    search_fields = ("name", "phone", "email", "service_needed", "provider__business_name", "product__name")
    autocomplete_fields = ("customer", "provider", "category", "product", "assigned_by")
    readonly_fields = ("created_at", "updated_at", "assigned_at", "accepted_at", "completed_at")

    @admin.display(description="Location")
    def location(self, obj):
        return ", ".join(value for value in [obj.city, obj.state] if value)


@admin.register(ServiceReview)
class ServiceReviewAdmin(admin.ModelAdmin):
    list_display = ("provider", "rating", "customer", "is_approved", "created_at")
    list_filter = ("is_approved", "rating", "created_at")
    search_fields = ("provider__business_name", "customer__email", "comment")
    autocomplete_fields = ("provider", "customer")
