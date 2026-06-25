from django.contrib import admin
from django.utils import timezone

from .models import ContactMessage


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = [
        "subject",
        "name",
        "email",
        "vendor_short",
        "created_at",
        "is_read",
        "replied",
    ]
    list_filter = ["is_read", "replied", "created_at", "vendor"]
    search_fields = ["name", "email", "subject", "message", "vendor__store_name"]
    readonly_fields = ["created_at", "updated_at", "ip_address", "user_agent"]

    fieldsets = (
        ("Message Information", {
            "fields": ("name", "email", "subject", "message"),
        }),
        ("Vendor Information", {
            "fields": ("vendor",),
        }),
        ("User Information", {
            "fields": ("user", "ip_address", "user_agent"),
        }),
        ("Status", {
            "fields": ("is_read", "replied", "replied_at", "reply_message"),
        }),
        ("Metadata", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )

    actions = ["mark_as_read", "mark_as_unread", "mark_as_replied"]

    def vendor_short(self, obj):
        return obj.vendor.store_name if obj.vendor else "-"
    vendor_short.short_description = "Vendor"

    def mark_as_read(self, request, queryset):
        updated = queryset.update(is_read=True)
        self.message_user(request, f"{updated} message(s) marked as read.")
    mark_as_read.short_description = "Mark selected messages as read"

    def mark_as_unread(self, request, queryset):
        updated = queryset.update(is_read=False)
        self.message_user(request, f"{updated} message(s) marked as unread.")
    mark_as_unread.short_description = "Mark selected messages as unread"

    def mark_as_replied(self, request, queryset):
        updated = queryset.update(replied=True, replied_at=timezone.now())
        self.message_user(request, f"{updated} message(s) marked as replied.")
    mark_as_replied.short_description = "Mark selected messages as replied"

    def save_model(self, request, obj, form, change):
        if obj.replied and not obj.replied_at:
            obj.replied_at = timezone.now()
        super().save_model(request, obj, form, change)