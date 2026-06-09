from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html

from .models import (
    LandingPage,
    LandingPageBenefit,
    LandingPageCTA,
    LandingPageCategoryCard,
    LandingPageComparisonItem,
    LandingPageContactOption,
    LandingPageFAQ,
    LandingPageOffer,
    LandingPageSection,
    LandingPageStep,
    LandingPageTestimonial,
    LandingPageVideoGuide,
)


class SortableInlineMixin:
    extra = 0
    ordering = ("sort_order",)


class LandingPageSectionInline(SortableInlineMixin, admin.StackedInline):
    model = LandingPageSection
    fields = (
        "section_type",
        "title",
        "subtitle",
        "content",
        ("background_color", "text_color"),
        ("image", "video_url"),
        ("button_text", "button_url"),
        ("sort_order", "is_active"),
        "extra_data",
    )


class LandingPageBenefitInline(SortableInlineMixin, admin.TabularInline):
    model = LandingPageBenefit
    fields = ("section", "icon", "title", "description", "link_text", "link_url", "sort_order", "is_active")


class LandingPageOfferInline(SortableInlineMixin, admin.StackedInline):
    model = LandingPageOffer
    fields = (
        "section",
        ("icon", "offer_label"),
        "title",
        "description",
        ("price_text", "discount_text"),
        ("button_text", "button_url"),
        "image",
        ("start_date", "end_date"),
        ("sort_order", "is_active"),
    )


class LandingPageStepInline(SortableInlineMixin, admin.TabularInline):
    model = LandingPageStep
    fields = ("section", "step_number", "icon", "title", "description", "sort_order", "is_active")


class LandingPageCategoryCardInline(SortableInlineMixin, admin.StackedInline):
    model = LandingPageCategoryCard
    fields = ("section", "icon", "title", "description", "image", "category", "button_text", "button_url", "sort_order", "is_active")
    autocomplete_fields = ("category",)


class LandingPageComparisonItemInline(SortableInlineMixin, admin.TabularInline):
    model = LandingPageComparisonItem
    fields = ("section", "side", "icon", "title", "description", "sort_order", "is_active")


class LandingPageTestimonialInline(SortableInlineMixin, admin.StackedInline):
    model = LandingPageTestimonial
    fields = ("section", "quote", ("customer_name", "customer_title"), "customer_location", "rating", "image", "sort_order", "is_active")


class LandingPageFAQInline(SortableInlineMixin, admin.StackedInline):
    model = LandingPageFAQ
    fields = ("section", "question", "answer", "sort_order", "is_active")


class LandingPageCTAInline(SortableInlineMixin, admin.TabularInline):
    model = LandingPageCTA
    fields = ("section", "label", "url", "style", "open_behavior", "icon", "sort_order", "is_active")


class LandingPageContactOptionInline(SortableInlineMixin, admin.TabularInline):
    model = LandingPageContactOption
    fields = ("icon", "label", "value", "url", "sort_order", "is_active")


class LandingPageVideoGuideInline(SortableInlineMixin, admin.StackedInline):
    model = LandingPageVideoGuide
    fields = ("section", "title", "subtitle", "description", "video_url", "thumbnail", "duration", "platform", "button_text", "sort_order", "is_active")


