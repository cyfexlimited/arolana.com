from django.contrib.auth import get_user_model
from django.db import models

from core.models import BaseModel
from core.private_upload_validation import (
    validate_chat_attachment_upload,
)
from orders.models import Order
from products.models import Product


User = get_user_model()


# =============================================================================
# CHAT ROOM
# =============================================================================


class ChatRoom(BaseModel):
    """
    General chat room between Arolana users.
    """

    ROOM_TYPE_DIRECT = "direct"
    ROOM_TYPE_VENDOR_CUSTOMER = "vendor_customer"
    ROOM_TYPE_SUPPORT = "support"
    ROOM_TYPE_GROUP = "group"

    ROOM_TYPES = [
        (
            ROOM_TYPE_DIRECT,
            "Direct Message",
        ),
        (
            ROOM_TYPE_VENDOR_CUSTOMER,
            "Vendor-Customer",
        ),
        (
            ROOM_TYPE_SUPPORT,
            "Support Chat",
        ),
        (
            ROOM_TYPE_GROUP,
            "Group Chat",
        ),
    ]

    room_type = models.CharField(
        max_length=20,
        choices=ROOM_TYPES,
        default=ROOM_TYPE_DIRECT,
    )

    name = models.CharField(
        max_length=255,
        blank=True,
        help_text=(
            "Room name for group chats."
        ),
    )

    participants = models.ManyToManyField(
        User,
        related_name="chat_rooms",
    )

    product = models.ForeignKey(
        Product,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="chat_rooms",
    )

    order = models.ForeignKey(
        Order,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="chat_rooms",
    )

    is_active = models.BooleanField(
        default=True,
    )

    class Meta:
        ordering = [
            "-updated_at",
        ]

    def __str__(self):
        if self.name:
            return self.name

        return (
            f"Chat {self.id} "
            f"- {self.room_type}"
        )

    def get_last_message(self):
        return (
            self.messages
            .filter(
                is_active=True
            )
            .order_by(
                "-created_at"
            )
            .first()
        )

    def get_unread_count(
        self,
        user,
    ):
        return (
            self.messages
            .filter(
                is_active=True,
                is_read=False,
            )
            .exclude(
                sender=user
            )
            .count()
        )


# =============================================================================
# CHAT MESSAGE
# =============================================================================


class ChatMessage(BaseModel):
    """
    Individual message belonging to a general chat room.

    A message may contain:
    - text only;
    - attachment only;
    - text and attachment.
    """

    ATTACHMENT_IMAGE = "image"
    ATTACHMENT_FILE = "file"
    ATTACHMENT_VIDEO = "video"
    ATTACHMENT_AUDIO = "audio"

    ATTACHMENT_TYPE_CHOICES = [
        (
            ATTACHMENT_IMAGE,
            "Image",
        ),
        (
            ATTACHMENT_FILE,
            "File",
        ),
        (
            ATTACHMENT_VIDEO,
            "Video",
        ),
        (
            ATTACHMENT_AUDIO,
            "Audio",
        ),
    ]

    room = models.ForeignKey(
        ChatRoom,
        on_delete=models.CASCADE,
        related_name="messages",
    )

    sender = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="sent_messages",
    )

    message = models.TextField(
        blank=True,
    )

    attachment = models.FileField(
        upload_to=(
            "chat/attachments/%Y/%m/"
        ),
        null=True,
        blank=True,
        validators=[
            validate_chat_attachment_upload,
        ],
    )

    attachment_type = models.CharField(
        max_length=50,
        blank=True,
        choices=ATTACHMENT_TYPE_CHOICES,
    )

    is_read = models.BooleanField(
        default=False,
    )

    read_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    is_delivered = models.BooleanField(
        default=False,
    )

    delivered_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    is_edited = models.BooleanField(
        default=False,
    )

    is_deleted = models.BooleanField(
        default=False,
    )

    reply_to = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="replies",
    )

    class Meta:
        ordering = [
            "created_at",
        ]

    def __str__(self):
        preview = (
            self.message[:50]
            if self.message
            else "Attachment"
        )

        return (
            f"{self.sender.username}: "
            f"{preview}"
        )


