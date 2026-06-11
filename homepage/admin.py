from django.contrib import admin
from django.utils.html import format_html

from core.local_cache import local_delete, local_delete_prefix

from .models import (
    HomepageCategory,
    HomepageBanner,
    HomepageBannerImage,
    HomepageSection,
    HomepageSectionProduct,
    HomepageVendorSettings,
    HomepageNewsletterSettings,
    HomepageManufacturerSettings,
    HomepageManufacturerCategory,
    HomepageVideoSection,
    HomepageVendorSection,
)


# ============================================================
# CACHE CLEAR HELPERS
# ============================================================

def clear_homepage_banner_cache():
    """Clear every placement and style variant of the banner cache."""
    local_delete_prefix("homepage:banners:v4")


def clear_homepage_all_cache():
    """
    Clear homepage cache keys that can affect what appears on the homepage.
    """
    clear_homepage_banner_cache()
    local_delete("homepage:categories")
    local_delete("homepage:sections")
    local_delete("homepage:vendor_settings")
    local_delete("homepage:vendor_sections:v3")
    local_delete("homepage:newsletter_settings")
    local_delete("homepage:manufacturers_section")
    local_delete("homepage:video_section")


# ============================================================
# BANNER IMAGE INLINE
# ============================================================

class HomepageBannerImageInline(admin.TabularInline):
    model = HomepageBannerImage
    extra = 1
    fields = [
        "image_preview",
        "image",
        "position",
        "width_px",
        "height_px",
        "object_fit",
        "object_position",
        "animation",
        "display_order",
        "is_active",
    ]
    readonly_fields = [
        "image_preview",
    ]

    def image_preview(self, obj):
        if obj and obj.image:
            return format_html(
                '<img src="{}" width="80" height="55" '
                'style="object-fit:cover;border-radius:8px;border:1px solid #e5e7eb;" />',
                obj.image.url,
            )
        return "No Image"

    image_preview.short_description = "Preview"


# ============================================================
# HOMEPAGE CATEGORIES
# ============================================================

@admin.register(HomepageCategory)
class HomepageCategoryAdmin(admin.ModelAdmin):
    list_display = [
        "category",
        "icon_preview",
        "display_order",
        "is_active",
    ]
    list_editable = [
        "display_order",
        "is_active",
    ]
    list_filter = [
        "is_active",
    ]
    search_fields = [
        "category__name",
        "category__slug",
        "icon",
    ]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("category")

    def icon_preview(self, obj):
        icon_class = obj.icon or "fas fa-folder-open"
        return format_html(
            '<i class="{} fa-lg"></i> <code>{}</code>',
            icon_class,
            icon_class,
        )

    icon_preview.short_description = "Icon"

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        local_delete("homepage:categories")

    def delete_model(self, request, obj):
        super().delete_model(request, obj)
        local_delete("homepage:categories")

    def delete_queryset(self, request, queryset):
        super().delete_queryset(request, queryset)
        local_delete("homepage:categories")


# ============================================================
# HOMEPAGE BANNERS
# ============================================================

@admin.register(HomepageBanner)
class HomepageBannerAdmin(admin.ModelAdmin):
    list_display = [
        "title",
        "placement",
        "banner_style",
        "target_audience",
        "display_order",
        "show_on_homepage",
        "is_active",
        "preview",
    ]
    list_editable = [
        "placement",
        "banner_style",
        "display_order",
        "show_on_homepage",
        "is_active",
    ]
    list_filter = [
        "placement",
        "banner_style",
        "target_audience",
        "show_on_homepage",
        "is_active",
    ]
    search_fields = [
        "title",
        "subtitle",
        "button_text",
        "button_url",
    ]
    inlines = [
        HomepageBannerImageInline,
    ]

    fieldsets = (
        (
            "📝 Content",
            {
                "fields": (
                    "title",
                    "subtitle",
                    "button_text",
                    "button_url",
                ),
                "description": "Main banner text and call-to-action for Arolana.",
            },
        ),
        (
            "📍 Homepage Placement",
            {
                "fields": (
                    "placement",
                    "banner_style",
                    "display_order",
                    "show_on_homepage",
                    "is_active",
                ),
                "description": (
                    "Control exactly where this Arolana banner appears on the homepage "
                    "and what visual structure it uses."
                ),
            },
        ),
        (
            "👥 Audience",
            {
                "fields": (
                    "target_audience",
                ),
                "description": (
                    "Choose who should see this banner: everyone, guests, customers, "
                    "vendors, manufacturers, or staff."
                ),
            },
        ),
        (
            "🎨 Styling",
            {
                "fields": (
                    ("background_color_start", "background_color_end"),
                    ("desktop_height", "tablet_height", "mobile_height"),
                    ("content_layout", "content_alignment"),
                    ("background_fit", "background_position", "background_opacity"),
                    "full_width",
                ),
                "description": (
                    "Control banner height, gradient colors, background fit, position, "
                    "opacity, width, and text alignment."
                ),
            },
        ),
        (
            "🖼 Floating URL Images",
            {
                "fields": (
                    "left_image",
                    "right_image",
                    "center_image",
                    "left_animation",
                    "right_animation",
                    "center_animation",
                ),
                "classes": ("collapse",),
                "description": (
                    "Optional URL-based floating images. For uploaded images, use the inline image table below."
                ),
            },
        ),
    )

    def preview(self, obj):
        img = (
            obj.uploaded_images
            .filter(is_active=True)
            .order_by("display_order", "id")
            .first()
        )
        if img and img.image:
            return format_html(
                '<img src="{}" width="100" height="60" '
                'style="object-fit:cover;border-radius:8px;border:1px solid #e5e7eb;" />',
                img.image.url,
            )
        return "No Image"

    preview.short_description = "Preview"

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        clear_homepage_banner_cache()

    def delete_model(self, request, obj):
        super().delete_model(request, obj)
        clear_homepage_banner_cache()

    def delete_queryset(self, request, queryset):
        super().delete_queryset(request, queryset)
        clear_homepage_banner_cache()


