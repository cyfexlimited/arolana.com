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

    AUDIENCE_CUSTOMER = "customer"
    AUDIENCE_VENDOR = "vendor"
    AUDIENCE_RIDER = "rider"
    AUDIENCE_ADMIN = "admin"
    AUDIENCE_GUEST = "guest"

    AUDIENCE_CHOICES = [
        (AUDIENCE_CUSTOMER, "Customer"),
        (AUDIENCE_VENDOR, "Vendor"),
        (AUDIENCE_RIDER, "Rider"),
        (AUDIENCE_ADMIN, "Admin"),
        (AUDIENCE_GUEST, "Guest"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="smart_chat_conversations",
    )

    session_key = models.CharField(
        max_length=120,
        blank=True,
        db_index=True,
        help_text="Visitor session key for guests.",
    )

    product = models.ForeignKey(
        "products.Product",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="smart_chat_conversations",
    )

    order = models.ForeignKey(
        "orders.Order",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="smart_chat_conversations",
    )

    vendor_profile = models.ForeignKey(
        "vendors.VendorProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="smart_chat_conversations",
    )

    rider_profile = models.ForeignKey(
        "deliveries.RiderProfile",
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

    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default=STATUS_AI,
        db_index=True,
    )

    audience = models.CharField(
        max_length=30,
        choices=AUDIENCE_CHOICES,
        default=AUDIENCE_CUSTOMER,
        db_index=True,
    )

    current_intent = models.CharField(max_length=80, blank=True, db_index=True)
    urgency = models.CharField(max_length=30, default="normal", blank=True, db_index=True)
    context = models.JSONField(default=dict, blank=True)

    # Visitor / customer captured details
    customer_first_name = models.CharField(max_length=100, blank=True)
    customer_last_name = models.CharField(max_length=100, blank=True)
    customer_name = models.CharField(max_length=200, blank=True)
    customer_email = models.EmailField(blank=True)
    customer_phone = models.CharField(max_length=40, blank=True)

    title = models.CharField(max_length=220, blank=True)
    selected_variants = models.JSONField(default=dict, blank=True)

    page_url = models.URLField(max_length=700, blank=True)
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
            models.Index(fields=["audience", "status", "-last_message_at"]),
            models.Index(fields=["current_intent", "-last_message_at"]),
            models.Index(fields=["session_key", "-last_message_at"]),
            models.Index(fields=["customer_email"]),
            models.Index(fields=["created_at"]),
        ]
        verbose_name = "Smart Chat Conversation"
        verbose_name_plural = "Smart Chat Conversations"

    def __str__(self):
        product_name = self.product.name if self.product else "General chat"
        return f"#{self.id} - {product_name} - {self.get_status_display()}"

    @property
    def full_customer_name(self):
        name = f"{self.customer_first_name} {self.customer_last_name}".strip()
        return name or self.customer_name

    @property
    def customer_display(self):
        if self.user:
            return self.user.get_full_name() or self.user.username or self.user.email

        return (
            self.full_customer_name
            or self.customer_email
            or "Guest customer"
        )

    @property
    def customer_avatar_url(self):
        """
        Best-effort avatar for admin Smart Chat views.
        Mobile customers store their app profile image separately, while web
        customers may have an account avatar or profile avatar.
        """
        try:
            mobile_customer_id = (self.selected_variants or {}).get("mobile_customer_id")
            if mobile_customer_id:
                from mobile_customers.models import MobileCustomer

                mobile_customer = MobileCustomer.objects.filter(id=mobile_customer_id).first()
                if mobile_customer and mobile_customer.profile_image:
                    return mobile_customer.profile_image.url
        except Exception:
            pass

        try:
            if self.user and getattr(self.user, "avatar", None):
                return self.user.avatar.url
        except Exception:
            pass

        try:
            if self.user and getattr(self.user, "profile", None) and self.user.profile.avatar:
                return self.user.profile.avatar.url
        except Exception:
            pass

        return ""

    @property
    def is_guest(self):
        return self.user_id is None

    @property
    def is_waiting_for_admin(self):
        return self.status == self.STATUS_ADMIN_REQUESTED

    @property
    def is_admin_active(self):
        return self.status == self.STATUS_ADMIN_ACTIVE

    @property
    def is_closed(self):
        return self.status == self.STATUS_CLOSED

    @property
    def unread_for_admin_count(self):
        return self.messages.filter(
            sender_type=SmartChatMessage.SENDER_USER,
            is_private_note=False,
        ).count()

    def mark_admin_requested(self):
        if self.status != self.STATUS_ADMIN_ACTIVE:
            self.status = self.STATUS_ADMIN_REQUESTED
            self.admin_requested_at = timezone.now()
            self.save(
                update_fields=[
                    "status",
                    "admin_requested_at",
                    "updated_at",
                ]
            )

    def assign_admin(self, admin_user):
        self.assigned_admin = admin_user
        self.status = self.STATUS_ADMIN_ACTIVE
        self.save(
            update_fields=[
                "assigned_admin",
                "status",
                "updated_at",
            ]
        )

    def close(self):
        self.status = self.STATUS_CLOSED
        self.save(update_fields=["status", "updated_at"])

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
        (SENDER_AI, "Arolana Chat"),
        (SENDER_ADMIN, "Admin"),
        (SENDER_SYSTEM, "System"),
    ]

    conversation = models.ForeignKey(
        SmartChatConversation,
        on_delete=models.CASCADE,
        related_name="messages",
    )

    sender_type = models.CharField(
        max_length=20,
        choices=SENDER_CHOICES,
        db_index=True,
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="smart_chat_messages",
    )

    message = models.TextField()
    image = models.ImageField(
        upload_to="smartchat/images/%Y/%m/",
        null=True,
        blank=True,
        help_text="Optional customer/admin image attachment.",
    )
    metadata = models.JSONField(default=dict, blank=True)

    is_private_note = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["conversation", "created_at"]),
            models.Index(fields=["conversation", "id"]),
            models.Index(fields=["sender_type", "created_at"]),
        ]
        verbose_name = "Smart Chat Message"
        verbose_name_plural = "Smart Chat Messages"

    def __str__(self):
        return f"{self.get_sender_type_display()} - {self.created_at:%Y-%m-%d %H:%M}"

    @property
    def sender_display(self):
        if self.sender_type == self.SENDER_USER:
            return "Customer"

        if self.sender_type == self.SENDER_AI:
            return "Arolana Chat"

        if self.sender_type == self.SENDER_ADMIN:
            if self.user:
                return self.user.get_full_name() or self.user.username or "Arolana Admin"
            return "Arolana Admin"

        return "System"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

        SmartChatConversation.objects.filter(
            pk=self.conversation_id
        ).update(
            last_message_at=self.created_at,
            updated_at=timezone.now(),
        )


