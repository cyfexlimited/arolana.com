import hashlib
from urllib.parse import quote

from django.contrib import admin
from django.db.models import Count
from django.utils.html import format_html

from .models import MobileCustomer, MobileWishlistItem


def protected_media_url(field_file):
    """
    Return a URL that always passes through Arolana's protected
    Django /media/ authorization route.

    Never use field_file.url for private mobile customer media.
    """
    if not field_file:
        return ""

    name = getattr(field_file, "name", "") or ""

    if not name:
        return ""

    safe_path = quote(
        name.lstrip("/"),
        safe="/",
    )

    return f"/media/{safe_path}"


class MobileWishlistItemInline(admin.TabularInline):
    model = MobileWishlistItem
    extra = 0

    fields = [
        "product",
        "created_at",
        "updated_at",
    ]

    readonly_fields = [
        "product",
        "created_at",
        "updated_at",
    ]

    can_delete = False
    show_change_link = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(MobileCustomer)
class MobileCustomerAdmin(admin.ModelAdmin):
    list_display = [
        "profile_preview",
        "full_name",
        "phone_number",
        "email",
        "wishlist_count",
        "token_status",
        "last_login_at",
        "created_at",
    ]

    search_fields = [
        "full_name",
        "phone_number",
        "email",
        "user__username",
        "user__email",
    ]

    list_filter = [
        "created_at",
        "last_login_at",
    ]

    list_select_related = [
        "user",
    ]

    readonly_fields = [
        "profile_image_preview",
        "token_security_status",
        "pin_security_status",
        "last_login_at",
        "created_at",
        "updated_at",
    ]

    inlines = [
        MobileWishlistItemInline,
    ]

    fieldsets = (
        (
            "Customer Profile",
            {
                "fields": (
                    "profile_image_preview",
                    "profile_image",
                    "full_name",
                    "phone_number",
                    "email",
                    "user",
                ),
            },
        ),
        (
            "Preferences",
            {
                "fields": (
                    "preferred_language",
                    "notification_preferences",
                ),
            },
        ),
        (
            "Security",
            {
                "fields": (
                    "token_security_status",
                    "pin_security_status",
                    "last_login_at",
                ),
                "description": (
                    "Sensitive credentials are intentionally hidden. "
                    "Only credential status and a non-reversible token "
                    "fingerprint are displayed."
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
            },
        ),
    )

    def get_queryset(self, request):
        queryset = super().get_queryset(request)

        return queryset.annotate(
            _wishlist_count=Count(
                "wishlist_items",
                distinct=True,
            ),
        )

    @admin.display(
        description="Wishlist",
        ordering="_wishlist_count",
    )
    def wishlist_count(self, obj):
        return getattr(
            obj,
            "_wishlist_count",
            0,
        )

    @admin.display(
        description="Token",
    )
    def token_status(self, obj):
        if obj.api_token:
            return "Issued"

        return "Not issued"

    @admin.display(
        description="API Token Security",
    )
    def token_security_status(self, obj):
        if not obj or not obj.api_token:
            return "No API token issued"

        fingerprint = hashlib.sha256(
            obj.api_token.encode("utf-8"),
        ).hexdigest()[:12]

        return format_html(
            '<div style="line-height:1.6;">'
            '<strong>Token issued</strong><br>'
            '<span style="color:#64748b;">'
            'Fingerprint: <code>{}</code>'
            '</span><br>'
            '<small style="color:#64748b;">'
            'The bearer token itself is intentionally hidden.'
            '</small>'
            '</div>',
            fingerprint,
        )

    @admin.display(
        description="PIN Security",
    )
    def pin_security_status(self, obj):
        if not obj:
            return "No customer selected"

        if obj.pin_hash:
            return "PIN configured"

        return "PIN not configured"

    @admin.display(
        description="Photo",
    )
    def profile_preview(self, obj):
        if not obj.profile_image:
            return "No image"

        image_url = protected_media_url(
            obj.profile_image,
        )

        if not image_url:
            return "No image"

        return format_html(
            '<img '
            'src="{}" '
            'alt="{} profile photo" '
            'style="'
            'width:48px;'
            'height:48px;'
            'border-radius:50%;'
            'object-fit:cover;'
            'border:1px solid #ddd;'
            'background:#f8fafc;'
            '" '
            '/>',
            image_url,
            obj.full_name or obj.phone_number,
        )

    @admin.display(
        description="Profile Image Preview",
    )
    def profile_image_preview(self, obj):
        if not obj or not obj.profile_image:
            return "No profile image uploaded"

        image_url = protected_media_url(
            obj.profile_image,
        )

        if not image_url:
            return "No profile image uploaded"

        return format_html(
            '<div style="margin-bottom:8px;">'
            '<img '
            'src="{}" '
            'alt="{} profile image" '
            'style="'
            'width:170px;'
            'height:170px;'
            'border-radius:22px;'
            'object-fit:cover;'
            'border:1px solid #ddd;'
            'background:#f8fafc;'
            '" '
            '/>'
            '</div>'
            '<a '
            'href="{}" '
            'target="_blank" '
            'rel="noopener noreferrer"'
            '>'
            'Open protected image'
            '</a>',
            image_url,
            obj.full_name or obj.phone_number,
            image_url,
        )


@admin.register(MobileWishlistItem)
class MobileWishlistItemAdmin(admin.ModelAdmin):
    list_display = [
        "customer",
        "product",
        "created_at",
    ]

    search_fields = [
        "customer__full_name",
        "customer__phone_number",
        "customer__email",
        "product__name",
        "product__slug",
        "product__title",
    ]

    list_filter = [
        "created_at",
    ]

    autocomplete_fields = [
        "customer",
        "product",
    ]

    readonly_fields = [
        "created_at",
        "updated_at",
    ]

    list_select_related = [
        "customer",
        "product",
    ]