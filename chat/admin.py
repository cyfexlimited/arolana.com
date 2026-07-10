from django.contrib import admin

from .models import (
    ChatMessage,
    ChatNotification,
    ChatRoom,
    ChatTypingStatus,
    VendorChatMessage,
    VendorChatRoom,
)


# =============================================================================
# CHAT ROOM ADMIN
# =============================================================================


@admin.register(ChatRoom)
class ChatRoomAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "room_type",
        "name",
        "participant_count",
        "is_active",
        "updated_at",
    )

    list_filter = (
        "room_type",
        "is_active",
    )

    filter_horizontal = (
        "participants",
    )

    search_fields = (
        "name",
        "participants__username",
        "participants__email",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    list_select_related = (
        "product",
        "order",
    )

    ordering = (
        "-updated_at",
    )

    list_per_page = 100

    fieldsets = (
        (
            "Room",
            {
                "fields": (
                    "room_type",
                    "name",
                    "participants",
                    "is_active",
                ),
            },
        ),
        (
            "Related Commerce",
            {
                "fields": (
                    "product",
                    "order",
                ),
            },
        ),
        (
            "Dates",
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

    @admin.display(
        description="Participants"
    )
    def participant_count(
        self,
        obj,
    ):
        return obj.participants.count()


# =============================================================================
# CHAT MESSAGE ADMIN
# =============================================================================


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "sender",
        "message_preview",
        "attachment_status",
        "room",
        "is_read",
        "is_delivered",
        "is_edited",
        "is_deleted",
        "created_at",
    )

    list_filter = (
        "is_read",
        "is_delivered",
        "is_edited",
        "is_deleted",
        "attachment_type",
        "created_at",
    )

    search_fields = (
        "message",
        "sender__username",
        "sender__email",
        "room__name",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
        "read_at",
        "delivered_at",
    )

    list_select_related = (
        "room",
        "sender",
        "reply_to",
    )

    ordering = (
        "-created_at",
    )

    date_hierarchy = (
        "created_at"
    )

    list_per_page = 100

    fieldsets = (
        (
            "Message",
            {
                "fields": (
                    "room",
                    "sender",
                    "message",
                    "reply_to",
                ),
            },
        ),
        (
            "Attachment",
            {
                "fields": (
                    "attachment",
                    "attachment_type",
                ),
            },
        ),
        (
            "Delivery Status",
            {
                "fields": (
                    "is_delivered",
                    "delivered_at",
                    "is_read",
                    "read_at",
                ),
            },
        ),
        (
            "Moderation Status",
            {
                "fields": (
                    "is_edited",
                    "is_deleted",
                    "is_active",
                ),
            },
        ),
        (
            "Dates",
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

    def get_readonly_fields(
        self,
        request,
        obj=None,
    ):
        """
        Prevent an existing chat attachment from being silently replaced.

        New messages:
            attachment remains editable and uses the model validator.

        Existing messages:
            attachment becomes read-only.
        """

        readonly = list(
            super().get_readonly_fields(
                request,
                obj,
            )
        )

        if obj is not None:
            readonly.append(
                "attachment"
            )

        return tuple(
            readonly
        )

    @admin.display(
        description="Message"
    )
    def message_preview(
        self,
        obj,
    ):
        if not obj.message:
            if obj.attachment:
                return "[Attachment]"

            return "[Empty message]"

        if len(
            obj.message
        ) > 50:
            return (
                obj.message[:50]
                + "..."
            )

        return obj.message

    @admin.display(
        description="Attachment",
        boolean=True,
    )
    def attachment_status(
        self,
        obj,
    ):
        return bool(
            obj.attachment
        )


# =============================================================================
# CHAT NOTIFICATION ADMIN
# =============================================================================


@admin.register(ChatNotification)
class ChatNotificationAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "message",
        "is_read",
        "created_at",
    )

    list_filter = (
        "is_read",
        "created_at",
    )

    search_fields = (
        "user__username",
        "user__email",
        "message__message",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    list_select_related = (
        "user",
        "message",
    )

    ordering = (
        "-created_at",
    )

    date_hierarchy = (
        "created_at"
    )

    list_per_page = 100

    fieldsets = (
        (
            "Notification",
            {
                "fields": (
                    "user",
                    "message",
                    "is_read",
                ),
            },
        ),
        (
            "Dates",
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


# =============================================================================
# CHAT TYPING STATUS ADMIN
# =============================================================================


@admin.register(ChatTypingStatus)
class ChatTypingStatusAdmin(admin.ModelAdmin):
    list_display = (
        "room",
        "user",
        "is_typing",
        "last_typing_at",
    )

    list_filter = (
        "is_typing",
        "last_typing_at",
    )

    search_fields = (
        "user__username",
        "user__email",
        "room__name",
    )

    readonly_fields = (
        "last_typing_at",
        "created_at",
        "updated_at",
    )

    list_select_related = (
        "room",
        "user",
    )

    ordering = (
        "-last_typing_at",
    )

    list_per_page = 100

    fieldsets = (
        (
            "Typing Status",
            {
                "fields": (
                    "room",
                    "user",
                    "is_typing",
                ),
            },
        ),
        (
            "Dates",
            {
                "fields": (
                    "last_typing_at",
                    "created_at",
                    "updated_at",
                ),
                "classes": (
                    "collapse",
                ),
            },
        ),
    )


# =============================================================================
# VENDOR CHAT ROOM ADMIN
# =============================================================================


@admin.register(VendorChatRoom)
class VendorChatRoomAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "vendor",
        "customer",
        "product",
        "last_message_preview",
        "vendor_unread",
        "customer_unread",
        "is_active",
        "last_message_time",
    )

    list_filter = (
        "is_active",
        "last_message_time",
    )

    search_fields = (
        "vendor__username",
        "vendor__email",
        "customer__username",
        "customer__email",
        "product__name",
        "last_message",
    )

    readonly_fields = (
        "last_message_time",
        "created_at",
        "updated_at",
    )

    list_select_related = (
        "vendor",
        "customer",
        "product",
        "order",
    )

    ordering = (
        "-last_message_time",
    )

    date_hierarchy = (
        "last_message_time"
    )

    list_per_page = 100

    fieldsets = (
        (
            "Participants",
            {
                "fields": (
                    "vendor",
                    "customer",
                ),
            },
        ),
        (
            "Related Commerce",
            {
                "fields": (
                    "product",
                    "order",
                ),
            },
        ),
        (
            "Conversation State",
            {
                "fields": (
                    "last_message",
                    "vendor_unread",
                    "customer_unread",
                    "is_active",
                ),
            },
        ),
        (
            "Dates",
            {
                "fields": (
                    "last_message_time",
                    "created_at",
                    "updated_at",
                ),
                "classes": (
                    "collapse",
                ),
            },
        ),
    )

    @admin.display(
        description="Last Message"
    )
    def last_message_preview(
        self,
        obj,
    ):
        return (
            obj.get_last_message_preview()
        )


# =============================================================================
# VENDOR CHAT MESSAGE ADMIN
# =============================================================================


@admin.register(VendorChatMessage)
class VendorChatMessageAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "sender",
        "room",
        "message_preview",
        "attachment_status",
        "is_read",
        "created_at",
    )

    list_filter = (
        "is_read",
        "created_at",
    )

    search_fields = (
        "message",
        "sender__username",
        "sender__email",
        "room__vendor__username",
        "room__customer__username",
    )

    readonly_fields = (
        "created_at",
        "read_at",
        "updated_at",
    )

    list_select_related = (
        "room",
        "sender",
        "room__vendor",
        "room__customer",
    )

    ordering = (
        "-created_at",
    )

    date_hierarchy = (
        "created_at"
    )

    list_per_page = 100

    fieldsets = (
        (
            "Message",
            {
                "fields": (
                    "room",
                    "sender",
                    "message",
                ),
            },
        ),
        (
            "Attachment",
            {
                "fields": (
                    "attachment",
                ),
            },
        ),
        (
            "Read Status",
            {
                "fields": (
                    "is_read",
                    "read_at",
                ),
            },
        ),
        (
            "Status",
            {
                "fields": (
                    "is_active",
                ),
            },
        ),
        (
            "Dates",
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

    def get_readonly_fields(
        self,
        request,
        obj=None,
    ):
        """
        Existing vendor-chat evidence attachments cannot be replaced
        through Django Admin.
        """

        readonly = list(
            super().get_readonly_fields(
                request,
                obj,
            )
        )

        if obj is not None:
            readonly.append(
                "attachment"
            )

        return tuple(
            readonly
        )

    @admin.display(
        description="Message"
    )
    def message_preview(
        self,
        obj,
    ):
        if not obj.message:
            if obj.attachment:
                return "[Attachment]"

            return "[Empty message]"

        if len(
            obj.message
        ) > 50:
            return (
                obj.message[:50]
                + "..."
            )

        return obj.message

    @admin.display(
        description="Attachment",
        boolean=True,
    )
    def attachment_status(
        self,
        obj,
    ):
        return bool(
            obj.attachment
        )