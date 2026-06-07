import secrets

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import models
from django.utils import timezone

from core.models import BaseModel


class StaffMobileToken(BaseModel):
    ROLE_ADMIN = "admin"
    ROLE_VENDOR = "vendor"
    ROLE_RIDER = "rider"

    ROLE_CHOICES = [
        (ROLE_ADMIN, "Admin"),
        (ROLE_VENDOR, "Vendor"),
        (ROLE_RIDER, "Rider"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="staff_mobile_tokens",
        null=True,
        blank=True,
    )
    rider = models.ForeignKey(
        "deliveries.RiderProfile",
        on_delete=models.CASCADE,
        related_name="mobile_tokens",
        null=True,
        blank=True,
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    token = models.CharField(max_length=120, unique=True, db_index=True)
    device_name = models.CharField(max_length=180, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["token", "is_active"]),
            models.Index(fields=["role", "is_active"]),
        ]

    def __str__(self):
        owner = self.user or self.rider
        return f"{owner} - {self.role}"

    @classmethod
    def issue(cls, role, user=None, rider=None, device_name=""):
        return cls.objects.create(
            user=user,
            rider=rider,
            role=role,
            token=secrets.token_urlsafe(40),
            device_name=device_name,
            last_used_at=timezone.now(),
        )


class RiderCredential(BaseModel):
    rider = models.OneToOneField(
        "deliveries.RiderProfile",
        on_delete=models.CASCADE,
        related_name="mobile_credential",
    )
    pin_hash = models.CharField(max_length=128, blank=True)

    class Meta:
        verbose_name = "Rider mobile credential"
        verbose_name_plural = "Rider mobile credentials"

    def set_pin(self, pin):
        self.pin_hash = make_password(str(pin))

    def check_pin(self, pin):
        return bool(self.pin_hash and check_password(str(pin), self.pin_hash))

    def __str__(self):
        return f"Credential for {self.rider}"