# ============================================================
# HOMEPAGE PRODUCT SECTIONS
# ============================================================

class HomepageSectionProductInline(admin.TabularInline):
    model = HomepageSectionProduct
    extra = 0
    autocomplete_fields = ["product"]
    fields = ["product", "display_order", "is_active"]
    ordering = ["display_order", "id"]


@admin.register(HomepageSection)
class HomepageSectionAdmin(admin.ModelAdmin):
    list_display = [
        "title",
        "section_type",
        "layout_style",
        "sort_mode",
        "products_limit",
        "use_subscription_priority",
        "display_order",
        "is_active",
    ]
    list_editable = [
        "layout_style",
        "sort_mode",
        "products_limit",
        "use_subscription_priority",
        "display_order",
        "is_active",
    ]
    list_filter = [
        "section_type",
        "layout_style",
        "sort_mode",
        "vendor_type",
        "verified_vendors_only",
        "use_subscription_priority",
        "is_active",
    ]
    search_fields = [
        "title",
        "subtitle",
        "view_all_url",
    ]
    autocomplete_fields = ["category", "brand"]
    inlines = [HomepageSectionProductInline]

    fieldsets = (
        (
            "📝 Content",
            {
                "fields": (
                    "title",
                    "subtitle",
                    "section_type",
                    "layout_style",
                    ("view_all_text", "view_all_url"),
                    "show_view_all",
                    "empty_state_text",
                ),
            },
        ),
        (
            "📦 Product Source & Ranking",
            {
                "fields": (
                    "sort_mode",
                    ("category", "brand"),
                    ("vendor_type", "verified_vendors_only"),
                    ("use_subscription_priority", "fill_automatically"),
                    "products_limit",
                ),
                "description": (
                    "Curated products below always appear first. Automatic products then fill "
                    "the remaining slots using these filters and active vendor-plan priority."
                ),
            },
        ),
        (
            "🎨 Card Content & Styling",
            {
                "fields": (
                    ("accent_color", "background_color"),
                    ("show_vendor", "show_subscription_badge"),
                    ("show_rating", "show_price", "show_add_to_cart"),
                ),
            },
        ),
        (
            "⚙️ Publishing",
            {
                "fields": (
                    "display_order",
                    "is_active",
                ),
                "description": (
                    "This controls homepage product rows like Featured Products, "
                    "New Arrivals, Best Sellers, and Trending Deals."
                ),
            },
        ),
    )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        local_delete("homepage:sections")

    def delete_model(self, request, obj):
        super().delete_model(request, obj)
        local_delete("homepage:sections")

    def delete_queryset(self, request, queryset):
        super().delete_queryset(request, queryset)
        local_delete("homepage:sections")


# ============================================================
# VENDOR SETTINGS SINGLE INSTANCE
# ============================================================

@admin.register(HomepageVendorSettings)
class HomepageVendorSettingsAdmin(admin.ModelAdmin):
    list_display = [
        "title",
        "vendor_count",
        "autoplay_speed",
        "is_active",
    ]

    fieldsets = (
        (
            "📝 Content",
            {
                "fields": (
                    "title",
                    "subtitle",
                ),
            },
        ),
        (
            "🎛 Display Settings",
            {
                "fields": (
                    "vendor_count",
                    "autoplay_speed",
                    "is_active",
                ),
            },
        ),
    )

    def has_add_permission(self, request):
        return not HomepageVendorSettings.objects.exists()

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        local_delete("homepage:vendor_settings")

    def delete_model(self, request, obj):
        super().delete_model(request, obj)
        local_delete("homepage:vendor_settings")


