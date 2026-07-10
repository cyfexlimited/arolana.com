import secrets

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import models

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

    full_name = models.CharField(
        max_length=160,
        blank=True,
    )

    phone_number = models.CharField(
        max_length=40,
        unique=True,
    )

    email = models.EmailField(
        blank=True,
    )

    pin_hash = models.CharField(
        max_length=128,
        blank=True,
    )

    api_token = models.CharField(
        max_length=120,
        blank=True,
        db_index=True,
    )

    profile_image = models.ImageField(
        upload_to="mobile_customers/profile_pictures/",
        validators=[validate_private_profile_image_upload],
        blank=True,
        null=True,
    )

    preferred_language = models.CharField(
        max_length=24,
        default="english",
    )

    notification_preferences = models.JSONField(
        default=dict,
        blank=True,
    )

    last_login_at = models.DateTimeField(
        null=True,
        blank=True,
    )

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

        return check_password(
            str(pin),
            self.pin_hash,
        )

    def ensure_api_token(self):
        if not self.api_token:
            self.api_token = secrets.token_urlsafe(32)

        return self.api_token


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

        unique_together = (
            "customer",
            "product",
        )

        indexes = [
            models.Index(
                fields=["customer", "-created_at"],
            ),
            models.Index(
                fields=["product", "-created_at"],
            ),
        ]

    def __str__(self):
        return f"{self.customer.phone_number} saved {self.product}"