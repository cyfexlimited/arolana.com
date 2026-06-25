from django.contrib import admin
from django.utils.html import format_html

from .models import (
    CareerCategory,
    ContactPageSettings,
    ContactQuickAction,
    FAQ,
    HelpCenterHero,
    JobApplication,
    JobPosition,
    Page,
    SupportArticle,
    SupportTopic,
)


def safe_image_preview(image_field, width=80, height=50, radius=8):
    """
    Safely render image previews in Django admin.
    Prevents admin crash if storage/CDN URL is temporarily unavailable.
    """
    if not image_field:
        return "-"

    try:
        image_url = image_field.url
    except Exception:
        return "Image uploaded, preview unavailable"

    return format_html(
        '<img src="{}" width="{}" height="{}" style="border-radius:{}px;object-fit:cover;border:1px solid #e5e7eb;background:#f8fafc;" />',
        image_url,
        width,
        height,
        radius,
    )


@admin.register(Page)
class PageAdmin(admin.ModelAdmin):
    list_display = [
        "title",
        "slug",
        "is_active",
        "show_in_footer",
        "show_in_header",
        "footer_order",
        "updated_at",
    ]
    list_filter = ["is_active", "show_in_footer", "show_in_header"]
    search_fields = ["title", "slug", "content", "meta_description", "meta_keywords"]
    prepopulated_fields = {"slug": ["title"]}
    list_editable = ["is_active", "show_in_footer", "show_in_header", "footer_order"]

    fieldsets = (
        ("Basic Information", {
            "fields": ("title", "slug", "content", "is_active"),
        }),
        ("SEO", {
            "fields": ("meta_description", "meta_keywords"),
            "classes": ("collapse",),
        }),
        ("Display Options", {
            "fields": ("show_in_footer", "show_in_header", "footer_order"),
            "classes": ("collapse",),
        }),
        ("Sidebar", {
            "fields": ("sidebar_content",),
            "classes": ("collapse",),
        }),
    )


@admin.register(ContactPageSettings)
class ContactPageSettingsAdmin(admin.ModelAdmin):
    list_display = ["title", "support_email", "support_phone", "is_active", "updated_at"]
    list_filter = ["is_active"]
    search_fields = ["title", "support_email", "support_phone", "coverage_text", "protection_text"]
    list_editable = ["is_active"]

    fieldsets = (
        ("Support Channels", {
            "fields": ("title", "support_email", "support_phone", "coverage_text", "is_active"),
        }),
        ("Protection Message", {
            "fields": ("protection_title", "protection_text"),
        }),
    )


@admin.register(ContactQuickAction)
class ContactQuickActionAdmin(admin.ModelAdmin):
    list_display = ["label", "url", "order", "is_active", "updated_at"]
    list_filter = ["is_active"]
    list_editable = ["order", "is_active"]
    search_fields = ["label", "url"]


@admin.register(SupportTopic)
class SupportTopicAdmin(admin.ModelAdmin):
    list_display = ["title", "slug", "order", "icon_preview", "image_preview", "is_active"]
    list_filter = ["is_active"]
    list_editable = ["order", "is_active"]
    search_fields = ["title", "slug", "description"]
    prepopulated_fields = {"slug": ["title"]}

    fieldsets = (
        ("Basic Information", {
            "fields": ("title", "slug", "description", "is_active"),
        }),
        ("Display", {
            "fields": ("icon", "image", "button_text", "button_url", "order"),
        }),
    )

    def icon_preview(self, obj):
        if obj.icon:
            return format_html('<i class="{} fa-2x"></i>', obj.icon)
        return "-"

    icon_preview.short_description = "Icon"

    def image_preview(self, obj):
        return safe_image_preview(obj.image, width=50, height=50, radius=8)

    image_preview.short_description = "Image"


@admin.register(SupportArticle)
class SupportArticleAdmin(admin.ModelAdmin):
    list_display = [
        "title",
        "category",
        "views",
        "helpful_count",
        "not_helpful_count",
        "is_active",
        "updated_at",
    ]
    list_filter = ["category", "is_active"]
    search_fields = ["title", "slug", "content"]
    prepopulated_fields = {"slug": ["title"]}
    readonly_fields = ["views", "helpful_count", "not_helpful_count"]
    list_editable = ["is_active"]

    fieldsets = (
        ("Basic Information", {
            "fields": ("title", "slug", "category", "image", "is_active"),
        }),
        ("Article Content", {
            "fields": ("content",),
        }),
        ("Statistics", {
            "fields": ("views", "helpful_count", "not_helpful_count"),
            "classes": ("collapse",),
        }),
    )