# ============================================================
# VENDOR MARKETPLACE SECTIONS
# ============================================================

@admin.register(HomepageVendorSection)
class HomepageVendorSectionAdmin(admin.ModelAdmin):
    list_display = [
        "title",
        "section_type",
        "vendor_type_filter",
        "verified_only",
        "manufacturer_only",
        "max_items",
        "sort_order",
        "show_when_empty",
        "show_view_all",
        "is_active",
    ]
    list_editable = [
        "max_items",
        "sort_order",
        "show_when_empty",
        "show_view_all",
        "is_active",
    ]
    list_filter = [
        "section_type",
        "vendor_type_filter",
        "verified_only",
        "manufacturer_only",
        "show_when_empty",
        "show_view_all",
        "is_active",
    ]
    search_fields = [
        "title",
        "description",
        "empty_state_text",
        "view_all_url",
    ]

    fieldsets = (
        (
            "📝 Content",
            {
                "fields": (
                    "title",
                    "description",
                    "section_type",
                    "empty_state_text",
                ),
            },
        ),
        (
            "🔎 Vendor Filters",
            {
                "fields": (
                    "vendor_type_filter",
                    "verified_only",
                    "manufacturer_only",
                ),
                "description": (
                    "Factory Direct Manufacturers should be locked to manufacturer vendors only."
                ),
            },
        ),
        (
            "🎛 Display",
            {
                "fields": (
                    "view_all_url",
                    "show_view_all",
                    "show_when_empty",
                    "max_items",
                    "sort_order",
                    "is_active",
                ),
            },
        ),
    )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        local_delete("homepage:vendor_sections:v3")

    def delete_model(self, request, obj):
        super().delete_model(request, obj)
        local_delete("homepage:vendor_sections:v3")

    def delete_queryset(self, request, queryset):
        super().delete_queryset(request, queryset)
        local_delete("homepage:vendor_sections:v3")


# ============================================================
# NEWSLETTER SETTINGS SINGLE INSTANCE
# ============================================================

@admin.register(HomepageNewsletterSettings)
class HomepageNewsletterSettingsAdmin(admin.ModelAdmin):
    list_display = [
        "title",
        "button_text",
        "is_active",
    ]

    search_fields = [
        "title",
        "subtitle",
        "button_text",
    ]

    fieldsets = (
        (
            "📝 Content",
            {
                "fields": (
                    "title",
                    "subtitle",
                    "button_text",
                ),
            },
        ),
        (
            "🎨 Styling",
            {
                "fields": (
                    "background_color",
                ),
                "description": "Control the newsletter background color.",
            },
        ),
        (
            "⚙️ Settings",
            {
                "fields": (
                    "is_active",
                ),
            },
        ),
    )

    def has_add_permission(self, request):
        return not HomepageNewsletterSettings.objects.exists()

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        local_delete("homepage:newsletter_settings")

    def delete_model(self, request, obj):
        super().delete_model(request, obj)
        local_delete("homepage:newsletter_settings")


# ============================================================
# BANNER IMAGE ADMIN
# ============================================================

@admin.register(HomepageBannerImage)
class HomepageBannerImageAdmin(admin.ModelAdmin):
    list_display = [
        "banner",
        "position",
        "image_preview",
        "display_order",
        "is_active",
    ]
    list_editable = [
        "display_order",
        "is_active",
    ]
    list_filter = [
        "position",
        "is_active",
        "banner",
    ]
    search_fields = [
        "banner__title",
    ]
    readonly_fields = [
        "image_preview",
    ]
    autocomplete_fields = [
        "banner",
    ]

    fieldsets = (
        (
            "🖼 Image",
            {
                "fields": (
                    "banner",
                    "image",
                    "image_preview",
                    "position",
                ),
            },
        ),
        (
            "📐 Image Sizing",
            {
                "fields": (
                    "width_px",
                    "height_px",
                    "object_fit",
                    "object_position",
                ),
            },
        ),
        (
            "🎞 Animation & Order",
            {
                "fields": (
                    "animation",
                    "display_order",
                    "is_active",
                ),
            },
        ),
    )

    def image_preview(self, obj):
        if obj and obj.image:
            return format_html(
                '<img src="{}" width="110" height="70" '
                'style="object-fit:cover;border-radius:8px;border:1px solid #e5e7eb;" />',
                obj.image.url,
            )
        return "No Image"

    image_preview.short_description = "Preview"

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        clear_homepage_banner_cache()

    def delete_model(self, request, obj):
        super().delete_model(request, obj)
        clear_homepage_banner_cache()

    def delete_queryset(self, request, queryset):
        super().delete_queryset(request, queryset)
        clear_homepage_banner_cache()


