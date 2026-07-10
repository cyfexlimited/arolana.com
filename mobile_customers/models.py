from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import models
from django.utils import timezone

from core.models import BaseModel
from core.private_upload_validation import (
    validate_private_profile_image_upload,
)
from products.models import Product


class MobileCustomer(BaseModel):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="mobile_customer_profile",
    )
    full_name = models.CharField(max_length=160, blank=True)
    phone_number = models.CharField(max_length=40, unique=True)
    email = models.EmailField(blank=True)
    pin_hash = models.CharField(max_length=128, blank=True)

    # TRANSITION-ONLY LEGACY FIELD.
    #
    # Existing app sessions are migrated into MobileCustomerAccessToken rows.
    # New authentication code must never issue or persist new plaintext values
    # here. Remove this field in a later migration after:
    #
    #   python manage.py audit_mobile_customer_tokens --fail-on-plaintext
    #
    # passes in production and all direct api_token ORM lookups are gone.
    api_token = models.CharField(
        max_length=120,
        blank=True,
        db_index=True,
        editable=False,
    )

    profile_image = models.ImageField(
        upload_to="mobile_customers/profile_pictures/",
        validators=[validate_private_profile_image_upload],
        blank=True,
        null=True,
    )
    preferred_language = models.CharField(max_length=24, default="english")
    notification_preferences = models.JSONField(default=dict, blank=True)
    last_login_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["phone_number"]),
            models.Index(fields=["email"]),
            models.Index(fields=["api_token"]),
            models.Index(fields=["-created_at"]),
        ]

    def __str__(self):
        return self.full_name or self.phone_number

    def set_pin(self, pin):
        self.pin_hash = make_password(str(pin))

    def check_pin(self, pin):
        if not self.pin_hash:
            return False
        return check_password(str(pin), self.pin_hash)


class MobileCustomerAccessToken(models.Model):
    """
    Revocable, expiring mobile session token.

    The raw bearer token is returned to the client once. Only a keyed digest
    is persisted in the database.
    """

    customer = models.ForeignKey(
        MobileCustomer,
        on_delete=models.CASCADE,
        related_name="access_tokens",
    )
    token_hash = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
    )
    fingerprint = models.CharField(
        max_length=16,
        db_index=True,
        help_text="Non-secret prefix of the keyed token digest for support/audit use.",
    )
    device_name = models.CharField(max_length=160, blank=True)
    expires_at = models.DateTimeField(db_index=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_seen_ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["customer", "revoked_at", "expires_at"],
                name="mobtok_customer_state_idx",
            ),
            models.Index(
                fields=["expires_at", "revoked_at"],
                name="mobtok_expiry_state_idx",
            ),
        ]

    def __str__(self):
        return f"{self.customer} · {self.fingerprint}"

    @property
    def is_usable(self):
        return (
            self.revoked_at is None
            and self.expires_at > timezone.now()
            and getattr(self.customer, "is_active", True)
        )


class MobileWishlistItem(BaseModel):
    customer = models.ForeignKey(
        MobileCustomer,
        on_delete=models.CASCADE,
        related_name="wishlist_items",
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="mobile_wishlist_items",
    )

    class Meta:
        ordering = ["-created_at"]
        unique_together = ("customer", "product")
        indexes = [
            models.Index(fields=["customer", "-created_at"]),
            models.Index(fields=["product", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.customer.phone_number} saved {self.product}"
