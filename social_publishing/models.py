from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone

from core.models import BaseModel


class SocialPlatform(models.TextChoices):
    YOUTUBE = "youtube", "YouTube"
    INSTAGRAM = "instagram", "Instagram"
    FACEBOOK = "facebook", "Facebook"
    TIKTOK = "tiktok", "TikTok"
    LINKEDIN = "linkedin", "LinkedIn"


class SocialOwnerRole(models.TextChoices):
    VENDOR = "vendor", "Vendor"
    PROVIDER = "provider", "Service Provider"
    ADMIN = "admin", "Arolana Admin"


class SocialConnectionStatus(models.TextChoices):
    CONNECTED = "connected", "Connected"
    EXPIRED = "expired", "Expired"
    REVOKED = "revoked", "Revoked"
    ERROR = "error", "Error"


class SocialAccount(BaseModel):
    """OAuth-authorized publishing identity for one Arolana user role.

    Tokens are intentionally kept server-side. Plain social passwords are never
    stored. Encryption-at-rest is supplied by the service layer before live OAuth
    integrations are enabled.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="social_publishing_accounts",
    )
    owner_role = models.CharField(max_length=20, choices=SocialOwnerRole.choices)
    platform = models.CharField(max_length=20, choices=SocialPlatform.choices)
    external_account_id = models.CharField(max_length=255, blank=True)
    account_name = models.CharField(max_length=255, blank=True)
    account_username = models.CharField(max_length=255, blank=True)
    status = models.CharField(
        max_length=20,
        choices=SocialConnectionStatus.choices,
        default=SocialConnectionStatus.CONNECTED,
        db_index=True,
    )
    access_token_encrypted = models.TextField(blank=True)
    refresh_token_encrypted = models.TextField(blank=True)
    token_expires_at = models.DateTimeField(blank=True, null=True)
    scopes = models.JSONField(default=list, blank=True)
    platform_metadata = models.JSONField(default=dict, blank=True)
    connected_at = models.DateTimeField(default=timezone.now)
    last_verified_at = models.DateTimeField(blank=True, null=True)
    last_error = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "owner_role", "platform"],
                name="uniq_social_account_user_role_platform",
            )
        ]
        indexes = [
            models.Index(fields=["user", "owner_role", "status"]),
            models.Index(fields=["platform", "status"]),
        ]

    def __str__(self):
        label = self.account_username or self.account_name or self.external_account_id or "account"
        return f"{self.get_platform_display()} · {label}"

    @property
    def is_connected(self):
        if self.status != SocialConnectionStatus.CONNECTED:
            return False
        return not self.token_expires_at or self.token_expires_at > timezone.now()


class PublicationStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    QUEUED = "queued", "Queued"
    UPLOADING = "uploading", "Uploading"
    PROCESSING = "processing", "Processing"
    PUBLISHED = "published", "Published"
    RETRYING = "retrying", "Retrying"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"


class SocialPublication(BaseModel):
    """One content-to-platform publication attempt/state machine."""

    owner_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="social_publications",
    )
    owner_role = models.CharField(max_length=20, choices=SocialOwnerRole.choices)
    social_account = models.ForeignKey(
        SocialAccount,
        on_delete=models.SET_NULL,
        related_name="publications",
        blank=True,
        null=True,
    )
    platform = models.CharField(max_length=20, choices=SocialPlatform.choices, db_index=True)

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")

    status = models.CharField(
        max_length=20,
        choices=PublicationStatus.choices,
        default=PublicationStatus.PENDING,
        db_index=True,
    )
    external_id = models.CharField(max_length=255, blank=True)
    external_url = models.URLField(max_length=1000, blank=True)
    attempt_count = models.PositiveIntegerField(default=0)
    last_attempt_at = models.DateTimeField(blank=True, null=True)
    next_retry_at = models.DateTimeField(blank=True, null=True)
    published_at = models.DateTimeField(blank=True, null=True)
    error_code = models.CharField(max_length=120, blank=True)
    error_message = models.TextField(blank=True)
    request_metadata = models.JSONField(default=dict, blank=True)
    response_metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["owner_user", "owner_role", "platform", "content_type", "object_id"],
                name="uniq_social_publication_content_platform",
            )
        ]
        indexes = [
            models.Index(fields=["status", "next_retry_at"]),
            models.Index(fields=["content_type", "object_id"]),
            models.Index(fields=["owner_user", "owner_role", "created_at"]),
        ]

    def __str__(self):
        return f"{self.get_platform_display()} · {self.get_status_display()} · {self.object_id}"


class TemporaryVideoLease(BaseModel):
    """Tracks temporary video staging only; never a permanent video library."""

    owner_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="temporary_social_video_leases",
    )
    owner_role = models.CharField(max_length=20, choices=SocialOwnerRole.choices)
    storage_key = models.CharField(max_length=1000, unique=True)
    original_filename = models.CharField(max_length=500, blank=True)
    file_size = models.PositiveBigIntegerField(default=0)
    mime_type = models.CharField(max_length=120, blank=True)
    expires_at = models.DateTimeField(db_index=True)
    cleanup_completed_at = models.DateTimeField(blank=True, null=True)
    cleanup_error = models.TextField(blank=True)

    class Meta:
        indexes = [models.Index(fields=["expires_at", "cleanup_completed_at"])]

    @property
    def is_expired(self):
        return self.expires_at <= timezone.now()