@admin.register(FAQ)
class FAQAdmin(admin.ModelAdmin):
    list_display = [
        "question",
        "category",
        "order",
        "is_featured",
        "is_active",
        "image_preview",
    ]
    list_filter = ["category", "is_featured", "is_active"]
    search_fields = ["question", "answer"]
    list_editable = ["order", "is_featured", "is_active"]

    fieldsets = (
        ("FAQ Content", {
            "fields": ("question", "answer", "category"),
        }),
        ("Display Settings", {
            "fields": ("image", "order", "is_featured", "is_active"),
        }),
    )

    def image_preview(self, obj):
        return safe_image_preview(obj.image, width=40, height=40, radius=6)

    image_preview.short_description = "Image"


@admin.register(HelpCenterHero)
class HelpCenterHeroAdmin(admin.ModelAdmin):
    list_display = [
        "title",
        "is_active",
        "image_preview",
        "updated_at",
    ]
    list_filter = ["is_active"]
    list_editable = ["is_active"]
    search_fields = ["title", "subtitle"]
    readonly_fields = ["large_image_preview"]

    fieldsets = (
        ("Hero Content", {
            "fields": (
                "title",
                "subtitle",
                "background_image",
                "large_image_preview",
                "is_active",
            ),
        }),
    )

    def image_preview(self, obj):
        return safe_image_preview(obj.background_image, width=120, height=60, radius=8)

    image_preview.short_description = "Background"

    def large_image_preview(self, obj):
        if not obj or not obj.background_image:
            return "No background image uploaded yet."

        try:
            image_url = obj.background_image.url
        except Exception:
            return "Image uploaded, preview unavailable."

        return format_html(
            """
            <div style="max-width:720px;">
                <img src="{}" style="width:100%;max-height:260px;object-fit:cover;border-radius:16px;border:1px solid #e5e7eb;background:#f8fafc;" />
                <p style="margin-top:8px;color:#64748b;font-size:12px;">
                    This is the image that will appear on the Help Center hero when this record is active.
                </p>
            </div>
            """,
            image_url,
        )

    large_image_preview.short_description = "Current Background Preview"

    def save_model(self, request, obj, form, change):
        """
        Keep only one Help Center Hero active at a time.
        This prevents the frontend from picking the wrong active hero.
        """
        super().save_model(request, obj, form, change)

        if obj.is_active:
            HelpCenterHero.objects.exclude(pk=obj.pk).update(is_active=False)


@admin.register(CareerCategory)
class CareerCategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "icon", "order", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["name", "slug"]
    prepopulated_fields = {"slug": ["name"]}
    list_editable = ["order", "is_active"]


@admin.register(JobPosition)
class JobPositionAdmin(admin.ModelAdmin):
    list_display = [
        "title",
        "category",
        "job_type",
        "experience_level",
        "location",
        "is_featured",
        "is_active",
        "is_open_status",
        "publish_date",
    ]
    list_filter = [
        "category",
        "job_type",
        "experience_level",
        "is_featured",
        "is_active",
    ]
    search_fields = ["title", "slug", "description", "requirements", "location"]
    prepopulated_fields = {"slug": ["title"]}
    list_editable = ["is_featured", "is_active"]
    readonly_fields = ["publish_date"]

    fieldsets = (
        ("Basic Information", {
            "fields": ("title", "slug", "category", "job_type", "experience_level"),
        }),
        ("Location & Compensation", {
            "fields": ("location", "salary_range"),
        }),
        ("Job Description", {
            "fields": ("description", "responsibilities", "requirements", "benefits"),
        }),
        ("Application Settings", {
            "fields": ("application_email", "application_url"),
        }),
        ("Publishing", {
            "fields": ("is_featured", "is_active", "publish_date", "closing_date"),
        }),
    )

    def is_open_status(self, obj):
        return obj.is_open()

    is_open_status.boolean = True
    is_open_status.short_description = "Open"


@admin.register(JobApplication)
class JobApplicationAdmin(admin.ModelAdmin):
    list_display = [
        "first_name",
        "last_name",
        "position",
        "email",
        "phone",
        "status",
        "created_at",
    ]
    list_filter = ["status", "position", "created_at"]
    search_fields = [
        "first_name",
        "last_name",
        "email",
        "phone",
        "position__title",
    ]
    readonly_fields = ["created_at", "updated_at"]

    fieldsets = (
        ("Applicant Information", {
            "fields": ("first_name", "last_name", "email", "phone"),
        }),
        ("Application Details", {
            "fields": (
                "position",
                "cover_letter",
                "resume",
                "portfolio_url",
                "linkedin_url",
            ),
        }),
        ("Review Status", {
            "fields": ("status", "notes"),
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )