from django.db import models
from django.utils import timezone

from core.models import BaseModel
from accounts.models import User
from vendors.models import VendorProfile


class ContactMessage(BaseModel):
    name = models.CharField(max_length=200)
    email = models.EmailField()
    subject = models.CharField(max_length=200)
    message = models.TextField()

    vendor = models.ForeignKey(
        VendorProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contact_messages",
    )

    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contact_messages",
    )

    is_read = models.BooleanField(default=False)
    replied = models.BooleanField(default=False)
    replied_at = models.DateTimeField(null=True, blank=True)
    reply_message = models.TextField(blank=True)

    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Contact Message"
        verbose_name_plural = "Contact Messages"

    def __str__(self):
        return f"{self.subject} - {self.name}"

    def mark_as_read(self):
        self.is_read = True
        self.save(update_fields=["is_read"])

    def mark_as_replied(self, reply):
        self.replied = True
        self.replied_at = timezone.now()
        self.reply_message = reply
        self.save(update_fields=["replied", "replied_at", "reply_message"])