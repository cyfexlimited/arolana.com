from django.conf import settings
from django.db import models
from django.utils import timezone


class PageVisit(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="page_visits",
    )

    ip_address = models.GenericIPAddressField(null=True, blank=True)
    country = models.CharField(max_length=10, blank=True)

    user_agent = models.TextField(blank=True)
    device_type = models.CharField(max_length=50, blank=True, db_index=True)
    browser = models.CharField(max_length=100, blank=True, db_index=True)
    operating_system = models.CharField(max_length=100, blank=True, db_index=True)

    referrer = models.URLField(max_length=1000, blank=True)
    page_url = models.URLField(max_length=1000, blank=True, db_index=True)
    path = models.CharField(max_length=1000, blank=True, db_index=True)

    session_key = models.CharField(max_length=100, blank=True, db_index=True)

    method = models.CharField(max_length=20, blank=True)
    status_code = models.PositiveSmallIntegerField(null=True, blank=True)

    is_authenticated = models.BooleanField(default=False)
    is_bot = models.BooleanField(default=False, db_index=True)

    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Page Visit"
        verbose_name_plural = "Page Visits"
        indexes = [
            models.Index(fields=["created_at", "country"]),
            models.Index(fields=["created_at", "device_type"]),
            models.Index(fields=["created_at", "browser"]),
            models.Index(fields=["path", "created_at"]),
            models.Index(fields=["session_key", "created_at"]),
        ]

    def __str__(self):
        return f"{self.page_url or self.path} - {self.ip_address or 'No IP'}"


class ClickEvent(models.Model):
    EVENT_UNKNOWN = "unknown"
    EVENT_BUTTON = "button"
    EVENT_LINK = "link"
    EVENT_PRODUCT = "product"
    EVENT_CATEGORY = "category"
    EVENT_LANDING_CTA = "landing_cta"
    EVENT_VENDOR = "vendor"
    EVENT_WHATSAPP = "whatsapp"
    EVENT_PHONE = "phone"
    EVENT_EMAIL = "email"
    EVENT_VIDEO = "video"

    EVENT_TYPE_CHOICES = [
        (EVENT_UNKNOWN, "Unknown"),
        (EVENT_BUTTON, "Button"),
        (EVENT_LINK, "Link"),
        (EVENT_PRODUCT, "Product"),
        (EVENT_CATEGORY, "Category"),
        (EVENT_LANDING_CTA, "Landing Page CTA"),
        (EVENT_VENDOR, "Vendor Link"),
        (EVENT_WHATSAPP, "WhatsApp Link"),
        (EVENT_PHONE, "Phone Link"),
        (EVENT_EMAIL, "Email Link"),
        (EVENT_VIDEO, "Video Button"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="click_events",
    )

    ip_address = models.GenericIPAddressField(null=True, blank=True)
    country = models.CharField(max_length=10, blank=True)

    user_agent = models.TextField(blank=True)
    device_type = models.CharField(max_length=50, blank=True, db_index=True)
    browser = models.CharField(max_length=100, blank=True, db_index=True)
    operating_system = models.CharField(max_length=100, blank=True, db_index=True)

    referrer = models.URLField(max_length=1000, blank=True)
    page_url = models.URLField(max_length=1000, blank=True, db_index=True)
    path = models.CharField(max_length=1000, blank=True, db_index=True)

    clicked_text = models.CharField(max_length=500, blank=True, db_index=True)
    clicked_url = models.URLField(max_length=1000, blank=True, db_index=True)

    element_tag = models.CharField(max_length=50, blank=True)
    element_id = models.CharField(max_length=200, blank=True)
    element_classes = models.CharField(max_length=500, blank=True)

    event_type = models.CharField(
        max_length=50,
        choices=EVENT_TYPE_CHOICES,
        default=EVENT_UNKNOWN,
        db_index=True,
    )

    product_id = models.CharField(max_length=100, blank=True, db_index=True)
    category_id = models.CharField(max_length=100, blank=True, db_index=True)
    vendor_id = models.CharField(max_length=100, blank=True, db_index=True)
    landing_page_id = models.CharField(max_length=100, blank=True, db_index=True)

    session_key = models.CharField(max_length=100, blank=True, db_index=True)

    is_authenticated = models.BooleanField(default=False)
    is_bot = models.BooleanField(default=False, db_index=True)

    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Click Event"
        verbose_name_plural = "Click Events"
        indexes = [
            models.Index(fields=["created_at", "country"]),
            models.Index(fields=["created_at", "device_type"]),
            models.Index(fields=["created_at", "browser"]),
            models.Index(fields=["event_type", "created_at"]),
            models.Index(fields=["clicked_url", "created_at"]),
            models.Index(fields=["clicked_text", "created_at"]),
            models.Index(fields=["session_key", "created_at"]),
        ]

    def __str__(self):
        label = self.clicked_text or self.clicked_url or self.event_type
        return f"{label} - {self.ip_address or 'No IP'}"