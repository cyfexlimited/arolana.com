from django.contrib import admin
from django.db.models import Count
from django.utils.html import format_html
from django.utils.timezone import localtime

from .models import ClickEvent, PageVisit


class SuperuserOnlyAdminMixin:
    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser


@admin.register(PageVisit)
class PageVisitAdmin(SuperuserOnlyAdminMixin, admin.ModelAdmin):
    list_display = [
        "created_at_display",
        "country",
        "device_type",
        "browser",
        "operating_system",
        "ip_address",
        "user_display",
        "short_path",
        "status_code",
        "is_bot",
    ]

    list_filter = [
        "country",
        "device_type",
        "browser",
        "operating_system",
        "is_authenticated",
        "is_bot",
        "status_code",
        "created_at",
    ]

    search_fields = [
        "ip_address",
        "country",
        "user_agent",
        "referrer",
        "page_url",
        "path",
        "session_key",
        "user__email",
        "user__username",
    ]

    readonly_fields = [
        "user",
        "ip_address",
        "country",
        "user_agent",
        "device_type",
        "browser",
        "operating_system",
        "referrer",
        "page_url",
        "path",
        "session_key",
        "method",
        "status_code",
        "is_authenticated",
        "is_bot",
        "created_at",
    ]

    date_hierarchy = "created_at"
    ordering = ["-created_at"]
    list_per_page = 50

    def created_at_display(self, obj):
        return localtime(obj.created_at).strftime("%Y-%m-%d %H:%M:%S")

    created_at_display.short_description = "Date"

    def user_display(self, obj):
        if obj.user:
            return str(obj.user)
        return "-"

    user_display.short_description = "User"

    def short_path(self, obj):
        if not obj.path:
            return "-"
        label = obj.path[:80]
        return format_html('<a href="{}" target="_blank">{}</a>', obj.page_url, label)

    short_path.short_description = "Page URL"


@admin.register(ClickEvent)
class ClickEventAdmin(SuperuserOnlyAdminMixin, admin.ModelAdmin):
    list_display = [
        "created_at_display",
        "event_type",
        "country",
        "device_type",
        "browser",
        "ip_address",
        "user_display",
        "clicked_text_display",
        "clicked_url_display",
        "page_display",
    ]

    list_filter = [
        "event_type",
        "country",
        "device_type",
        "browser",
        "operating_system",
        "is_authenticated",
        "is_bot",
        "created_at",
    ]

    search_fields = [
        "ip_address",
        "country",
        "user_agent",
        "referrer",
        "page_url",
        "path",
        "clicked_text",
        "clicked_url",
        "element_tag",
        "element_id",
        "element_classes",
        "product_id",
        "category_id",
        "vendor_id",
        "landing_page_id",
        "session_key",
        "user__email",
        "user__username",
    ]

    readonly_fields = [
        "user",
        "ip_address",
        "country",
        "user_agent",
        "device_type",
        "browser",
        "operating_system",
        "referrer",
        "page_url",
        "path",
        "clicked_text",
        "clicked_url",
        "element_tag",
        "element_id",
        "element_classes",
        "event_type",
        "product_id",
        "category_id",
        "vendor_id",
        "landing_page_id",
        "session_key",
        "is_authenticated",
        "is_bot",
        "created_at",
    ]

    date_hierarchy = "created_at"
    ordering = ["-created_at"]
    list_per_page = 50

    def created_at_display(self, obj):
        return localtime(obj.created_at).strftime("%Y-%m-%d %H:%M:%S")

    created_at_display.short_description = "Date"

    def user_display(self, obj):
        if obj.user:
            return str(obj.user)
        return "-"

    user_display.short_description = "User"

    def clicked_text_display(self, obj):
        if not obj.clicked_text:
            return "-"
        return obj.clicked_text[:80]

    clicked_text_display.short_description = "Clicked Text"

    def clicked_url_display(self, obj):
        if not obj.clicked_url:
            return "-"
        return format_html('<a href="{}" target="_blank">{}</a>', obj.clicked_url, obj.clicked_url[:80])

    clicked_url_display.short_description = "Clicked URL"

    def page_display(self, obj):
        if not obj.page_url:
            return "-"
        return format_html('<a href="{}" target="_blank">{}</a>', obj.page_url, obj.path[:60] or "Page")

    page_display.short_description = "Page"