# =============================================================================
# CHAT NOTIFICATION
# =============================================================================


class ChatNotification(BaseModel):
    """
    Push and in-app notification record for chat messages.
    """

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="chat_notifications",
    )

    message = models.ForeignKey(
        ChatMessage,
        on_delete=models.CASCADE,
        related_name="notifications",
    )

    is_read = models.BooleanField(
        default=False,
    )

    class Meta:
        ordering = [
            "-created_at",
        ]

    def __str__(self):
        return (
            "Notification for "
            f"{self.user.username}"
        )


# =============================================================================
# CHAT TYPING STATUS
# =============================================================================


class ChatTypingStatus(BaseModel):
    """
    Tracks typing state for users in a general chat room.
    """

    room = models.ForeignKey(
        ChatRoom,
        on_delete=models.CASCADE,
        related_name="typing_status",
    )

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="typing_status",
    )

    is_typing = models.BooleanField(
        default=False,
    )

    last_typing_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        unique_together = [
            "room",
            "user",
        ]

    def __str__(self):
        return (
            f"{self.user.username} "
            f"typing in room {self.room.id}"
        )


# =============================================================================
# VENDOR CHAT ROOM
# =============================================================================


class VendorChatRoom(BaseModel):
    """
    Dedicated vendor-to-customer chat room.
    """

    vendor = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="vendor_chats",
    )

    customer = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="customer_chats",
    )

    product = models.ForeignKey(
        Product,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    order = models.ForeignKey(
        Order,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    last_message = models.TextField(
        blank=True,
    )

    last_message_time = models.DateTimeField(
        auto_now=True,
    )

    customer_unread = models.IntegerField(
        default=0,
    )

    vendor_unread = models.IntegerField(
        default=0,
    )

    is_active = models.BooleanField(
        default=True,
    )

    class Meta:
        unique_together = [
            "vendor",
            "customer",
            "product",
        ]

        ordering = [
            "-last_message_time",
        ]

    def __str__(self):
        return (
            "Chat between "
            f"{self.vendor.username} "
            "and "
            f"{self.customer.username}"
        )

    def get_last_message_preview(self):
        if len(
            self.last_message
        ) > 50:
            return (
                self.last_message[:50]
                + "..."
            )

        return self.last_message

    def mark_read(
        self,
        user,
    ):
        """
        Mark the relevant participant's unread counter as zero.
        """

        if user == self.vendor:
            self.vendor_unread = 0

            self.save(
                update_fields=[
                    "vendor_unread",
                    "updated_at",
                ]
            )

        elif user == self.customer:
            self.customer_unread = 0

            self.save(
                update_fields=[
                    "customer_unread",
                    "updated_at",
                ]
            )


# =============================================================================
# VENDOR CHAT MESSAGE
# =============================================================================


class VendorChatMessage(BaseModel):
    """
    Individual message in a vendor-customer chat room.

    Supports:
    - text only;
    - attachment only;
    - text and attachment.
    """

    room = models.ForeignKey(
        VendorChatRoom,
        on_delete=models.CASCADE,
        related_name="messages",
    )

    sender = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="vendor_messages_sent",
    )

    message = models.TextField(
        blank=True,
    )

    is_read = models.BooleanField(
        default=False,
    )

    read_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    attachment = models.FileField(
        upload_to=(
            "chat/vendor_attachments/%Y/%m/"
        ),
        null=True,
        blank=True,
        validators=[
            validate_chat_attachment_upload,
        ],
    )

    class Meta:
        ordering = [
            "created_at",
        ]

    def __str__(self):
        preview = (
            self.message[:50]
            if self.message
            else "Attachment"
        )

        return (
            f"{self.sender.username}: "
            f"{preview}"
        )