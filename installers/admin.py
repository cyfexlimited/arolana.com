from django.contrib import admin
from django.utils.html import format_html

from core.media_optimization import get_optimized_image_url

from .models import (
    ProviderService,
    ServiceCategory,
    ServiceMarketplaceHomepageSection,
    ServicePortfolio,
    ServiceProviderProfile,
    ServiceQuoteRequest,
    ServiceReview,
)


class ProviderServiceInline(admin.TabularInline):
    model = ProviderService
    extra = 0


class ServicePortfolioInline(admin.StackedInline):
    model = ServicePortfolio
    extra = 0


@admin.action(description="Approve and verify selected providers")
def approve_providers(modeladmin, request, queryset):
    queryset.update(
        verification_status=ServiceProviderProfile.STATUS_APPROVED,
        is_verified=True,
        is_active=True,
    )


@admin.action(description="Reject selected providers")
def reject_providers(modeladmin, request, queryset):
    queryset.update(
        verification_status=ServiceProviderProfile.STATUS_REJECTED,
        is_verified=False,
    )


@admin.action(description="Activate selected records")
def activate_records(modeladmin, request, queryset):
    queryset.update(is_active=True)


@admin.action(description="Deactivate selected records")
def deactivate_records(modeladmin, request, queryset):
    queryset.update(is_active=False)


@admin.register(ServiceProviderProfile)
class ServiceProviderProfileAdmin(admin.ModelAdmin):
    list_display = (
        "profile_preview", "business_name", "provider_type", "location",
        "verification_status", "is_verified", "average_rating", "total_reviews", "is_active",
    )
    list_filter = (
        "verification_status", "is_verified", "provider_type", "country",
        "state", "city", "services__category", "is_active", "created_at",
    )
    search_fields = (
        "business_name", "contact_person", "phone_number", "email", "city", "state",
    )
    prepopulated_fields = {"slug": ("business_name",)}
    readonly_fields = ("profile_preview", "average_rating", "total_reviews", "created_at", "updated_at")
    inlines = [ProviderServiceInline, ServicePortfolioInline]
    actions = [approve_providers, reject_providers, activate_records, deactivate_records]
    fieldsets = (
        ("Account", {"fields": ("user", "business_name", "slug", "contact_person", "provider_type")}),
        ("Contact & Coverage", {"fields": ("phone_number", "whatsapp_number", "email", "website", "country", "state", "city", "address", "service_coverage")}),
        ("Profile", {"fields": ("description", "years_of_experience", "profile_image", "profile_preview")}),
        ("Verification", {"fields": ("cac_number", "government_id_upload", "verification_status", "verification_note", "is_verified", "is_active")}),
        ("Performance", {"fields": ("average_rating", "total_reviews", "total_completed_jobs")}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )

    @admin.display(description="Image")
    def profile_preview(self, obj):
        if not obj or not obj.profile_image:
            return "No image"
        url = get_optimized_image_url(obj.profile_image, "avatar")
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
    list_display = ("name", "service_needed", "provider", "location", "status", "created_at")
    list_filter = ("status", "state", "city", "category", "created_at")
    search_fields = ("name", "phone", "email", "service_needed", "provider__business_name", "product__name")
    autocomplete_fields = ("customer", "provider", "category", "product")
    readonly_fields = ("created_at", "updated_at")

    @admin.display(description="Location")
    def location(self, obj):
        return ", ".join(value for value in [obj.city, obj.state] if value)


@admin.register(ServiceReview)
class ServiceReviewAdmin(admin.ModelAdmin):
    list_display = ("provider", "rating", "customer", "is_approved", "created_at")
    list_filter = ("is_approved", "rating", "created_at")
    search_fields = ("provider__business_name", "customer__email", "comment")
    autocomplete_fields = ("provider", "customer")
