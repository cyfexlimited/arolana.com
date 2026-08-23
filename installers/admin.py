from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html

from core.media_optimization import get_optimized_image_url
from social_publishing.admin_inlines import SocialPublicationInline

from .models import (
    ProviderKYCDocument,
    ProviderProfileChangeRequest,
    ProviderSubscriptionPlan,
    ProviderService,
    ServiceCategory,
    ServiceMarketplaceHomepageSection,
    ServicePortfolio,
    ServiceProjectMedia,
    ServiceProjectModerationLog,
    ServiceProjectProduct,
    ServiceProjectReport,
    ServiceProviderProfile,
    ServiceQuoteRequest,
    ServiceReview,
)
from .project_services import moderate_project
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


class ProviderKYCDocumentInline(
    admin.TabularInline
):
    model = ProviderKYCDocument

    extra = 0

    fields = (
        "document_type",
        "file",
        "note",
        "is_active",
        "created_at",
    )

    readonly_fields = (
        "created_at",
    )

    show_change_link = True

    def get_readonly_fields(
        self,
        request,
        obj=None,
    ):
        return (
            "created_at",
        )


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
        ("Settings & Support", {"fields": ("preferred_language", "notification_preferences", "support_phone", "support_email", "support_whatsapp", "business_hours", "business_hours_data", "availability_note", "bank_details")}),
        ("Sensitive Update Control", {"fields": ("last_sensitive_update_approved_at", "sensitive_update_cooldown_unlocked_until", "sensitive_update_available_at")}),
        ("Performance", {"fields": ("average_rating", "total_reviews", "total_completed_jobs")}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )

    @admin.display(description="Image")
    def profile_preview(self, obj):
        image = getattr(obj, "profile_image", None) or getattr(obj, "business_logo", None)
        if not obj or not image:
            return "No image"
        url = get_optimized_image_url(image, "provider_profile")
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
        (
            "Projects & Proof Network",
            {
                "fields": (
                    "projects_enabled",
                    "projects_eyebrow",
                    "projects_title",
                    "projects_subtitle",
                    "projects_button_text",
                    "projects_limit",
                )
            },
        ),
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
    list_display = (
        "provider",
        "status",
        "sensitive_fields_display",
        "requested_by",
        "reviewed_by",
        "created_at",
    )

    list_filter = (
        "status",
        "created_at",
        "reviewed_at",
    )

    search_fields = (
        "provider__business_name",
        "requested_by__email",
        "admin_note",
    )

    autocomplete_fields = (
        "provider",
        "requested_by",
        "reviewed_by",
    )

    readonly_fields = (
        "provider",
        "requested_by",
        "old_values",
        "proposed_values",
        "sensitive_fields",
        "proposed_file",
        "proposed_file_field",
        "created_at",
        "updated_at",
        "reviewed_at",
    )

    actions = [
        approve_profile_changes,
        reject_profile_changes,
    ]

    fieldsets = (
        (
            "Provider",
            {
                "fields": (
                    "provider",
                    "requested_by",
                    "status",
                ),
            },
        ),
        (
            "Requested Changes",
            {
                "fields": (
                    "sensitive_fields",
                    "old_values",
                    "proposed_values",
                    "proposed_file_field",
                    "proposed_file",
                ),
            },
        ),
        (
            "Review",
            {
                "fields": (
                    "admin_note",
                    "reviewed_by",
                    "reviewed_at",
                ),
            },
        ),
        (
            "Timestamps",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                ),
                "classes": (
                    "collapse",
                ),
            },
        ),
    )

    @admin.display(
        description="Fields"
    )
    def sensitive_fields_display(
        self,
        obj,
    ):
        return ", ".join(
            obj.sensitive_fields
            or []
        )


@admin.register(ProviderKYCDocument)
class ProviderKYCDocumentAdmin(admin.ModelAdmin):
    list_display = ("provider", "document_type", "is_active", "created_at")
    list_filter = ("document_type", "is_active", "created_at")
    search_fields = ("provider__business_name", "note")
    autocomplete_fields = ("provider",)


@admin.register(ProviderSubscriptionPlan)
class ProviderSubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = (
        "name", "official_tier_key", "price_monthly", "price_yearly",
        "is_deprecated", "display_order", "is_default", "is_active",
    )
    list_filter = ("official_tier_key", "is_deprecated", "is_default", "is_active")
    search_fields = ("name", "description")

    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ServicePortfolio)
