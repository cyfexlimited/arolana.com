from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from .models import SmartChatConversation, SmartChatMessage


class SmartChatMessageInline(admin.TabularInline):
    model = SmartChatMessage
    extra = 0
    can_delete = False

    fields = [
        "sender_type",
        "user",
        "message",
        "is_private_note",
        "created_at",
    ]

    readonly_fields = [
        "sender_type",
        "user",
        "message",
        "is_private_note",
        "created_at",
    ]

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(SmartChatConversation)
class SmartChatConversationAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "customer_display_admin",
        "customer_email_display",
        "product_display",
        "status_badge",
        "assigned_admin",
        "message_count",
        "last_message_at",
        "open_chat_link",
    ]

    list_filter = [
        "status",
        "assigned_admin",
        "created_at",
        "last_message_at",
    ]

    search_fields = [
        "title",
        "customer_name",
        "customer_email",
        "user__username",
        "user__email",
        "product__name",
        "product__sku",
        "page_url",
    ]

    list_select_related = [
        "user",
        "product",
        "assigned_admin",
    ]

    readonly_fields = [
        "open_chat_link",
        "created_at",
        "updated_at",
        "last_message_at",
        "admin_requested_at",
        "customer_preview",
        "product_preview",
        "page_url_link",
    ]

    inlines = [
        SmartChatMessageInline,
    ]

    actions = [
        "take_over_chats",
        "mark_admin_requested",
        "mark_ai_active",
        "mark_closed",
    ]

    ordering = [
        "-last_message_at",
    ]

    list_per_page = 30

    def get_fieldsets(self, request, obj=None):
        """
        Dynamic fieldsets so admin will not break if some newer fields
        like customer_first_name/customer_last_name/customer_phone
        do not exist yet.
        """
        model_fields = {field.name for field in SmartChatConversation._meta.fields}

        customer_fields = []

        if "customer_first_name" in model_fields:
            customer_fields.append("customer_first_name")

        if "customer_last_name" in model_fields:
            customer_fields.append("customer_last_name")

        if "customer_name" in model_fields:
            customer_fields.append("customer_name")

        if "customer_email" in model_fields:
            customer_fields.append("customer_email")

        if "customer_phone" in model_fields:
            customer_fields.append("customer_phone")

        fieldsets = [
            (
                "Conversation",
                {
                    "fields": (
                        "status",
                        "title",
                        "product",
                        "user",
                        "session_key",
                        "open_chat_link",
                    )
                },
            ),
            (
                "Admin",
                {
                    "fields": (
                        "assigned_admin",
                        "admin_requested_at",
                    )
                },
            ),
            (
                "Customer / Visitor Details",
                {
                    "fields": tuple(customer_fields) + (
                        "customer_preview",
                    )
                },
            ),
            (
                "Context",
                {
                    "fields": (
                        "selected_variants",
                        "page_url",
                        "page_url_link",
                        "user_agent",
                        "product_preview",
                    )
                },
            ),
            (
                "AI",
                {
                    "fields": (
                        "ai_summary",
                    )
                },
            ),
            (
                "Timestamps",
                {
                    "fields": (
                        "created_at",
                        "updated_at",
                        "last_message_at",
                    ),
                    "classes": (
                        "collapse",
                    ),
                },
            ),
        ]

        return fieldsets

    def customer_display_admin(self, obj):
        return obj.customer_display

    customer_display_admin.short_description = "Customer"

    def customer_email_display(self, obj):
        if obj.customer_email:
            return format_html(
                '<a href="mailto:{}">{}</a>',
                obj.customer_email,
                obj.customer_email,
            )

        if obj.user and obj.user.email:
            return format_html(
                '<a href="mailto:{}">{}</a>',
                obj.user.email,
                obj.user.email,
            )

        return "—"

    customer_email_display.short_description = "Email"

    def product_display(self, obj):
        if obj.product:
            return format_html(
                '<strong>{}</strong><br><small style="color:#6b7280;">SKU: {}</small>',
                obj.product.name,
                obj.product.sku,
            )

        return "General Support"

    product_display.short_description = "Product"

    def product_preview(self, obj):
        if not obj or not obj.product:
            return "No product attached"

        try:
            product_url = obj.product.get_absolute_url()
        except Exception:
            product_url = "#"

        image_html = ""

        if getattr(obj.product, "main_image", None):
            try:
                image_html = (
                    f'<img src="{obj.product.main_image.url}" '
                    f'style="width:80px;height:80px;object-fit:cover;'
                    f'border-radius:10px;margin-right:12px;" />'
                )
            except Exception:
                image_html = ""

        return format_html(
            '<div style="display:flex;align-items:center;">'
            '{}'
            '<div>'
            '<strong>{}</strong><br>'
            '<small>SKU: {}</small><br>'
            '<a href="{}" target="_blank">View product</a>'
            '</div>'
            '</div>',
            format_html(image_html),
            obj.product.name,
            obj.product.sku,
            product_url,
        )

    product_preview.short_description = "Product Preview"

    def status_badge(self, obj):
        colors = {
            SmartChatConversation.STATUS_AI: "#2563eb",
            SmartChatConversation.STATUS_ADMIN_REQUESTED: "#f97316",
            SmartChatConversation.STATUS_ADMIN_ACTIVE: "#059669",
            SmartChatConversation.STATUS_CLOSED: "#6b7280",
        }

        labels = {
            SmartChatConversation.STATUS_AI: "AI Active",
            SmartChatConversation.STATUS_ADMIN_REQUESTED: "Needs Admin",
            SmartChatConversation.STATUS_ADMIN_ACTIVE: "Admin Active",
            SmartChatConversation.STATUS_CLOSED: "Closed",
        }

        return format_html(
            '<span style="background:{};color:white;padding:5px 10px;'
            'border-radius:999px;font-size:11px;font-weight:800;">{}</span>',
            colors.get(obj.status, "#6b7280"),
            labels.get(obj.status, obj.get_status_display()),
        )

    status_badge.short_description = "Status"

    def open_chat_link(self, obj):
        if not obj or not obj.pk:
            return "Save first"

        url = reverse(
            "smartchat:admin_conversation",
            args=[
                obj.id,
            ],
        )

        return format_html(
            '<a class="button" '
            'style="background:#2563eb;color:#fff;padding:8px 13px;'
            'border-radius:8px;text-decoration:none;font-weight:800;" '
            'href="{}">Open chat</a>',
            url,
        )

    open_chat_link.short_description = "Admin Chat"

    def customer_preview(self, obj):
        if not obj:
            return "No customer yet"

        name = obj.customer_display
        email = obj.customer_email or getattr(obj.user, "email", "") or "No email"

        return format_html(
            '<div style="background:#f8fafc;border:1px solid #e5e7eb;'
            'padding:12px;border-radius:12px;">'
            '<strong>{}</strong><br>'
            '<small style="color:#475569;">{}</small>'
            '</div>',
            name,
            email,
        )

    customer_preview.short_description = "Customer Preview"

    def page_url_link(self, obj):
        if not obj or not obj.page_url:
            return "No page URL"

        return format_html(
            '<a href="{}" target="_blank">{}</a>',
            obj.page_url,
            obj.page_url[:80],
        )

    page_url_link.short_description = "Page URL"

    def message_count(self, obj):
        return obj.messages.count()

    message_count.short_description = "Messages"

    def take_over_chats(self, request, queryset):
        updated = 0

        for conversation in queryset:
            conversation.assign_admin(request.user)
            updated += 1

        self.message_user(
            request,
            f"{updated} conversation(s) assigned to you.",
        )

    take_over_chats.short_description = "Take over selected chats"

    def mark_admin_requested(self, request, queryset):
        updated = 0

        for conversation in queryset:
            conversation.mark_admin_requested()
            updated += 1

        self.message_user(
            request,
            f"{updated} conversation(s) marked as admin requested.",
        )

    mark_admin_requested.short_description = "Mark as admin requested"

    def mark_ai_active(self, request, queryset):
        updated = queryset.update(
            status=SmartChatConversation.STATUS_AI,
        )

        self.message_user(
            request,
            f"{updated} conversation(s) returned to AI mode.",
        )

    mark_ai_active.short_description = "Return to AI mode"

    def mark_closed(self, request, queryset):
        updated = queryset.update(
            status=SmartChatConversation.STATUS_CLOSED,
        )

        self.message_user(
            request,
            f"{updated} conversation(s) closed.",
        )

    mark_closed.short_description = "Close selected chats"


