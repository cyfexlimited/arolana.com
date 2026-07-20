from decimal import Decimal

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone


class AIProviderConfig(models.Model):
    PROVIDER_OPENAI = "openai"

    PROVIDER_CHOICES = [
        (PROVIDER_OPENAI, "OpenAI"),
    ]

    name = models.CharField(max_length=80, unique=True)
    provider = models.CharField(max_length=40, choices=PROVIDER_CHOICES, default=PROVIDER_OPENAI)
    is_active = models.BooleanField(default=True, db_index=True)
    base_url = models.URLField(blank=True)
    api_key_env_var = models.CharField(max_length=80, default="OPENAI_API_KEY")
    timeout_seconds = models.PositiveIntegerField(default=30)
    max_retries = models.PositiveIntegerField(default=2)
    settings = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.provider})"


class AIModelConfig(models.Model):
    provider = models.ForeignKey(AIProviderConfig, on_delete=models.CASCADE, related_name="models")
    model_name = models.CharField(max_length=120)
    feature = models.CharField(max_length=80, db_index=True)
    is_default = models.BooleanField(default=False, db_index=True)
    supports_structured_outputs = models.BooleanField(default=True)
    supports_tool_calls = models.BooleanField(default=True)
    input_token_cost_per_1k = models.DecimalField(max_digits=10, decimal_places=6, default=Decimal("0.000000"))
    output_token_cost_per_1k = models.DecimalField(max_digits=10, decimal_places=6, default=Decimal("0.000000"))
    max_input_tokens = models.PositiveIntegerField(default=128000)
    max_output_tokens = models.PositiveIntegerField(default=4096)
    settings = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["feature", "-is_default", "model_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "model_name", "feature"],
                name="unique_ai_model_feature",
            ),
        ]

    def __str__(self):
        return f"{self.feature}: {self.model_name}"

    def estimate_cost(self, input_tokens=0, output_tokens=0):
        input_cost = Decimal(str(input_tokens or 0)) / Decimal("1000") * self.input_token_cost_per_1k
        output_cost = Decimal(str(output_tokens or 0)) / Decimal("1000") * self.output_token_cost_per_1k
        return (input_cost + output_cost).quantize(Decimal("0.000001"))


class AIPromptTemplate(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_ACTIVE = "active"
    STATUS_ARCHIVED = "archived"

    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_ACTIVE, "Active"),
        (STATUS_ARCHIVED, "Archived"),
    ]

    key = models.SlugField(max_length=120)
    version = models.PositiveIntegerField(default=1)
    title = models.CharField(max_length=160)
    feature = models.CharField(max_length=80, db_index=True)
    system_prompt = models.TextField()
    developer_prompt = models.TextField(blank=True)
    output_schema = models.JSONField(default=dict, blank=True)
    allowed_roles = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_ai_prompts",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_ai_prompts",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["key", "-version"]
        constraints = [
            models.UniqueConstraint(fields=["key", "version"], name="unique_ai_prompt_version"),
        ]

    def __str__(self):
        return f"{self.key} v{self.version}"