@admin.register(LandingPage)
class LandingPageAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "slug",
        "page_type",
        "status",
        "is_active",
        "is_featured",
        "show_on_homepage",
        "background_preview",
        "preview_link",
        "published_at",
        "updated_at",
    )
    list_filter = ("page_type", "status", "is_active", "is_featured", "show_on_homepage")
    search_fields = ("title", "slug", "hero_headline", "meta_title")
    date_hierarchy = "published_at"
    prepopulated_fields = {"slug": ("title",)}
    readonly_fields = ("created_at", "updated_at", "preview_link", "background_preview")
    actions = ("publish_pages", "unpublish_pages", "feature_pages", "unfeature_pages")
    inlines = [
        LandingPageSectionInline,
        LandingPageBenefitInline,
        LandingPageOfferInline,
        LandingPageStepInline,
        LandingPageCategoryCardInline,
        LandingPageComparisonItemInline,
        LandingPageTestimonialInline,
        LandingPageFAQInline,
        LandingPageCTAInline,
        LandingPageContactOptionInline,
        LandingPageVideoGuideInline,
    ]
    fieldsets = (
        ("Basic Information", {
            "fields": ("title", "slug", "subtitle", "page_type", "navigation_label", ("show_in_nav", "show_on_homepage"))
        }),
        ("Hero Section", {
            "fields": (
                "hero_badge_text",
                "hero_headline",
                "hero_subheadline",
                ("hero_background_image", "hero_mobile_image"),
                "hero_video_url",
                "hero_overlay_opacity",
                "trust_badges",
            )
        }),
        ("Call To Action", {
            "fields": (("primary_cta_text", "primary_cta_url"), ("secondary_cta_text", "secondary_cta_url"))
        }),
        ("Branding & Colors", {
            "fields": (("primary_color", "accent_color"), ("dark_color", "background_color", "text_color"))
        }),
        ("Full Page Background", {
            "fields": (
                "background_preview",
                ("page_background_image", "page_mobile_background_image"),
                ("page_background_overlay_opacity", "page_mobile_background_overlay_opacity"),
                ("page_background_blur", "page_background_fixed"),
                ("page_background_position", "page_mobile_background_position"),
            ),
            "description": (
                "Upload separate desktop and mobile landing page background images. "
                "Recommended desktop: 1920x1080 WebP. Recommended mobile: 1080x1350 WebP or 1080x1920 WebP."
            ),
        }),
        ("SEO & Metadata", {
            "fields": ("meta_title", "meta_description", "meta_keywords", "og_title", "og_description", "og_image", "canonical_url", "schema_markup")
        }),
        ("Publication", {
            "fields": ("status", "is_active", "is_featured", "published_at")
        }),
        ("Advanced", {
            "fields": ("custom_css", "preview_link", "created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )


    def background_preview(self, obj):
        if not obj:
            return "No background preview."

        desktop_html = ""
        mobile_html = ""

        if getattr(obj, "page_background_image", None):
            try:
                desktop_html = format_html(
                    '<div style="margin-right:14px;">'
                    '<div style="font-weight:700;margin-bottom:6px;color:#111827;">Desktop Background</div>'
                    '<div style="width:230px;height:95px;border-radius:12px;overflow:hidden;'
                    'border:1px solid #e5e7eb;background:#f8fafc;">'
                    '<img src="{}" style="width:100%;height:100%;object-fit:cover;" alt="Desktop landing background">'
                    '</div>'
                    '<div style="font-size:11px;color:#6b7280;margin-top:4px;">Recommended: 1920×1080 WebP</div>'
                    '</div>',
                    obj.page_background_image.url,
                )
            except Exception:
                desktop_html = "Desktop image exists but could not be previewed."

        if getattr(obj, "page_mobile_background_image", None):
            try:
                mobile_html = format_html(
                    '<div>'
                    '<div style="font-weight:700;margin-bottom:6px;color:#111827;">Mobile Background</div>'
                    '<div style="width:95px;height:125px;border-radius:12px;overflow:hidden;'
                    'border:1px solid #e5e7eb;background:#f8fafc;">'
                    '<img src="{}" style="width:100%;height:100%;object-fit:cover;" alt="Mobile landing background">'
                    '</div>'
                    '<div style="font-size:11px;color:#6b7280;margin-top:4px;">Recommended: 1080×1350 WebP</div>'
                    '</div>',
                    obj.page_mobile_background_image.url,
                )
            except Exception:
                mobile_html = "Mobile image exists but could not be previewed."

        if not desktop_html and not mobile_html:
            return "No background images uploaded."

        return format_html(
            '<div style="display:flex;align-items:flex-start;gap:10px;flex-wrap:wrap;">{}{}</div>',
            desktop_html,
            mobile_html,
        )
    background_preview.short_description = "Background Preview"


    def preview_link(self, obj):
        if not obj or not obj.slug:
            return "Save first to preview."
        return format_html('<a class="button" href="/landing-preview/{}/" target="_blank">Preview page</a>', obj.slug)
    preview_link.short_description = "Preview"

    def publish_pages(self, request, queryset):
        count = queryset.update(status=LandingPage.STATUS_PUBLISHED, is_active=True, published_at=timezone.now())
        self.message_user(request, f"{count} landing page(s) published.")
    publish_pages.short_description = "Publish selected pages"

    def unpublish_pages(self, request, queryset):
        count = queryset.update(status=LandingPage.STATUS_DRAFT)
        self.message_user(request, f"{count} landing page(s) moved to draft.")
    unpublish_pages.short_description = "Unpublish selected pages"

    def feature_pages(self, request, queryset):
        count = queryset.update(is_featured=True)
        self.message_user(request, f"{count} landing page(s) featured.")
    feature_pages.short_description = "Feature selected pages"

    def unfeature_pages(self, request, queryset):
        count = queryset.update(is_featured=False)
        self.message_user(request, f"{count} landing page(s) unfeatured.")
    unfeature_pages.short_description = "Unfeature selected pages"


@admin.register(LandingPageSection)
class LandingPageSectionAdmin(admin.ModelAdmin):
    list_display = ("title", "landing_page", "section_type", "sort_order", "is_active")
    list_filter = ("section_type", "is_active")
    search_fields = ("title", "subtitle", "landing_page__title")
    autocomplete_fields = ("landing_page",)


@admin.register(LandingPageBenefit)
class LandingPageBenefitAdmin(admin.ModelAdmin):
    list_display = ("title", "landing_page", "sort_order", "is_active")
    list_filter = ("is_active",)
    search_fields = ("title", "description", "landing_page__title")


@admin.register(LandingPageOffer)
class LandingPageOfferAdmin(admin.ModelAdmin):
    list_display = ("title", "landing_page", "offer_label", "sort_order", "is_active")
    list_filter = ("is_active",)
    search_fields = ("title", "description", "landing_page__title")


@admin.register(LandingPageStep)
class LandingPageStepAdmin(admin.ModelAdmin):
    list_display = ("title", "landing_page", "step_number", "sort_order", "is_active")
    list_filter = ("is_active",)
    search_fields = ("title", "description", "landing_page__title")


@admin.register(LandingPageCategoryCard)
class LandingPageCategoryCardAdmin(admin.ModelAdmin):
    list_display = ("title", "landing_page", "category", "sort_order", "is_active")
    list_filter = ("is_active",)
    search_fields = ("title", "description", "landing_page__title", "category__name")
    autocomplete_fields = ("category",)


@admin.register(LandingPageComparisonItem)
class LandingPageComparisonItemAdmin(admin.ModelAdmin):
    list_display = ("title", "landing_page", "side", "sort_order", "is_active")
    list_filter = ("side", "is_active")
    search_fields = ("title", "description", "landing_page__title")


@admin.register(LandingPageTestimonial)
class LandingPageTestimonialAdmin(admin.ModelAdmin):
    list_display = ("customer_name", "landing_page", "rating", "sort_order", "is_active")
    list_filter = ("rating", "is_active")
    search_fields = ("quote", "customer_name", "customer_title", "landing_page__title")


@admin.register(LandingPageFAQ)
class LandingPageFAQAdmin(admin.ModelAdmin):
    list_display = ("question", "landing_page", "sort_order", "is_active")
    list_filter = ("is_active",)
    search_fields = ("question", "answer", "landing_page__title")


@admin.register(LandingPageCTA)
class LandingPageCTAAdmin(admin.ModelAdmin):
    list_display = ("label", "landing_page", "style", "open_behavior", "sort_order", "is_active")
    list_filter = ("style", "open_behavior", "is_active")
    search_fields = ("label", "url", "landing_page__title")


@admin.register(LandingPageContactOption)
class LandingPageContactOptionAdmin(admin.ModelAdmin):
    list_display = ("label", "value", "landing_page", "sort_order", "is_active")
    list_filter = ("is_active",)
    search_fields = ("label", "value", "url", "landing_page__title")


@admin.register(LandingPageVideoGuide)
class LandingPageVideoGuideAdmin(admin.ModelAdmin):
    list_display = ("title", "landing_page", "platform", "duration", "sort_order", "is_active")
    list_filter = ("platform", "is_active")
    search_fields = ("title", "subtitle", "video_url", "landing_page__title")
