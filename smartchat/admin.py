from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from .models import SmartChatConversation, SmartChatMessage


class SmartChatMessageInline(admin.TabularInline):
    model = SmartChatMessage
    extra = 0
    readonly_fields = ["sender_type", "user", "message", "is_private_note", "created_at"]
    fields = ["sender_type", "user", "message", "is_private_note", "created_at"]
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(SmartChatConversation)
class SmartChatConversationAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "customer_display",
        "product_display",
        "status_badge",
        "assigned_admin",
        "last_message_at",
        "open_chat_link",
    ]
    list_filter = ["status", "created_at", "last_message_at"]
    search_fields = [
        "title",
        "customer_name",
        "customer_email",
        "user__username",
        "user__email",
        "product__name",
        "product__sku",
    ]
    readonly_fields = ["created_at", "updated_at", "last_message_at", "admin_requested_at", "open_chat_link"]
    list_select_related = ["user", "product", "assigned_admin"]
    inlines = [SmartChatMessageInline]
    actions = ["mark_admin_active", "mark_closed"]

    fieldsets = (
        ("Conversation", {"fields": ("status", "title", "product", "user", "session_key", "open_chat_link")}),
        ("Admin", {"fields": ("assigned_admin", "admin_requested_at")}),
        ("Customer", {"fields": ("customer_name", "customer_email", "selected_variants", "page_url", "user_agent")}),
        ("AI", {"fields": ("ai_summary",)}),
        ("Timestamps", {"fields": ("created_at", "updated_at", "last_message_at"), "classes": ("collapse",)}),
    )

    def product_display(self, obj):
        if obj.product:
            return f"{obj.product.name} ({obj.product.sku})"
        return "General"
    product_display.short_description = "Product"

    def status_badge(self, obj):
        colors = {
            "ai": "#2563eb",
            "admin_requested": "#f97316",
            "admin_active": "#059669",
            "closed": "#6b7280",
        }
        return format_html(
            '<span style="background:{};color:white;padding:4px 9px;border-radius:999px;font-size:11px;font-weight:700;">{}</span>',
            colors.get(obj.status, "#6b7280"),
            obj.get_status_display(),
        )
    status_badge.short_description = "Status"

    def open_chat_link(self, obj):
        if not obj or not obj.pk:
            return "Save first"
        url = reverse("smartchat:admin_conversation", args=[obj.id])
        return format_html(
            '<a class="button" style="background:#2563eb;color:#fff;padding:7px 12px;border-radius:6px;text-decoration:none;font-weight:700;" href="{}">Open chat</a>',
            url,
        )
    open_chat_link.short_description = "Admin Chat"

    def mark_admin_active(self, request, queryset):
        updated = 0
        for conversation in queryset:
            conversation.assign_admin(request.user)
            updated += 1
        self.message_user(request, f"{updated} conversation(s) assigned to you.")
    mark_admin_active.short_description = "Take over selected chats"

    def mark_closed(self, request, queryset):
        updated = queryset.update(status="closed")
        self.message_user(request, f"{updated} conversation(s) closed.")
    mark_closed.short_description = "Close selected chats"


@admin.register(SmartChatMessage)
class SmartChatMessageAdmin(admin.ModelAdmin):
    list_display = ["conversation", "sender_type", "user", "message_preview", "is_private_note", "created_at"]
    list_filter = ["sender_type", "is_private_note", "created_at"]
    search_fields = ["message", "conversation__title", "conversation__product__name"]
    list_select_related = ["conversation", "user"]
    readonly_fields = ["created_at"]

    def message_preview(self, obj):
        return obj.message[:90] + ("..." if len(obj.message) > 90 else "")
    message_preview.short_description = "Message"
