from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
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
    device_id = models.CharField(max_length=160, blank=True, db_index=True)
    channel = models.CharField(
        max_length=20,
        choices=[("web", "Web"), ("mobile", "Mobile"), ("admin", "Admin")],
        default="web",
        db_index=True,
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
    resolved_at = models.DateTimeField(null=True, blank=True)

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
        self.resolved_at = timezone.now()
        self.save(update_fields=["status", "resolved_at", "updated_at"])

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
    source_type = models.CharField(max_length=40, blank=True, db_index=True)
    source_label = models.CharField(max_length=220, blank=True)
    source_object_id = models.PositiveBigIntegerField(null=True, blank=True)
    confidence = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)
    is_read_by_customer = models.BooleanField(default=False, db_index=True)
    is_read_by_admin = models.BooleanField(default=False, db_index=True)

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
        if self.sender_type == self.SENDER_USER:
            self.is_read_by_customer = True
        elif self.sender_type in {self.SENDER_AI, self.SENDER_ADMIN, self.SENDER_SYSTEM}:
            self.is_read_by_admin = True
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


class AIConversation(SmartChatConversation):
    class Meta:
        proxy = True
        verbose_name = "AI Conversation"
        verbose_name_plural = "AI Conversations"


class AIMessage(SmartChatMessage):
    class Meta:
        proxy = True
        verbose_name = "AI Message"
        verbose_name_plural = "AI Messages"


class AIKnowledgeBase(models.Model):
    AUDIENCE_CHOICES = [("all", "All")] + SmartChatConversation.AUDIENCE_CHOICES
    ANSWER_TYPE_CHOICES = [
        ("customer_answer", "Customer answer"),
        ("internal_rule", "Internal rule"),
        ("policy_rule", "Policy rule"),
        ("catalog_lookup_rule", "Catalog lookup rule"),
        ("recommendation_rule", "Recommendation rule"),
        ("escalation_rule", "Escalation rule"),
    ]

    question = models.CharField(max_length=500)
    answer = models.TextField()
    answer_type = models.CharField(
        max_length=40,
        choices=ANSWER_TYPE_CHOICES,
        default="customer_answer",
        db_index=True,
    )
    category = models.CharField(max_length=120, blank=True, db_index=True)
    keywords = models.TextField(blank=True, help_text="Comma-separated search terms.")
    audience = models.CharField(max_length=30, choices=AUDIENCE_CHOICES, default="all", db_index=True)
    approved = models.BooleanField(default=False, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    priority = models.PositiveSmallIntegerField(default=50, db_index=True)
    usage_count = models.PositiveIntegerField(default=0)
    last_used_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="created_ai_knowledge",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="approved_ai_knowledge",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-priority", "question"]
        indexes = [models.Index(fields=["approved", "is_active", "-priority"])]
        verbose_name = "AI Knowledge Base"
        verbose_name_plural = "AI Knowledge Base"

    def __str__(self):
        return self.question


class AILearnedKnowledge(models.Model):
    KNOWLEDGE_TYPE_CHOICES = [
        ("standalone_question", "Standalone question"),
        ("follow_up_context", "Follow-up context"),
        ("recommendation_request", "Recommendation request"),
        ("recommendation_decision", "Recommendation decision"),
        ("product_availability", "Product availability"),
        ("category_availability", "Category availability"),
        ("brand_availability", "Brand availability"),
        ("product_comparison", "Product comparison"),
        ("product_specification", "Product specification"),
        ("stock_question", "Stock question"),
        ("price_question", "Price question"),
        ("warranty_question", "Warranty question"),
        ("order_support", "Order support"),
        ("return_support", "Return support"),
        ("vendor_question", "Vendor question"),
        ("service_request", "Service request"),
        ("human_handoff", "Human handoff"),
        ("unclear", "Unclear"),
    ]
    normalized_question = models.CharField(max_length=500, unique=True)
    proposed_answer = models.TextField()
    answer_type = models.CharField(
        max_length=40,
        choices=AIKnowledgeBase.ANSWER_TYPE_CHOICES,
        default="customer_answer",
        db_index=True,
    )
    knowledge_type = models.CharField(
        max_length=50,
        choices=KNOWLEDGE_TYPE_CHOICES,
        default="standalone_question",
        db_index=True,
    )
    context_type = models.CharField(max_length=80, blank=True, db_index=True)
    context_value = models.CharField(max_length=240, blank=True)
    requires_previous_context = models.BooleanField(default=False, db_index=True)
    requires_live_catalog = models.BooleanField(default=False, db_index=True)
    category = models.CharField(max_length=120, blank=True, db_index=True)
    keywords = models.TextField(blank=True)
    occurrence_count = models.PositiveIntegerField(default=1)
    confidence = models.DecimalField(max_digits=5, decimal_places=4, default=0)
    approved = models.BooleanField(default=False, db_index=True)
    rejected = models.BooleanField(default=False, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    privacy_safe = models.BooleanField(default=False, db_index=True)
    source_conversation = models.ForeignKey(
        SmartChatConversation, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="learned_knowledge",
    )
    source_message = models.ForeignKey(
        SmartChatMessage, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="learned_knowledge",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="reviewed_ai_learning",
    )
    review_notes = models.TextField(blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-occurrence_count", "-updated_at"]
        indexes = [models.Index(fields=["approved", "privacy_safe", "is_active"])]
        verbose_name = "AI Learned Knowledge"
        verbose_name_plural = "AI Learned Knowledge"

    def __str__(self):
        return self.normalized_question


class AICustomerMemory(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True,
        related_name="ai_customer_memories",
    )
    session_key = models.CharField(max_length=120, blank=True, db_index=True)
    device_id = models.CharField(max_length=160, blank=True, db_index=True)
    memory_key = models.CharField(max_length=120)
    memory_value = models.TextField()
    category = models.CharField(max_length=80, blank=True, db_index=True)
    confidence = models.DecimalField(max_digits=5, decimal_places=4, default=1)
    is_active = models.BooleanField(default=True, db_index=True)
    source_conversation = models.ForeignKey(
        SmartChatConversation, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="customer_memories",
    )
    source_message = models.ForeignKey(
        SmartChatMessage, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="customer_memories",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(user__isnull=False) | ~Q(session_key="") | ~Q(device_id=""),
                name="ai_memory_has_owner",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "is_active"]),
            models.Index(fields=["session_key", "is_active"]),
            models.Index(fields=["device_id", "is_active"]),
        ]
        verbose_name = "AI Customer Memory"
        verbose_name_plural = "AI Customer Memories"

    def clean(self):
        if not self.user_id and not self.session_key and not self.device_id:
            raise ValidationError("Customer memory must have an owner.")

    def __str__(self):
        return f"{self.memory_key}: {self.memory_value[:80]}"


class AIFeedback(models.Model):
    conversation = models.ForeignKey(
        SmartChatConversation, on_delete=models.CASCADE, related_name="feedback",
    )
    message = models.ForeignKey(
        SmartChatMessage, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="feedback",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="ai_feedback",
    )
    session_key = models.CharField(max_length=120, blank=True, db_index=True)
    device_id = models.CharField(max_length=160, blank=True, db_index=True)
    rating = models.PositiveSmallIntegerField()
    helpful = models.BooleanField(null=True, blank=True)
    comment = models.TextField(blank=True)
    is_reviewed = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "AI Feedback"
        verbose_name_plural = "AI Feedback & Ratings"

    def clean(self):
        if not 1 <= int(self.rating or 0) <= 5:
            raise ValidationError({"rating": "Rating must be from 1 to 5."})


class AITrainingData(models.Model):
    question = models.CharField(max_length=500)
    answer = models.TextField()
    answer_type = models.CharField(
        max_length=40,
        choices=AIKnowledgeBase.ANSWER_TYPE_CHOICES,
        default="customer_answer",
        db_index=True,
    )
    category = models.CharField(max_length=120, blank=True, db_index=True)
    keywords = models.TextField(blank=True)
    audience = models.CharField(
        max_length=30, choices=AIKnowledgeBase.AUDIENCE_CHOICES, default="all", db_index=True,
    )
    approved = models.BooleanField(default=False, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    priority = models.PositiveSmallIntegerField(default=50)
    metadata = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="created_ai_training_data",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-priority", "question"]
        indexes = [models.Index(fields=["approved", "is_active", "-priority"])]
        verbose_name = "AI Training Data"
        verbose_name_plural = "AI Training Center"

    def __str__(self):
        return self.question


class AISettings(models.Model):
    enabled = models.BooleanField(default=True)
    provider = models.CharField(max_length=40, default="openai")
    model_name = models.CharField(max_length=120, default="gpt-5.5")
    system_prompt = models.TextField(blank=True)
    minimum_confidence = models.DecimalField(max_digits=5, decimal_places=4, default=0.45)
    memory_enabled = models.BooleanField(default=True)
    learning_enabled = models.BooleanField(default=True)
    repeated_question_threshold = models.PositiveSmallIntegerField(default=3)
    history_message_limit = models.PositiveSmallIntegerField(default=12)
    polling_seconds = models.PositiveSmallIntegerField(default=6)
    fallback_message = models.CharField(
        max_length=300, default="Let me connect you with Arolana support.",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="updated_ai_settings",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "AI Settings"
        verbose_name_plural = "AI Settings"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return "Arolana Smart Chat Settings"


class HumanTakeoverRequest(models.Model):
    STATUS_PENDING = "pending"
    STATUS_ASSIGNED = "assigned"
    STATUS_RESOLVED = "resolved"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_ASSIGNED, "Assigned"),
        (STATUS_RESOLVED, "Resolved"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    conversation = models.ForeignKey(
        SmartChatConversation, on_delete=models.CASCADE, related_name="takeover_requests",
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="ai_takeover_requests",
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="assigned_ai_takeovers", limit_choices_to={"is_staff": True},
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    priority = models.CharField(
        max_length=20, choices=SmartChatSupportTicket.PRIORITY_CHOICES,
        default=SmartChatSupportTicket.PRIORITY_NORMAL, db_index=True,
    )
    reason = models.TextField(blank=True)
    requested_at = models.DateTimeField(auto_now_add=True, db_index=True)
    assigned_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-requested_at"]
        indexes = [models.Index(fields=["status", "-requested_at"])]
        verbose_name = "Human Takeover Request"
        verbose_name_plural = "Human Takeover"

    def __str__(self):
        return f"Conversation #{self.conversation_id} - {self.get_status_display()}"


class AIUnansweredQuestion(models.Model):
    conversation = models.ForeignKey(
        SmartChatConversation,
        on_delete=models.CASCADE,
        related_name="unanswered_questions",
    )
    message = models.ForeignKey(
        SmartChatMessage,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="unanswered_question_records",
    )
    question = models.TextField()
    normalized_question = models.CharField(max_length=500, db_index=True)
    detected_intent = models.CharField(max_length=80, blank=True, db_index=True)
    marketplace_category = models.CharField(max_length=80, blank=True, db_index=True)
    confidence = models.DecimalField(max_digits=5, decimal_places=4, default=0)
    reason = models.CharField(max_length=240, blank=True)
    context_snapshot = models.JSONField(default=dict, blank=True)
    occurrence_count = models.PositiveIntegerField(default=1)
    is_resolved = models.BooleanField(default=False, db_index=True)
    resolved_knowledge = models.ForeignKey(
        AIKnowledgeBase,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolved_unanswered_questions",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_ai_unanswered_questions",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-occurrence_count", "-updated_at"]
        indexes = [
            models.Index(fields=["is_resolved", "-updated_at"], name="smartchat_a_is_reso_3877ec_idx"),
            models.Index(fields=["marketplace_category", "detected_intent"], name="smartchat_a_marketp_472c1c_idx"),
        ]
        verbose_name = "AI Unanswered Question"
        verbose_name_plural = "AI Unanswered Questions"

    def __str__(self):
        return self.question[:120]


class AIIntentLog(models.Model):
    conversation = models.ForeignKey(
        SmartChatConversation,
        on_delete=models.CASCADE,
        related_name="intent_logs",
    )
    message = models.ForeignKey(
        SmartChatMessage,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="intent_logs",
    )
    intent = models.CharField(max_length=80, db_index=True)
    previous_intent = models.CharField(max_length=80, blank=True, db_index=True)
    confidence = models.DecimalField(max_digits=5, decimal_places=4, default=1)
    channel = models.CharField(max_length=20, blank=True, db_index=True)
    used_memory = models.BooleanField(default=False)
    triggered_search = models.BooleanField(default=False)
    triggered_handover = models.BooleanField(default=False)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["intent", "-created_at"], name="smartchat_a_intent_841ee7_idx"),
            models.Index(fields=["channel", "-created_at"], name="smartchat_a_channel_e581cf_idx"),
        ]
        verbose_name = "AI Intent Log"
        verbose_name_plural = "AI Intent Analytics"

    def __str__(self):
        return f"{self.intent} - conversation #{self.conversation_id}"


class AICategoryRouterLog(models.Model):
    conversation = models.ForeignKey(
        SmartChatConversation,
        on_delete=models.CASCADE,
        related_name="category_router_logs",
    )
    message = models.ForeignKey(
        SmartChatMessage,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="category_router_logs",
    )
    marketplace_category = models.CharField(max_length=80, db_index=True)
    catalog_category = models.ForeignKey(
        "products.Category",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_router_logs",
    )
    confidence = models.DecimalField(max_digits=5, decimal_places=4, default=0)
    matched_terms = models.JSONField(default=list, blank=True)
    route_source = models.CharField(max_length=80, blank=True)
    entity_type = models.CharField(max_length=40, blank=True)
    entity_id = models.PositiveBigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["marketplace_category", "-created_at"], name="smartchat_a_marketp_778797_idx"),
            models.Index(fields=["entity_type", "entity_id"], name="smartchat_a_entity__5e38d9_idx"),
        ]
        verbose_name = "AI Category Router Log"
        verbose_name_plural = "AI Category Analytics"

    def __str__(self):
        return f"{self.marketplace_category} - conversation #{self.conversation_id}"
