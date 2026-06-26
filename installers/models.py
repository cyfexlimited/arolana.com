from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Avg
from django.urls import reverse
from django.utils.text import slugify

from core.models import BaseModel


phone_validator = RegexValidator(
    regex=r"^\+?[0-9][0-9\s().-]{6,24}$",
    message="Enter a valid phone number, preferably with country code.",
)


class PublicProviderQuerySet(models.QuerySet):
    def public(self):
        return self.filter(
            is_active=True,
            verification_status=ServiceProviderProfile.STATUS_APPROVED,
            is_verified=True,
        )


class ServiceProviderProfile(BaseModel):
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    VERIFICATION_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
    ]
    PROVIDER_TYPES = [
        ("installer", "Installer"),
        ("repair_engineer", "Repair Engineer"),
        ("maintenance_technician", "Maintenance Technician"),
        ("setup_specialist", "Setup / Configuration Specialist"),
        ("trainer", "Trainer"),
        ("consultant", "Consultant"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="service_provider_profile",
    )
    business_name = models.CharField(max_length=180)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    contact_person = models.CharField(max_length=160)
    provider_type = models.CharField(max_length=40, choices=PROVIDER_TYPES)
    phone_number = models.CharField(max_length=30, validators=[phone_validator])
    whatsapp_number = models.CharField(max_length=30, blank=True, validators=[phone_validator])
    email = models.EmailField()
    website = models.URLField(blank=True)
    country = models.CharField(max_length=100, default="Nigeria")
    state = models.CharField(max_length=100)
    city = models.CharField(max_length=100)
    address = models.TextField()
    service_coverage = models.CharField(
        max_length=300,
        blank=True,
        help_text="Cities, states, or regions this provider serves.",
    )
    description = models.TextField()
    years_of_experience = models.PositiveSmallIntegerField(default=0)
    cac_number = models.CharField(max_length=100, blank=True)
    government_id_upload = models.FileField(
        upload_to="installers/verification/%Y/%m/",
        blank=True,
        null=True,
    )
    profile_image = models.ImageField(
        upload_to="installers/providers/%Y/%m/",
        blank=True,
        null=True,
    )
    verification_status = models.CharField(
        max_length=20,
        choices=VERIFICATION_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
    )
    verification_note = models.TextField(blank=True)
    is_verified = models.BooleanField(default=False, db_index=True)
    average_rating = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(0), MaxValueValidator(5)],
    )
    total_reviews = models.PositiveIntegerField(default=0)
    total_completed_jobs = models.PositiveIntegerField(default=0)

    objects = PublicProviderQuerySet.as_manager()

    class Meta:
        ordering = ["-is_verified", "-average_rating", "business_name"]
        indexes = [
            models.Index(fields=["verification_status", "is_verified", "is_active"]),
            models.Index(fields=["country", "state", "city"]),
            models.Index(fields=["provider_type", "is_active"]),
        ]

    def __str__(self):
        return self.business_name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.business_name) or f"provider-{self.user_id or 'new'}"
            slug = base
            counter = 2
            while ServiceProviderProfile.objects.exclude(pk=self.pk).filter(slug=slug).exists():
                slug = f"{base}-{counter}"
                counter += 1
            self.slug = slug
        if self.verification_status != self.STATUS_APPROVED:
            self.is_verified = False
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("installers:provider_detail", kwargs={"slug": self.slug})

    @property
    def location_label(self):
        return ", ".join(value for value in [self.city, self.state, self.country] if value)

    @property
    def whatsapp_url(self):
        digits = "".join(character for character in (self.whatsapp_number or self.phone_number) if character.isdigit())
        return f"https://wa.me/{digits}" if digits else ""

    def refresh_rating(self):
        approved = self.reviews.filter(is_approved=True)
        aggregate = approved.aggregate(average=Avg("rating"))
        self.average_rating = aggregate["average"] or Decimal("0.00")
        self.total_reviews = approved.count()
        self.save(update_fields=["average_rating", "total_reviews", "updated_at"])


class ServiceCategory(BaseModel):
    name = models.CharField(max_length=160, unique=True)
    slug = models.SlugField(max_length=190, unique=True, blank=True)
    description = models.TextField(blank=True)
    image = models.ImageField(
        upload_to="installers/categories/",
        blank=True,
        null=True,
    )
    icon = models.CharField(max_length=80, blank=True)
    matching_keywords = models.TextField(
        blank=True,
        help_text="Comma-separated product/category keywords used for automatic matching.",
    )
    product_categories = models.ManyToManyField(
        "products.Category",
        blank=True,
        related_name="service_categories",
        help_text="Products in these categories will suggest this service.",
    )

    class Meta:
        verbose_name_plural = "Service categories"
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("installers:category_detail", kwargs={"slug": self.slug})

    @property
    def keywords(self):
        return [word.strip().lower() for word in self.matching_keywords.split(",") if word.strip()]


class ServiceMarketplaceHomepageSection(BaseModel):
    title = models.CharField(max_length=180, default="Need installation, repair, or setup?")
    subtitle = models.CharField(
        max_length=500,
        default="Find verified Arolana installers, engineers, technicians, trainers, and consultants.",
    )
    eyebrow = models.CharField(max_length=100, default="Verified professional services", blank=True)
    customer_button_text = models.CharField(max_length=80, default="Find Verified Installers & Engineers")
    provider_button_text = models.CharField(max_length=80, default="Register as a Service Provider")
    background_image = models.ImageField(
        upload_to="installers/homepage/",
        blank=True,
        null=True,
    )
    background_color = models.CharField(max_length=20, default="#071A44")
    accent_color = models.CharField(max_length=20, default="#FF7A00")
    display_order = models.PositiveIntegerField(default=60)

    class Meta:
        verbose_name = "Service Marketplace Homepage Section"
        verbose_name_plural = "Service Marketplace Homepage Section"
        ordering = ["display_order"]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if self.is_active:
            ServiceMarketplaceHomepageSection.objects.exclude(pk=self.pk).update(is_active=False)
        super().save(*args, **kwargs)


class ProviderService(BaseModel):
    provider = models.ForeignKey(
        ServiceProviderProfile,
        on_delete=models.CASCADE,
        related_name="services",
    )
    category = models.ForeignKey(
        ServiceCategory,
        on_delete=models.PROTECT,
        related_name="provider_services",
    )
    service_name = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    starting_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        blank=True,
        null=True,
        validators=[MinValueValidator(0)],
    )

    class Meta:
        ordering = ["service_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "category", "service_name"],
                name="unique_provider_service_name",
            )
        ]

    def __str__(self):
        return f"{self.provider} - {self.service_name}"


class ServicePortfolio(models.Model):
    provider = models.ForeignKey(
        ServiceProviderProfile,
        on_delete=models.CASCADE,
        related_name="portfolio_items",
    )
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    image = models.ImageField(
        upload_to="installers/portfolio/%Y/%m/",
        blank=True,
        null=True,
    )
    video_url = models.URLField(blank=True)
    project_location = models.CharField(max_length=180, blank=True)
    completed_at = models.DateField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-completed_at", "-created_at"]

    def __str__(self):
        return f"{self.provider}: {self.title}"


class ServiceQuoteRequest(BaseModel):
    STATUS_CHOICES = [
        ("new", "New"),
        ("contacted", "Contacted"),
        ("quoted", "Quoted"),
        ("accepted", "Accepted"),
        ("rejected", "Rejected"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
    ]

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="service_quote_requests",
        blank=True,
        null=True,
    )
    provider = models.ForeignKey(
        ServiceProviderProfile,
        on_delete=models.SET_NULL,
        related_name="quote_requests",
        blank=True,
        null=True,
    )
    category = models.ForeignKey(
        ServiceCategory,
        on_delete=models.SET_NULL,
        related_name="quote_requests",
        blank=True,
        null=True,
    )
    product = models.ForeignKey(
        "products.Product",
        on_delete=models.SET_NULL,
        related_name="service_quote_requests",
        blank=True,
        null=True,
    )
    name = models.CharField(max_length=160)
    phone = models.CharField(max_length=30, validators=[phone_validator])
    whatsapp = models.CharField(max_length=30, blank=True, validators=[phone_validator])
    email = models.EmailField(blank=True)
    state = models.CharField(max_length=100)
    city = models.CharField(max_length=100)
    address = models.TextField()
    service_needed = models.CharField(max_length=220)
    message = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="new", db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["provider", "status"]),
        ]

    def __str__(self):
        return f"{self.name} - {self.service_needed}"


class ServiceReview(models.Model):
    provider = models.ForeignKey(
        ServiceProviderProfile,
        on_delete=models.CASCADE,
        related_name="reviews",
    )
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="service_reviews",
        blank=True,
        null=True,
    )
    rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    comment = models.TextField()
    professionalism_rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    communication_rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    quality_rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    timeliness_rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    is_approved = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.provider} - {self.rating}/5"

    def save(self, *args, **kwargs):
        previous_provider_id = None
        if self.pk:
            previous_provider_id = ServiceReview.objects.filter(pk=self.pk).values_list("provider_id", flat=True).first()
        super().save(*args, **kwargs)
        self.provider.refresh_rating()
        if previous_provider_id and previous_provider_id != self.provider_id:
            old_provider = ServiceProviderProfile.objects.filter(pk=previous_provider_id).first()
            if old_provider:
                old_provider.refresh_rating()

    def delete(self, *args, **kwargs):
        provider = self.provider
        result = super().delete(*args, **kwargs)
        provider.refresh_rating()
        return result
