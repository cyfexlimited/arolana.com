from django.conf import settings
from django.db import models

from core.models import BaseModel


class NewsletterSubscriber(BaseModel):
    """Unified newsletter subscriber model."""

    SOURCE_CHOICES = [
        ("homepage", "Homepage"),
        ("blog", "Blog"),
        ("footer", "Footer"),
        ("checkout", "Checkout"),
        ("registration", "Registration"),
        ("google", "Google Signup"),
        ("facebook", "Facebook Signup"),
        ("api", "API"),
        ("manual", "Manual"),
        ("other", "Other"),
    ]

    email = models.EmailField(unique=True)
    name = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    subscribed_at = models.DateTimeField(auto_now_add=True)
    unsubscribed_at = models.DateTimeField(null=True, blank=True)

    source = models.CharField(
        max_length=50,
        choices=SOURCE_CHOICES,
        default="homepage",
        db_index=True,
    )

    preferences = models.JSONField(
        default=dict,
        blank=True,
        help_text="User preferences for newsletters.",
    )

    class Meta:
        ordering = ["-subscribed_at"]
        verbose_name = "Newsletter Subscriber"
        verbose_name_plural = "Newsletter Subscribers"

    def __str__(self):
        return self.email

    def unsubscribe(self):
        from django.utils import timezone

        self.is_active = False
        self.unsubscribed_at = timezone.now()
        self.save(update_fields=["is_active", "unsubscribed_at", "updated_at"])


class NewsletterCampaign(BaseModel):
    """Designed newsletter campaigns for products, promos, vendor news, and launch updates."""

    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("scheduled", "Scheduled"),
        ("sending", "Sending"),
        ("sent", "Sent"),
        ("cancelled", "Cancelled"),
    ]

    RECIPIENT_CHOICES = [
        ("subscribers", "Active newsletter subscribers"),
        ("registered", "Registered user emails"),
        ("all", "Subscribers and registered users"),
    ]

    FREQUENCY_CHOICES = [
        ("once", "One time"),
        ("weekly", "Weekly"),
        ("monthly", "Monthly"),
        ("custom", "Custom schedule"),
    ]

    CAMPAIGN_TYPE_CHOICES = [
        ("product_announcement", "Product Announcement"),
        ("new_arrival", "New Arrival"),
        ("promotion", "Promotion"),
        ("marketplace_update", "Marketplace Update"),
        ("vendor_update", "Vendor Update"),
        ("launch_news", "Launch News"),
        ("general", "General Newsletter"),
    ]

    name = models.CharField(max_length=200)
    subject = models.CharField(max_length=200)
    preheader = models.CharField(
        max_length=220,
        blank=True,
        help_text="Short preview text shown by many email apps under the subject.",
    )

    campaign_type = models.CharField(
        max_length=40,
        choices=CAMPAIGN_TYPE_CHOICES,
        default="general",
        db_index=True,
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="draft",
        db_index=True,
    )

    recipient_scope = models.CharField(
        max_length=20,
        choices=RECIPIENT_CHOICES,
        default="all",
        db_index=True,
    )

    send_frequency = models.CharField(
        max_length=20,
        choices=FREQUENCY_CHOICES,
        default="once",
    )

    # Designed email content
    eyebrow = models.CharField(
        max_length=120,
        blank=True,
        help_text="Small label above headline. Example: New Product, Vendor Update, Launch News.",
    )
    headline = models.CharField(
        max_length=220,
        blank=True,
        help_text="Main email headline.",
    )
    subheadline = models.TextField(
        blank=True,
        help_text="Short supporting message under headline.",
    )

    content = models.TextField(
        help_text="Plain text email body/fallback content.",
    )

    html_content = models.TextField(
        blank=True,
        help_text="Optional custom HTML. If filled, it can be used as extra body content inside the designed template.",
    )

    hero_image = models.ImageField(
        upload_to="newsletter/campaigns/hero/",
        null=True,
        blank=True,
        help_text="Upload designed banner/hero image for the email.",
    )
    hero_image_url = models.URLField(
        blank=True,
        help_text="Optional external hero image URL. Used if no uploaded hero image is selected.",
    )

    product_image = models.ImageField(
        upload_to="newsletter/campaigns/products/",
        null=True,
        blank=True,
        help_text="Optional product image for the email.",
    )
    product_image_url = models.URLField(
        blank=True,
        help_text="Optional external product image URL.",
    )

    related_product = models.ForeignKey(
        "products.Product",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="newsletter_campaigns",
        help_text="Optional product connected to this newsletter.",
    )

    product_title = models.CharField(max_length=220, blank=True)
    product_price_text = models.CharField(
        max_length=80,
        blank=True,
        help_text="Example: ₦989,550 or Contact for price.",
    )
    product_description = models.TextField(blank=True)

    button_text = models.CharField(
        max_length=80,
        blank=True,
        default="Shop now",
    )
    button_url = models.URLField(
        blank=True,
        help_text="Main CTA link. Example: product page, landing page, vendor page.",
    )

    secondary_button_text = models.CharField(max_length=80, blank=True)
    secondary_button_url = models.URLField(blank=True)

    footer_note = models.TextField(
        blank=True,
        default="You are receiving this email because you subscribed to Arolana updates.",
    )

    test_email = models.EmailField(
        blank=True,
        help_text="Email address to receive test campaign before sending to all subscribers.",
    )

    scheduled_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    last_sent_at = models.DateTimeField(null=True, blank=True)

    sent_count = models.IntegerField(default=0)
    open_count = models.IntegerField(default=0)
    click_count = models.IntegerField(default=0)
    failed_count = models.IntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["campaign_type", "-created_at"]),
            models.Index(fields=["recipient_scope", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.name} - {self.subject}"


class EmailAudienceMember(BaseModel):
    """Unified admin email audience for registered users and newsletter subscribers."""

    SOURCE_CHOICES = [
        ("registered", "Registered user"),
        ("newsletter", "Newsletter subscriber"),
        ("both", "Registered and newsletter"),
        ("manual", "Manual"),
    ]

    email = models.EmailField(unique=True)
    name = models.CharField(max_length=200, blank=True)

    source = models.CharField(
        max_length=20,
        choices=SOURCE_CHOICES,
        default="manual",
        db_index=True,
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="email_audience_memberships",
    )

    subscriber = models.ForeignKey(
        NewsletterSubscriber,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audience_memberships",
    )

    is_active = models.BooleanField(default=True, db_index=True)
    accepts_promos = models.BooleanField(default=False, db_index=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["email"]
        verbose_name = "Email Audience Member"
        verbose_name_plural = "Email Audience"

    def __str__(self):
        return self.email


class NewsletterTracking(BaseModel):
    """Track newsletter opens and clicks for newsletter subscribers."""

    campaign = models.ForeignKey(
        NewsletterCampaign,
        on_delete=models.CASCADE,
        related_name="tracking",
    )
    subscriber = models.ForeignKey(
        NewsletterSubscriber,
        on_delete=models.CASCADE,
        related_name="tracking",
    )

    opened_at = models.DateTimeField(null=True, blank=True)
    clicked_at = models.DateTimeField(null=True, blank=True)

    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)

    class Meta:
        unique_together = ["campaign", "subscriber"]

    def __str__(self):
        return f"{self.subscriber.email} - {self.campaign.name}"