class SmartChatSupportTicket(models.Model):
    STATUS_OPEN = "open"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_WAITING_CUSTOMER = "waiting_customer"
    STATUS_RESOLVED = "resolved"
    STATUS_CLOSED = "closed"

    STATUS_CHOICES = [
        (STATUS_OPEN, "Open"),
        (STATUS_IN_PROGRESS, "In Progress"),
        (STATUS_WAITING_CUSTOMER, "Waiting Customer"),
        (STATUS_RESOLVED, "Resolved"),
        (STATUS_CLOSED, "Closed"),
    ]

    PRIORITY_LOW = "low"
    PRIORITY_NORMAL = "normal"
    PRIORITY_HIGH = "high"
    PRIORITY_URGENT = "urgent"

    PRIORITY_CHOICES = [
        (PRIORITY_LOW, "Low"),
        (PRIORITY_NORMAL, "Normal"),
        (PRIORITY_HIGH, "High"),
        (PRIORITY_URGENT, "Urgent"),
    ]

    conversation = models.ForeignKey(
        SmartChatConversation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="support_tickets",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="smartchat_support_tickets",
    )
    assigned_admin = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_smartchat_support_tickets",
        limit_choices_to={"is_staff": True},
    )
    title = models.CharField(max_length=220)
    description = models.TextField()
    audience = models.CharField(max_length=30, choices=SmartChatConversation.AUDIENCE_CHOICES, default=SmartChatConversation.AUDIENCE_CUSTOMER)
    intent = models.CharField(max_length=80, blank=True, db_index=True)
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default=PRIORITY_NORMAL, db_index=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_OPEN, db_index=True)
    order = models.ForeignKey("orders.Order", on_delete=models.SET_NULL, null=True, blank=True, related_name="smartchat_support_tickets")
    product = models.ForeignKey("products.Product", on_delete=models.SET_NULL, null=True, blank=True, related_name="smartchat_support_tickets")
    vendor_profile = models.ForeignKey("vendors.VendorProfile", on_delete=models.SET_NULL, null=True, blank=True, related_name="smartchat_support_tickets")
    rider_profile = models.ForeignKey("deliveries.RiderProfile", on_delete=models.SET_NULL, null=True, blank=True, related_name="smartchat_support_tickets")
    metadata = models.JSONField(default=dict, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["priority", "status"]),
            models.Index(fields=["audience", "status"]),
            models.Index(fields=["intent", "-created_at"]),
        ]
        verbose_name = "Smart Chat Support Ticket"
        verbose_name_plural = "Smart Chat Support Tickets"

    def __str__(self):
        return f"#{self.id} {self.title}"

    def mark_resolved(self):
        self.status = self.STATUS_RESOLVED
        self.resolved_at = timezone.now()
        self.save(update_fields=["status", "resolved_at", "updated_at"])
