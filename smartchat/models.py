from django.conf import settings
from django.db import models
from django.utils import timezone


class SmartChatConversation(models.Model):
    STATUS_AI = "ai"
    STATUS_ADMIN_REQUESTED = "admin_requested"
    STATUS_ADMIN_ACTIVE = "admin_active"
    STATUS_CLOSED = "closed"

    STATUS_CHOICES = [
        (STATUS_AI, "AI Active"),
        (STATUS_ADMIN_REQUESTED, "Admin Requested"),
        (STATUS_ADMIN_ACTIVE, "Admin Active"),
        (STATUS_CLOSED, "Closed"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="smart_chat_conversations",
    )
    session_key = models.CharField(max_length=80, blank=True, db_index=True)
    product = models.ForeignKey(
        "products.Product",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="smart_chat_conversations",
    )
    assigned_admin = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_smart_chat_conversations",
        limit_choices_to={"is_staff": True},
    )
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_AI, db_index=True)
    title = models.CharField(max_length=180, blank=True)
    customer_name = models.CharField(max_length=160, blank=True)
    customer_email = models.EmailField(blank=True)
    selected_variants = models.JSONField(default=dict, blank=True)
    page_url = models.URLField(blank=True)
    user_agent = models.TextField(blank=True)
    ai_summary = models.TextField(blank=True)
    admin_requested_at = models.DateTimeField(null=True, blank=True)
    last_message_at = models.DateTimeField(default=timezone.now, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-last_message_at"]
        indexes = [
            models.Index(fields=["status", "-last_message_at"]),
            models.Index(fields=["session_key", "-last_message_at"]),
        ]

    def __str__(self):
        product_name = self.product.name if self.product else "General chat"
        return f"#{self.id} - {product_name} - {self.get_status_display()}"

    @property
    def customer_display(self):
        if self.user:
            return self.user.get_full_name() or self.user.username or self.user.email
        return self.customer_name or self.customer_email or "Guest customer"

    @property
    def is_waiting_for_admin(self):
        return self.status == self.STATUS_ADMIN_REQUESTED

    def mark_admin_requested(self):
        if self.status != self.STATUS_ADMIN_ACTIVE:
            self.status = self.STATUS_ADMIN_REQUESTED
            self.admin_requested_at = timezone.now()
            self.save(update_fields=["status", "admin_requested_at", "updated_at"])

    def assign_admin(self, admin_user):
        self.assigned_admin = admin_user
        self.status = self.STATUS_ADMIN_ACTIVE
        self.save(update_fields=["assigned_admin", "status", "updated_at"])

    def touch(self):
        self.last_message_at = timezone.now()
        self.save(update_fields=["last_message_at", "updated_at"])


class SmartChatMessage(models.Model):
    SENDER_USER = "user"
    SENDER_AI = "ai"
    SENDER_ADMIN = "admin"
    SENDER_SYSTEM = "system"

    SENDER_CHOICES = [
        (SENDER_USER, "Customer"),
        (SENDER_AI, "AI Assistant"),
        (SENDER_ADMIN, "Admin"),
        (SENDER_SYSTEM, "System"),
    ]

    conversation = models.ForeignKey(
        SmartChatConversation,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    sender_type = models.CharField(max_length=20, choices=SENDER_CHOICES, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="smart_chat_messages",
    )
    message = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    is_private_note = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["conversation", "created_at"]),
            models.Index(fields=["sender_type", "created_at"]),
        ]

    def __str__(self):
        return f"{self.get_sender_type_display()} - {self.created_at:%Y-%m-%d %H:%M}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        SmartChatConversation.objects.filter(pk=self.conversation_id).update(
            last_message_at=self.created_at,
            updated_at=timezone.now(),
        )