class ServicePortfolioAdmin(admin.ModelAdmin):
    list_display = (
        "portfolio_preview", "title", "provider", "service_category", "location",
        "approval_status", "media_count", "has_video", "views_count",
        "quote_requests_count", "is_verified_project", "is_featured", "created_at",
    )
    list_filter = (
        "approval_status", "project_type", "service_category", "country", "state", "city",
        "is_verified_project", "is_featured", "is_active", "completed_at", "created_at",
    )
    search_fields = ("title", "short_summary", "provider__business_name", "location_display", "city", "state")
    autocomplete_fields = ("provider", "created_by", "service_category")
    readonly_fields = (
        "slug", "views_count", "video_views_count", "product_click_count",
        "provider_click_count", "quote_requests_count", "shares_count", "saves_count",
        "published_at", "created_at", "updated_at",
    )
    actions = ("approve_projects", "request_project_changes", "reject_projects", "feature_projects", "verify_projects")
    inlines = ()
    fieldsets = (
        ("Basic Information", {"fields": ("provider", "created_by", "title", "slug", "short_summary", "description", "project_type", "service_category")}),
        ("Location & Completion", {"fields": ("country", "state", "city", "location_display", "completed_at", "project_duration_text")}),
        ("Project Story", {"fields": ("challenge", "solution", "implementation_process", "project_result", "customer_outcome", "technologies_used", "services_performed")}),
        ("Customer & Value Privacy", {"fields": ("customer_type", "customer_name_display", "customer_name_private", "customer_consent_to_publish", "project_value_min", "project_value_max", "project_value_currency", "show_project_value")}),
        ("Primary Media", {"fields": ("image", "video_source", "video_url", "local_video", "video_thumbnail", "video_duration")}),
        ("Moderation", {"fields": ("approval_status", "moderation_notes", "is_verified_project", "is_featured", "is_active", "published_at")}),
        ("Analytics", {"fields": ("views_count", "video_views_count", "product_click_count", "provider_click_count", "quote_requests_count", "shares_count", "saves_count")}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )

    @admin.display(description="Image")
    def portfolio_preview(self, obj):
        if not obj.image:
            return "No image"
        return format_html('<img src="{}" style="width:80px;height:54px;object-fit:cover;border-radius:10px">', get_optimized_image_url(obj.image, "category_card"))

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if obj.approval_status == ServicePortfolio.STATUS_APPROVED:
            from social_publishing.moderation import approve_project_media_package

            approve_project_media_package(obj, request.user)

    @admin.display(description="Location")
    def location(self, obj):
        return obj.location_display

    @admin.display(description="Media")
    def media_count(self, obj):
        return obj.media_items.count()

    @admin.display(boolean=True, description="Video")
    def has_video(self, obj):
        return obj.has_video

    @admin.action(description="Approve selected projects")
    def approve_projects(self, request, queryset):
        for project in queryset:
            moderate_project(project, ServicePortfolio.STATUS_APPROVED, request.user)

    @admin.action(description="Request changes for selected projects")
    def request_project_changes(self, request, queryset):
        for project in queryset:
            moderate_project(project, ServicePortfolio.STATUS_REQUIRES_CHANGES, request.user, project.moderation_notes)

    @admin.action(description="Reject selected projects")
    def reject_projects(self, request, queryset):
        for project in queryset:
            moderate_project(project, ServicePortfolio.STATUS_REJECTED, request.user, project.moderation_notes)

    @admin.action(description="Feature selected projects")
    def feature_projects(self, request, queryset):
        queryset.update(is_featured=True)

    @admin.action(description="Mark selected as verified projects")
    def verify_projects(self, request, queryset):
        queryset.update(is_verified_project=True)


def _service_project_media_preview(obj):
    if not obj or not obj.pk:
        return "Save the media item to preview it."
    image = obj.image or obj.thumbnail
    if image:
        url = get_optimized_image_url(image, "project_thumb")
        if url:
            return format_html(
                '<img src="{}" alt="" style="width:150px;height:96px;'
                'object-fit:cover;border-radius:12px;background:#eef4fb">',
                url,
            )
    if obj.media_type == ServiceProjectMedia.TYPE_VIDEO:
        if obj.video_embed_url:
            return format_html(
                '<a href="{}" target="_blank" rel="noopener">Preview external video</a>',
                obj.external_video_url,
            )
        if obj.playable_video:
            return format_html(
                '<video src="{}" controls preload="metadata" '
                'style="width:220px;max-height:130px;border-radius:12px"></video>',
                obj.playable_video.url,
            )
        return format_html(
            '<strong style="color:#075cb7">Video {}</strong>',
            obj.get_processing_status_display().lower(),
        )
    if obj.media_type == ServiceProjectMedia.TYPE_DOCUMENT and obj.document:
        return format_html(
            '<a href="{}" target="_blank" rel="noopener">Open supporting document</a>',
            obj.document.url,
        )
    return "No preview available"


class ServiceProjectMediaInline(admin.StackedInline):
    model = ServiceProjectMedia
    extra = 0
    fields = (
        "media_preview",
        "media_type",
        "stage",
        "image",
        "video",
        "processed_video",
        "external_video_url",
        "document",
        "thumbnail",
        "caption",
        "alt_text",
        "display_order",
        "is_featured",
        "is_cover",
        "approval_status",
        "moderation_note",
        "processing_status",
        "processing_error",
    )
    readonly_fields = (
        "media_preview",
        "processing_error",
    )
    show_change_link = True

    @admin.display(description="Preview")
    def media_preview(self, obj):
        return _service_project_media_preview(obj)


class ServiceProjectProductInline(admin.TabularInline):
    model = ServiceProjectProduct
    extra = 0
    autocomplete_fields = ("product",)


class ServiceProjectModerationLogInline(admin.TabularInline):
    model = ServiceProjectModerationLog
    extra = 0
    readonly_fields = ("actor", "old_status", "new_status", "notes", "created_at")
    can_delete = False


ServicePortfolioAdmin.inlines = (
    ServiceProjectMediaInline,
    ServiceProjectProductInline,
    ServiceProjectModerationLogInline,
)


@admin.register(ServiceProjectMedia)
class ServiceProjectMediaAdmin(admin.ModelAdmin):
    inlines = (SocialPublicationInline,)
    list_display = (
        "media_preview",
        "project",
        "provider_name",
        "media_type",
        "stage",
        "approval_status",
        "processing_status",
        "is_cover",
        "is_featured",
        "display_order",
        "created_at",
    )
    list_filter = (
        "media_type",
        "stage",
        "approval_status",
        "processing_status",
        "is_cover",
        "is_featured",
        "created_at",
    )
    search_fields = ("project__title", "project__provider__business_name", "caption", "alt_text")
    autocomplete_fields = ("project",)
    readonly_fields = (
        "media_preview",
        "file_size",
        "mime_type",
        "original_filename",
        "processing_error",
        "created_at",
        "updated_at",
    )
    actions = (
        "approve_media",
        "request_media_changes",
        "reject_media",
        "mark_featured",
    )
    fieldsets = (
        ("Project & Classification", {"fields": ("project", "media_type", "stage")}),
        ("Preview", {"fields": ("media_preview",)}),
        ("Media Sources", {"fields": ("image", "video", "processed_video", "external_video_url", "document", "thumbnail")}),
        ("Presentation", {"fields": ("caption", "alt_text", "display_order", "is_cover", "is_featured")}),
        ("Moderation", {"fields": ("approval_status", "moderation_note", "approved_by", "approved_at", "is_active")}),
        ("Processing", {"fields": ("processing_status", "processing_error", "file_size", "mime_type", "original_filename")}),
        ("Audit", {"fields": ("uploaded_by", "created_at", "updated_at")}),
    )

    @admin.display(description="Preview")
    def media_preview(self, obj):
        return _service_project_media_preview(obj)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if obj.approval_status == ServiceProjectMedia.STATUS_APPROVED:
            from social_publishing.moderation import approve_project_media

            approve_project_media(obj, request.user)

    @admin.display(description="Provider", ordering="project__provider__business_name")
    def provider_name(self, obj):
        return obj.project.provider.business_name

    @admin.action(description="Approve selected project media")
    def approve_media(self, request, queryset):
        from social_publishing.moderation import approve_project_media
        for media in queryset:
            approve_project_media(media, request.user)

    @admin.action(description="Request changes for selected project media")
    def request_media_changes(self, request, queryset):
        queryset.update(
            approval_status=ServiceProjectMedia.STATUS_REQUIRES_CHANGES,
            approved_by=None,
            approved_at=None,
            is_active=True,
        )

    @admin.action(description="Reject selected project media")
    def reject_media(self, request, queryset):
        queryset.update(
            approval_status=ServiceProjectMedia.STATUS_REJECTED,
            approved_by=None,
            approved_at=None,
            is_active=False,
        )

    @admin.action(description="Mark selected project media as featured")
    def mark_featured(self, request, queryset):
        queryset.update(is_featured=True)


@admin.register(ServiceProjectReport)
class ServiceProjectReportAdmin(admin.ModelAdmin):
    list_display = ("project", "reason", "reporter", "status", "created_at")
    list_filter = ("status", "reason", "created_at")
    search_fields = ("project__title", "details", "reporter__email")
    autocomplete_fields = ("project", "reporter")


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