class AIToolDefinition(models.Model):
    name = models.CharField(
        max_length=120,
        unique=True,
        validators=[
            RegexValidator(
                regex=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$",
                message=(
                    "Use a dotted lowercase tool name such as "
                    "quotes.create_quote_request."
                ),
            ),
        ],
    )
    feature = models.CharField(max_length=80, db_index=True)
    description = models.TextField()
    input_schema = models.JSONField(default=dict, blank=True)
    output_schema = models.JSONField(default=dict, blank=True)
    allowed_roles = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    requires_human_approval = models.BooleanField(default=False)
    safe_serializer = models.CharField(max_length=160, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["feature", "name"]

    def __str__(self):
        return self.name


class AIDataBoundaryRule(models.Model):
    ACTION_ALLOW = "allow"
    ACTION_REDACT = "redact"
    ACTION_BLOCK = "block"

    ACTION_CHOICES = [
        (ACTION_ALLOW, "Allow"),
        (ACTION_REDACT, "Redact"),
        (ACTION_BLOCK, "Block"),
    ]

    label = models.CharField(max_length=160)
    model_label = models.CharField(max_length=120, db_index=True)
    field_name = models.CharField(max_length=120, blank=True, db_index=True)
    action = models.CharField(max_length=20, choices=ACTION_CHOICES, default=ACTION_BLOCK, db_index=True)
    reason = models.TextField(blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["model_label", "field_name", "action"]
        indexes = [
            models.Index(fields=["model_label", "field_name", "is_active"]),
        ]

    def __str__(self):
        target = f"{self.model_label}.{self.field_name}" if self.field_name else self.model_label
        return f"{target}: {self.action}"


class AIQuota(models.Model):
    ROLE_CUSTOMER = "customer"
    ROLE_VENDOR = "vendor"
    ROLE_PROVIDER = "provider"
    ROLE_RIDER = "rider"
    ROLE_ADMIN = "admin"
    ROLE_GUEST = "guest"

    ROLE_CHOICES = [
        (ROLE_CUSTOMER, "Customer"),
        (ROLE_VENDOR, "Vendor"),
        (ROLE_PROVIDER, "Provider"),
        (ROLE_RIDER, "Rider"),
        (ROLE_ADMIN, "Admin"),
        (ROLE_GUEST, "Guest"),
    ]

    role = models.CharField(max_length=30, choices=ROLE_CHOICES, db_index=True)
    feature = models.CharField(max_length=80, db_index=True)
    max_requests_per_day = models.PositiveIntegerField(default=100)
    max_tokens_per_day = models.PositiveIntegerField(default=100000)
    max_cost_per_day = models.DecimalField(max_digits=10, decimal_places=4, default=Decimal("0.0000"))
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["role", "feature"]
        constraints = [
            models.UniqueConstraint(fields=["role", "feature"], name="unique_ai_quota_role_feature"),
        ]

    def __str__(self):
        return f"{self.role}:{self.feature}"


class AIUsageEvent(models.Model):
    STATUS_SUCCESS = "success"
    STATUS_BLOCKED = "blocked"
    STATUS_ERROR = "error"
    STATUS_SKIPPED = "skipped"

    STATUS_CHOICES = [
        (STATUS_SUCCESS, "Success"),
        (STATUS_BLOCKED, "Blocked"),
        (STATUS_ERROR, "Error"),
        (STATUS_SKIPPED, "Skipped"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    role = models.CharField(max_length=30, db_index=True)
    feature = models.CharField(max_length=80, db_index=True)
    provider = models.CharField(max_length=40, blank=True)
    model_name = models.CharField(max_length=120, blank=True)
    prompt_key = models.CharField(max_length=120, blank=True)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    estimated_cost = models.DecimalField(max_digits=12, decimal_places=6, default=Decimal("0.000000"))
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_SUCCESS, db_index=True)
    latency_ms = models.PositiveIntegerField(default=0)
    request_id = models.CharField(max_length=80, blank=True, db_index=True)
    session_key = models.CharField(max_length=120, blank=True, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["role", "feature", "-created_at"]),
            models.Index(fields=["user", "feature", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.feature} {self.status} {self.created_at:%Y-%m-%d %H:%M}"


class AIAuditLog(models.Model):
    ACTION_CHOICES = [
        ("provider_request", "Provider request"),
        ("tool_call", "Tool call"),
        ("redaction", "Redaction"),
        ("quota_check", "Quota check"),
        ("policy_block", "Policy block"),
        ("configuration_change", "Configuration change"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    role = models.CharField(max_length=30, blank=True, db_index=True)
    feature = models.CharField(max_length=80, blank=True, db_index=True)
    action = models.CharField(max_length=40, choices=ACTION_CHOICES, db_index=True)
    object_label = models.CharField(max_length=160, blank=True)
    object_id = models.CharField(max_length=80, blank=True)
    request_id = models.CharField(max_length=80, blank=True, db_index=True)
    safe_summary = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.action} {timezone.localtime(self.created_at):%Y-%m-%d %H:%M}"