# ============================================================
# MANUFACTURER SETTINGS SINGLE INSTANCE
# ============================================================

@admin.register(HomepageManufacturerSettings)
class HomepageManufacturerSettingsAdmin(admin.ModelAdmin):
    list_display = [
        "title",
        "display_count",
        "display_order",
        "is_active",
    ]
    list_editable = [
        "display_count",
        "display_order",
        "is_active",
    ]
    search_fields = [
        "title",
        "subtitle",
    ]

    fieldsets = (
        (
            "📝 Content",
            {
                "fields": (
                    "title",
                    "subtitle",
                    "display_count",
                    "show_featured_only",
                ),
            },
        ),
        (
            "⚙️ Settings",
            {
                "fields": (
                    "display_order",
                    "is_active",
                ),
            },
        ),
    )

    def has_add_permission(self, request):
        return not HomepageManufacturerSettings.objects.exists()

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        local_delete("homepage:manufacturers_section")

    def delete_model(self, request, obj):
        super().delete_model(request, obj)
        local_delete("homepage:manufacturers_section")


# ============================================================
# MANUFACTURER CATEGORIES
# ============================================================

@admin.register(HomepageManufacturerCategory)
class HomepageManufacturerCategoryAdmin(admin.ModelAdmin):
    list_display = [
        "category",
        "icon",
        "display_order",
        "is_active",
    ]
    list_editable = [
        "icon",
        "display_order",
        "is_active",
    ]
    list_filter = [
        "is_active",
    ]
    search_fields = [
        "category__name",
        "category__slug",
        "icon",
    ]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("category")

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        local_delete("homepage:manufacturers_section")

    def delete_model(self, request, obj):
        super().delete_model(request, obj)
        local_delete("homepage:manufacturers_section")

    def delete_queryset(self, request, queryset):
        super().delete_queryset(request, queryset)
        local_delete("homepage:manufacturers_section")


# ============================================================
# VIDEO SECTION
# ============================================================

@admin.register(HomepageVideoSection)
class HomepageVideoSectionAdmin(admin.ModelAdmin):
    list_display = [
        "title",
        "video_source",
        "info_position",
        "position",
        "display_order",
        "is_active",
        "status",
    ]
    list_editable = [
        "info_position",
        "position",
        "display_order",
        "is_active",
    ]
    list_filter = [
        "video_source",
        "info_position",
        "position",
        "is_active",
    ]
    search_fields = [
        "title",
        "subtitle",
        "youtube_url",
        "vimeo_url",
        "button_text",
        "button_url",
    ]

    fieldsets = (
        (
            "📝 Content",
            {
                "fields": (
                    "title",
                    "subtitle",
                ),
            },
        ),
        (
            "🎥 Source",
            {
                "fields": (
                    "video_source",
                ),
            },
        ),
        (
            "📺 YouTube",
            {
                "fields": (
                    "youtube_url",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "🎬 Vimeo",
            {
                "fields": (
                    "vimeo_url",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "💾 Local Video",
            {
                "fields": (
                    "local_video",
                    "poster_image",
                ),
            },
        ),
        (
            "📐 Layout",
            {
                "fields": (
                    "info_position",
                    "position",
                    "video_width",
                    "video_height",
                    "background_color",
                    "text_color",
                ),
                "description": (
                    "Info position controls where title, subtitle, and CTA appear relative to the video. "
                    "Position aligns the full block inside the homepage section."
                ),
            },
        ),
        (
            "⚙️ Behavior",
            {
                "fields": (
                    "autoplay",
                    "loop",
                    "show_controls",
                ),
            },
        ),
        (
            "🔘 CTA",
            {
                "fields": (
                    "button_text",
                    "button_url",
                    "button_color",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "📊 Settings",
            {
                "fields": (
                    "display_order",
                    "is_active",
                ),
            },
        ),
    )

    def status(self, obj):
        if obj.video_source == "youtube" and obj.youtube_id:
            return format_html('<span style="color:green;font-weight:700;">YouTube Ready</span>')

        if obj.video_source == "local" and obj.local_video:
            return format_html('<span style="color:blue;font-weight:700;">Local Ready</span>')

        if obj.video_source == "vimeo" and obj.vimeo_id:
            return format_html('<span style="color:purple;font-weight:700;">Vimeo Ready</span>')

        return format_html('<span style="color:orange;font-weight:700;">Not Configured</span>')

    status.short_description = "Status"

    def has_add_permission(self, request):
        return not HomepageVideoSection.objects.exists()

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        local_delete("homepage:video_section")

    def delete_model(self, request, obj):
        super().delete_model(request, obj)
        local_delete("homepage:video_section")

    def delete_queryset(self, request, queryset):
        super().delete_queryset(request, queryset)
        local_delete("homepage:video_section")