@admin.register(SmartChatMessage)
class SmartChatMessageAdmin(admin.ModelAdmin):
    list_display = [
        "conversation",
        "sender_badge",
        "user",
        "message_preview",
        "is_private_note",
        "created_at",
    ]

    list_filter = [
        "sender_type",
        "is_private_note",
        "created_at",
    ]

    search_fields = [
        "message",
        "conversation__title",
        "conversation__customer_name",
        "conversation__customer_email",
        "conversation__product__name",
        "conversation__product__sku",
    ]

    list_select_related = [
        "conversation",
        "user",
        "conversation__product",
    ]

    readonly_fields = [
        "created_at",
    ]

    list_per_page = 50

    def sender_badge(self, obj):
        colors = {
            SmartChatMessage.SENDER_USER: "#2563eb",
            SmartChatMessage.SENDER_AI: "#7c3aed",
            SmartChatMessage.SENDER_ADMIN: "#059669",
            SmartChatMessage.SENDER_SYSTEM: "#6b7280",
        }

        return format_html(
            '<span style="background:{};color:white;padding:4px 9px;'
            'border-radius:999px;font-size:11px;font-weight:800;">{}</span>',
            colors.get(obj.sender_type, "#6b7280"),
            obj.get_sender_type_display(),
        )

    sender_badge.short_description = "Sender"

    def message_preview(self, obj):
        preview = obj.message[:100]

        if len(obj.message) > 100:
            preview += "..."

        return preview

    message_preview.short_description = "Message"