import csv

from django.contrib import admin
from django.http import HttpResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from .models import (
    AIConversation,
    AICustomerMemory,
    AIFeedback,
    AIKnowledgeBase,
    AILearnedKnowledge,
    AIMessage,
    AISettings,
    AITrainingData,
    HumanTakeoverRequest,
    SmartChatConversation,
    SmartChatMessage,
    SmartChatSupportTicket,
)


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


@admin.register(SmartChatSupportTicket)
class SmartChatSupportTicketAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "title",
        "audience",
        "intent",
        "priority",
        "status",
        "created_by",
        "assigned_admin",
        "created_at",
    ]
    list_filter = [
        "status",
        "priority",
        "audience",
        "intent",
        "created_at",
    ]
    search_fields = [
        "title",
        "description",
        "conversation__customer_name",
        "conversation__customer_email",
        "created_by__email",
        "created_by__username",
        "order__order_number",
        "product__name",
    ]
    list_select_related = [
        "conversation",
        "created_by",
        "assigned_admin",
        "order",
        "product",
        "vendor_profile",
        "rider_profile",
    ]
    readonly_fields = [
        "created_at",
        "updated_at",
        "resolved_at",
        "metadata",
    ]
    actions = [
        "assign_to_me",
        "mark_in_progress",
        "mark_resolved",
        "mark_closed",
    ]

    def assign_to_me(self, request, queryset):
        updated = queryset.update(assigned_admin=request.user, status=SmartChatSupportTicket.STATUS_IN_PROGRESS)
        self.message_user(request, f"{updated} ticket(s) assigned to you.")

    assign_to_me.short_description = "Assign selected tickets to me"

    def mark_in_progress(self, request, queryset):
        updated = queryset.update(status=SmartChatSupportTicket.STATUS_IN_PROGRESS)
        self.message_user(request, f"{updated} ticket(s) marked in progress.")

    mark_in_progress.short_description = "Mark selected tickets in progress"

    def mark_resolved(self, request, queryset):
        for ticket in queryset:
            ticket.mark_resolved()
        self.message_user(request, f"{queryset.count()} ticket(s) resolved.")

    mark_resolved.short_description = "Mark selected tickets resolved"

    def mark_closed(self, request, queryset):
        updated = queryset.update(status=SmartChatSupportTicket.STATUS_CLOSED)
        self.message_user(request, f"{updated} ticket(s) closed.")

    mark_closed.short_description = "Close selected tickets"


@admin.register(AIConversation)
class AIConversationAdmin(admin.ModelAdmin):
    list_display = ["id", "customer_display", "status", "channel", "assigned_admin", "last_message_at"]
    list_filter = ["status", "channel", "audience", "assigned_admin"]
    search_fields = ["title", "customer_name", "customer_email", "customer_phone", "messages__message"]
    actions = ["mark_resolved", "assign_to_staff", "convert_answer_to_knowledge", "export_csv"]

    @admin.action(description="Mark conversation resolved")
    def mark_resolved(self, request, queryset):
        queryset.update(status=SmartChatConversation.STATUS_CLOSED, resolved_at=timezone.now())

    @admin.action(description="Assign selected conversations to me")
    def assign_to_staff(self, request, queryset):
        queryset.update(assigned_admin=request.user, status=SmartChatConversation.STATUS_ADMIN_ACTIVE)
        HumanTakeoverRequest.objects.filter(
            conversation__in=queryset,
            status=HumanTakeoverRequest.STATUS_PENDING,
        ).update(
            status=HumanTakeoverRequest.STATUS_ASSIGNED,
            assigned_to=request.user,
            assigned_at=timezone.now(),
        )

    @admin.action(description="Convert latest answer to knowledge base")
    def convert_answer_to_knowledge(self, request, queryset):
        created = 0
        for conversation in queryset:
            answer = conversation.messages.filter(
                sender_type__in=[SmartChatMessage.SENDER_AI, SmartChatMessage.SENDER_ADMIN],
                is_private_note=False,
            ).order_by("-id").first()
            if not answer:
                continue
            question = conversation.messages.filter(
                sender_type=SmartChatMessage.SENDER_USER,
                id__lt=answer.id,
            ).order_by("-id").first()
            if not question:
                continue
            _, was_created = AIKnowledgeBase.objects.get_or_create(
                question=question.message[:500],
                defaults={
                    "answer": answer.message,
                    "created_by": request.user,
                    "approved": False,
                },
            )
            created += int(was_created)
        self.message_user(request, f"{created} knowledge item(s) created for review.")

    @admin.action(description="Export conversations CSV")
    def export_csv(self, request, queryset):
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="smartchat-conversations.csv"'
        writer = csv.writer(response)
        writer.writerow(["ID", "Customer", "Email", "Phone", "Status", "Channel", "Created", "Last message"])
        for item in queryset:
            writer.writerow([
                item.id, item.customer_display, item.customer_email, item.customer_phone,
                item.status, item.channel, item.created_at.isoformat(), item.last_message_at.isoformat(),
            ])
        return response


