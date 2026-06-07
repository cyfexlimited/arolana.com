from django.contrib import admin
from django.utils.html import format_html

from .models import MobileCustomer, MobileWishlistItem


class MobileWishlistItemInline(admin.TabularInline):
    model = MobileWishlistItem
    extra = 0
    autocomplete_fields = ["product"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(MobileCustomer)
class MobileCustomerAdmin(admin.ModelAdmin):
    list_display = [
        "profile_preview",
        "full_name",
        "phone_number",
        "email",
        "wishlist_count",
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

    list_filter = ["created_at", "last_login_at"]

    readonly_fields = [
        "profile_image_preview",
        "api_token",
        "pin_hash",
        "last_login_at",
        "created_at",
        "updated_at",
    ]

    inlines = [MobileWishlistItemInline]

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
                )
            },
        ),
        (
            "Security",
            {
                "fields": (
                    "api_token",
                    "pin_hash",
                    "last_login_at",
                )
            },
        ),
        (
            "Timestamps",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )

    def wishlist_count(self, obj):
        return obj.wishlist_items.count()

    wishlist_count.short_description = "Wishlist"

    def profile_preview(self, obj):
        if obj.profile_image:
            try:
                return format_html(
                    '<img src="{}" style="width:48px;height:48px;border-radius:50%;object-fit:cover;border:1px solid #ddd;background:#f8fafc;" />',
                    obj.profile_image.url,
                )
            except Exception as error:
                return f"Image error: {error}"
        return "No image"

    profile_preview.short_description = "Photo"

    def profile_image_preview(self, obj):
        if obj.profile_image:
            try:
                return format_html(
                    '<div style="margin-bottom:8px;">'
                    '<img src="{}" style="width:170px;height:170px;border-radius:22px;object-fit:cover;border:1px solid #ddd;background:#f8fafc;" />'
                    '</div>'
                    '<a href="{}" target="_blank">Open image</a>',
                    obj.profile_image.url,
                    obj.profile_image.url,
                )
            except Exception as error:
                return f"Image error: {error}"
        return "No profile image uploaded"

    profile_image_preview.short_description = "Profile Image Preview"


@admin.register(MobileWishlistItem)
class MobileWishlistItemAdmin(admin.ModelAdmin):
    list_display = ["customer", "product", "created_at"]
    search_fields = [
        "customer__full_name",
        "customer__phone_number",
        "customer__email",
        "product__name",
        "product__slug",
        "product__title",
    ]
    list_filter = ["created_at"]
    autocomplete_fields = ["customer", "product"]
    readonly_fields = ["created_at", "updated_at"]
