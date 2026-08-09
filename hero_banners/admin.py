from django import forms
from django.contrib import admin
from django.utils.html import format_html

from .models import HeroBanner, HeroBannerAnalytics


class HeroBannerAdminForm(forms.ModelForm):
    COLOR_FIELDS = (
        "overlay_color",
        "text_color",
        "button1_background_color",
        "button1_text_color",
        "button1_border_color",
        "button2_background_color",
        "button2_text_color",
        "button2_border_color",
        "button3_background_color",
        "button3_text_color",
        "button3_border_color",
        "article_button_background_color",
        "article_button_text_color",
        "article_button_border_color",
    )

    class Meta:
        model = HeroBanner
        fields = "__all__"
        widgets = {
            "overlay_opacity": forms.NumberInput(
                attrs={
                    "min": "0",
                    "max": "1",
                    "step": "0.05",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for field_name in self.COLOR_FIELDS:
            if field_name not in self.fields:
                continue

            attrs = {
                "placeholder": "#2563eb",
                "style": "max-width: 9rem;",
            }

            if field_name in {
                "overlay_color",
                "text_color",
            }:
                attrs.update(
                    {
                        "type": "color",
                        "style": (
                            "width: 5rem; "
                            "padding: 0.15rem;"
                        ),
                    }
                )

            self.fields[field_name].widget = (
                forms.TextInput(
                    attrs=attrs,
                )
            )


@admin.register(HeroBanner)
class HeroBannerAdmin(admin.ModelAdmin):
    form = HeroBannerAdminForm

    list_display = [
        "title",
        "placement",
        "brand",
        "display_order",
        "is_active",
        "image_preview",
        "views_count",
        "clicks_count",
    ]

    list_editable = [
        "display_order",
        "is_active",
    ]

    list_filter = [
        "placement",
        "is_active",
        "brand",
    ]

    search_fields = [
        "title",
        "subtitle",
        "brand__name",
    ]

    autocomplete_fields = [
        "brand",
    ]

    readonly_fields = [
        "image_preview",
        "created_at",
        "updated_at",
    ]

    fieldsets = (
        (
            "Placement & Targeting",
            {
                "fields": (
                    "placement",
                    "brand",
                    "display_order",
                    "is_active",
                ),
                "description": (
                    "Choose where this banner appears. "
                    "Select a Brand only when Placement is "
                    "'Brand Detail Page'."
                ),
            },
        ),
        (
            "Basic Information",
            {
                "fields": (
                    "title",
                    "subtitle",
                    "description",
                    (
                        "show_content",
                        "show_title",
                        "show_subtitle",
                        "show_description",
                    ),
                ),
                "description": (
                    "Content switches let you hide overlay "
                    "text when the uploaded banner image "
                    "already contains its own design or text."
                ),
            },
        ),
        (
            "Media",
            {
                "fields": (
                    "image_desktop",
                    "image_tablet",
                    "image_mobile",
                    "image_preview",
                ),
                "description": (
                    "Upload desktop, tablet and mobile banner "
                    "artwork. Desktop is the primary image. "
                    "Use a dedicated mobile image whenever "
                    "possible for cleaner responsive cropping."
                ),
            },
        ),
        (
            "Responsive Display",
            {
                "fields": (
                    (
                        "desktop_height",
                        "image_fit_desktop",
                        "image_position_desktop",
                        "desktop_content_layout",
                    ),
                    (
                        "tablet_height",
                        "image_fit_tablet",
                        "image_position_tablet",
                        "tablet_content_layout",
                    ),
                    (
                        "mobile_height",
                        "image_fit_mobile",
                        "image_position_mobile",
                        "mobile_content_layout",
                    ),
                ),
                "description": (
                    "Control banner frame size, crop and dynamic "
                    "content visibility per device. Standard displays "
                    "Admin-managed title, description and CTA content "
                    "over the image. Image only displays the uploaded "
                    "artwork without the dynamic content layer on this "
                    "device."
                ),
            },
        ),
        (
            "Animation",
            {
                "fields": (
                    "animation_effect",
                    "animation_duration",
                    "autoplay_delay",
                ),
            },
        ),
        (
            "Whole Banner Click",
            {
                "fields": (
                    "enable_slide_link",
                    "slide_link_url",
                    "slide_open_behavior",
                ),
                "description": (
                    "Optional: make the entire banner clickable. "
                    "Useful when the uploaded artwork already "
                    "contains a visual CTA."
                ),
            },
        ),
        (
            "Buttons",
            {
                "fields": (
                    "show_buttons",
                    (
                        "button1_text",
                        "button1_url",
                        "button1_style",
                    ),
                    (
                        "button1_background_color",
                        "button1_text_color",
                        "button1_border_color",
                    ),
                    (
                        "button2_text",
                        "button2_url",
                        "button2_style",
                    ),
                    (
                        "button2_background_color",
                        "button2_text_color",
                        "button2_border_color",
                    ),
                    (
                        "button3_text",
                        "button3_url",
                        "button3_style",
                    ),
                    (
                        "button3_background_color",
                        "button3_text_color",
                        "button3_border_color",
                    ),
                ),
                "description": (
                    "Leave button text or URL empty to hide that "
                    "button. A # URL is treated as hidden. "
                    "Optional custom colors override the selected "
                    "button style."
                ),
            },
        ),
        (
            "Article Button",
            {
                "fields": (
                    "linked_article",
                    (
                        "article_button_text",
                        "article_open_behavior",
                    ),
                    (
                        "article_button_background_color",
                        "article_button_text_color",
                        "article_button_border_color",
                    ),
                ),
                "description": (
                    "Optional article CTA for banners linked to "
                    "Arolana editorial content."
                ),
                "classes": (
                    "collapse",
                ),
            },
        ),
        (
            "Styling",
            {
                "fields": (
                    "overlay_color",
                    "overlay_opacity",
                    "text_color",
                    "text_alignment",
                    "content_position",
                ),
                "description": (
                    "Overlay opacity: 0 = transparent, "
                    "1 = fully opaque."
                ),
                "classes": (
                    "collapse",
                ),
            },
        ),
        (
            "Scheduling",
            {
                "fields": (
                    "start_date",
                    "end_date",
                ),
                "classes": (
                    "collapse",
                ),
                "description": (
                    "Leave both dates empty for an always-active "
                    "banner. Scheduling only applies while the "
                    "banner is also marked Active."
                ),
            },
        ),
        (
            "System Information",
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

    BRAND_HERO_HELP_TEXT = {
        "image_desktop": "Desktop image (1920×600 recommended)",
        "image_tablet": "Tablet image (1200×500 recommended)",
        "image_mobile": "Mobile image (1080×720 recommended)",
        "desktop_height": (
            "Desktop hero display height in CSS pixels. "
            "Recommended around 500–600."
        ),
        "tablet_height": (
            "Tablet hero display height in CSS pixels. "
            "Recommended around 400–500."
        ),
        "mobile_height": (
            "Mobile hero display height. Recommended around 360–420. "
            "The uploaded mobile image may still be 1080×720."
        ),
        "desktop_content_layout": (
            "Standard displays Admin-managed title, description and CTA "
            "content over the image. Image only displays the uploaded "
            "artwork without the dynamic content layer on desktop."
        ),
        "tablet_content_layout": (
            "Standard displays Admin-managed title, description and CTA "
            "content over the image. Image only displays the uploaded "
            "artwork without the dynamic content layer on tablet."
        ),
        "mobile_content_layout": (
            "Standard displays Admin-managed title, description and CTA "
            "content over the image. Image only displays the uploaded "
            "artwork without the dynamic content layer on mobile."
        ),
    }

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        formfield = super().formfield_for_dbfield(
            db_field,
            request,
            **kwargs,
        )

        if db_field.name in self.BRAND_HERO_HELP_TEXT:
            formfield.help_text = self.BRAND_HERO_HELP_TEXT[
                db_field.name
            ]

        return formfield

    def image_preview(self, obj):
        if obj and obj.image_desktop:
            return format_html(
                (
                    '<img src="{}" '
                    'width="150" '
                    'height="70" '
                    'style="'
                    'object-fit:cover;'
                    'border-radius:8px;'
                    'border:1px solid #e5e7eb;'
                    'background:#f8fafc;'
                    '" />'
                ),
                obj.image_desktop.url,
            )

        return format_html(
            (
                '<span style="'
                'color:#9ca3af;'
                'font-weight:600;'
                '">'
                "No banner image uploaded"
                "</span>"
            )
        )

    image_preview.short_description = "Preview"


@admin.register(HeroBannerAnalytics)
class HeroBannerAnalyticsAdmin(admin.ModelAdmin):
    list_display = [
        "banner",
        "action",
        "timestamp",
    ]

    list_filter = [
        "action",
        "banner",
    ]

    search_fields = [
        "banner__title",
        "session_id",
        "user__email",
    ]

    readonly_fields = [
        "banner",
        "session_id",
        "user",
        "action",
        "timestamp",
    ]

    ordering = [
        "-timestamp",
    ]

    def has_add_permission(
        self,
        request,
    ):
        return False

    def has_change_permission(
        self,
        request,
        obj=None,
    ):
        return False