@admin.register(AIMessage)
class AIMessageAdmin(admin.ModelAdmin):
    list_display = ["id", "conversation", "sender_type", "source_type", "confidence", "created_at"]
    list_filter = ["sender_type", "source_type", "is_read_by_customer", "is_read_by_admin"]
    search_fields = ["message", "source_label", "conversation__customer_email"]
    readonly_fields = ["created_at"]


@admin.register(AIKnowledgeBase)
class AIKnowledgeBaseAdmin(admin.ModelAdmin):
    list_display = ["question", "category", "audience", "approved", "is_active", "priority", "usage_count"]
    list_filter = ["approved", "is_active", "audience", "category"]
    search_fields = ["question", "answer", "keywords"]
    list_editable = ["approved", "is_active", "priority"]


@admin.register(AILearnedKnowledge)
class AILearnedKnowledgeAdmin(admin.ModelAdmin):
    list_display = ["normalized_question", "occurrence_count", "confidence", "privacy_safe", "approved", "rejected", "is_active"]
    list_filter = ["approved", "rejected", "privacy_safe", "is_active"]
    search_fields = ["normalized_question", "proposed_answer", "keywords"]
    actions = ["approve_learning", "reject_learning"]

    @admin.action(description="Approve learned knowledge")
    def approve_learning(self, request, queryset):
        queryset.update(
            approved=True, rejected=False, is_active=True, privacy_safe=True,
            reviewed_by=request.user, approved_at=timezone.now(),
        )

    @admin.action(description="Reject learned knowledge")
    def reject_learning(self, request, queryset):
        queryset.update(
            approved=False, rejected=True, is_active=False, reviewed_by=request.user,
        )


@admin.register(AICustomerMemory)
class AICustomerMemoryAdmin(admin.ModelAdmin):
    list_display = ["memory_key", "user", "category", "is_active", "confidence", "updated_at"]
    list_filter = ["is_active", "category"]
    search_fields = ["memory_key", "memory_value", "user__email", "session_key", "device_id"]
    list_editable = ["is_active"]


@admin.register(AIFeedback)
class AIFeedbackAdmin(admin.ModelAdmin):
    list_display = ["conversation", "rating", "helpful", "is_reviewed", "created_at"]
    list_filter = ["rating", "helpful", "is_reviewed"]
    search_fields = ["comment", "conversation__customer_email"]
    list_editable = ["is_reviewed"]


@admin.register(AITrainingData)
class AITrainingDataAdmin(admin.ModelAdmin):
    list_display = ["question", "category", "audience", "approved", "is_active", "priority"]
    list_filter = ["approved", "is_active", "audience", "category"]
    search_fields = ["question", "answer", "keywords"]
    list_editable = ["approved", "is_active", "priority"]


@admin.register(AISettings)
class AISettingsAdmin(admin.ModelAdmin):
    list_display = ["__str__", "enabled", "model_name", "memory_enabled", "learning_enabled", "updated_at"]

    def has_add_permission(self, request):
        return not AISettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(HumanTakeoverRequest)
class HumanTakeoverRequestAdmin(admin.ModelAdmin):
    list_display = ["conversation", "status", "priority", "assigned_to", "requested_at", "resolved_at"]
    list_filter = ["status", "priority", "assigned_to"]
    search_fields = ["reason", "conversation__customer_email", "conversation__customer_phone"]
    actions = ["assign_to_me", "mark_resolved"]

    @admin.action(description="Assign selected requests to me")
    def assign_to_me(self, request, queryset):
        queryset.update(
            status=HumanTakeoverRequest.STATUS_ASSIGNED,
            assigned_to=request.user,
            assigned_at=timezone.now(),
        )

    @admin.action(description="Mark selected requests resolved")
    def mark_resolved(self, request, queryset):
        queryset.update(status=HumanTakeoverRequest.STATUS_RESOLVED, resolved_at=timezone.now())
