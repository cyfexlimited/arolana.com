from datetime import timedelta
from decimal import Decimal
import uuid
from urllib.parse import parse_qs, urlparse

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Avg, Prefetch
from django.urls import reverse
from django.utils import timezone
from django.utils.functional import cached_property
from django.utils.text import slugify

from core.image_protection import (
    ProtectedImageUploadPath,
    protect_uploaded_image,
    record_protected_image,
)
from core.models import BaseModel


phone_validator = RegexValidator(
    regex=r"^\+?[0-9][0-9\s().-]{6,24}$",
    message="Enter a valid phone number, preferably with country code.",
)


class PublicProviderQuerySet(models.QuerySet):
    def public(self):
        return self.filter(
            is_active=True,
            verification_status__in=[
                ServiceProviderProfile.STATUS_APPROVED,
                ServiceProviderProfile.STATUS_VERIFIED,
            ],
        )


class ServiceProviderProfile(BaseModel):
    STATUS_DRAFT = "draft"
    STATUS_SUBMITTED = "submitted"
    STATUS_PENDING = "pending_review"
    STATUS_CHANGES_REQUESTED = "changes_requested"
    STATUS_APPROVED = "approved"
    STATUS_VERIFIED = "verified"
    STATUS_REJECTED = "rejected"
    STATUS_SUSPENDED = "suspended"
    STATUS_EXPIRED = "expired"
    VERIFICATION_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_SUBMITTED, "Submitted"),
        (STATUS_PENDING, "Pending review"),
        (STATUS_CHANGES_REQUESTED, "Changes requested"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_VERIFIED, "Verified"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_SUSPENDED, "Suspended"),
        (STATUS_EXPIRED, "Expired"),
    ]
    PROVIDER_TYPES = [
        ("installer", "Installer"),
        ("repair_engineer", "Repair Engineer"),
        ("maintenance_technician", "Maintenance Technician"),
        ("consultant", "Consultant"),
        ("training_provider", "Training Provider"),
        ("av_engineer", "AV Engineer"),
        ("cctv_security_installer", "CCTV / Security Installer"),
        ("network_engineer", "Network Engineer"),
        ("smart_home_installer", "Smart Home Installer"),
        ("cinema_installer", "Cinema Installer"),
        ("interactive_board_installer", "Interactive Board Installer"),
        ("projector_technician", "Projector Technician"),
        ("electrical_low_voltage_technician", "Electrical / Low-voltage Technician"),
        ("rider_logistics_partner", "Rider / Logistics Partner"),
        ("vendor_service_agent", "Vendor Service Agent"),
        ("other", "Other"),
    ]
    KYC_NOT_STARTED = "not_started"
    KYC_PENDING = "pending"
    KYC_APPROVED = "approved"
    KYC_REJECTED = "rejected"
    KYC_EXPIRED = "expired"
    KYC_CHOICES = [
        (KYC_NOT_STARTED, "Not started"),
        (KYC_PENDING, "Pending"),
        (KYC_APPROVED, "Approved"),
        (KYC_REJECTED, "Rejected"),
        (KYC_EXPIRED, "Expired"),
    ]
    LANGUAGE_CHOICES = [
        ("english", "English"),
        ("pidgin", "Pidgin English"),
        ("yoruba", "Yoruba"),
        ("igbo", "Igbo"),
        ("hausa", "Hausa"),
        ("french", "French"),
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
    cac_certificate_upload = models.FileField(
        upload_to="installers/verification/%Y/%m/",
        blank=True,
        null=True,
    )
    government_id_upload = models.FileField(
        upload_to="installers/verification/%Y/%m/",
        blank=True,
        null=True,
    )
    business_logo = models.ImageField(
        upload_to=ProtectedImageUploadPath("installers/providers/logos"),
        blank=True,
        null=True,
    )
    business_banner = models.ImageField(
        upload_to=ProtectedImageUploadPath("installers/providers/banners"),
        blank=True,
        null=True,
    )
    profile_image = models.ImageField(
        upload_to=ProtectedImageUploadPath("installers/providers/profiles"),
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
    admin_note = models.TextField(blank=True)
    rejection_reason = models.TextField(blank=True)
    changes_requested_note = models.TextField(blank=True)
    submitted_at = models.DateTimeField(blank=True, null=True)
    review_started_at = models.DateTimeField(blank=True, null=True)
    approved_at = models.DateTimeField(blank=True, null=True)
    rejected_at = models.DateTimeField(blank=True, null=True)
    changes_requested_at = models.DateTimeField(blank=True, null=True)
    review_due_at = models.DateTimeField(blank=True, null=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="reviewed_service_providers",
        blank=True,
        null=True,
    )
    is_verified = models.BooleanField(default=False, db_index=True)
    kyc_status = models.CharField(max_length=20, choices=KYC_CHOICES, default=KYC_NOT_STARTED, db_index=True)
    kyc_note = models.TextField(blank=True)
    kyc_reviewed_at = models.DateTimeField(blank=True, null=True)
    kyc_expires_at = models.DateTimeField(blank=True, null=True)
    subscription_plan = models.CharField(max_length=80, default="Free / Starter")
    subscription_status = models.CharField(
        max_length=20,
        choices=[
            ("inactive", "Inactive"),
            ("active", "Active"),
            ("trial", "Trial"),
            ("expired", "Expired"),
            ("cancelled", "Cancelled"),
        ],
        default="inactive",
        db_index=True,
    )
    subscription_expires_at = models.DateTimeField(blank=True, null=True)
    allow_limited_jobs_without_kyc = models.BooleanField(default=False)
    availability_status = models.CharField(
        max_length=20,
        choices=[
            ("offline", "Offline"),
            ("online", "Online"),
            ("busy", "Busy"),
            ("unavailable", "Unavailable"),
            ("vacation", "Vacation"),
            ("away", "Away"),
        ],
        default="offline",
    )
    preferred_language = models.CharField(max_length=20, choices=LANGUAGE_CHOICES, default="english")
    notification_preferences = models.JSONField(default=dict, blank=True)
    support_phone = models.CharField(max_length=30, blank=True)
    support_email = models.EmailField(blank=True)
    support_whatsapp = models.CharField(max_length=30, blank=True)
    business_hours = models.CharField(max_length=220, blank=True)
    business_hours_data = models.JSONField(
        default=dict,
        blank=True,
        help_text="Structured opening hours keyed by weekday.",
    )
    availability_note = models.CharField(max_length=300, blank=True)
    bank_details = models.JSONField(default=dict, blank=True)
    last_sensitive_update_approved_at = models.DateTimeField(blank=True, null=True)
    sensitive_update_cooldown_unlocked_until = models.DateTimeField(blank=True, null=True)
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
            models.Index(fields=["kyc_status", "subscription_status"]),
            models.Index(fields=["country", "state", "city"]),
            models.Index(fields=["provider_type", "is_active"]),
        ]

    def __str__(self):
        return self.business_name

    def save(self, *args, **kwargs):
        protect_uploaded_image(self, "business_logo", block_cross_vendor_duplicates=True)
        protect_uploaded_image(self, "business_banner", block_cross_vendor_duplicates=True)
        protect_uploaded_image(self, "profile_image", block_cross_vendor_duplicates=True)
        if not self.slug:
            base = slugify(self.business_name) or f"provider-{self.user_id or 'new'}"
            slug = base
            counter = 2
            while ServiceProviderProfile.objects.exclude(pk=self.pk).filter(slug=slug).exists():
                slug = f"{base}-{counter}"
                counter += 1
            self.slug = slug
        if self.verification_status != self.STATUS_VERIFIED:
            self.is_verified = False
        if self.verification_status == self.STATUS_VERIFIED:
            self.is_verified = True
        if self.verification_status in [self.STATUS_SUBMITTED, self.STATUS_PENDING] and not self.review_due_at:
            self.review_due_at = timezone.now() + timedelta(hours=72)
        super().save(*args, **kwargs)
        record_protected_image(self, "business_logo")
        record_protected_image(self, "business_banner")
        record_protected_image(self, "profile_image")

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

    @property
    def approval_allows_dashboard(self):
        return self.verification_status in [self.STATUS_APPROVED, self.STATUS_VERIFIED]

    @property
    def can_receive_serious_jobs(self):
        return (
            self.approval_allows_dashboard
            and self.is_active
            and (self.kyc_status == self.KYC_APPROVED or self.allow_limited_jobs_without_kyc)
            and self.subscription_status in ["active", "trial"]
        )

    @property
    def profile_completion_percent(self):
        completed_weight = sum(
            item["weight"] for item in self.profile_completion_items if item["complete"]
        )
        total_weight = sum(item["weight"] for item in self.profile_completion_items)
        return round((completed_weight / total_weight) * 100) if total_weight else 0

    @property
    def profile_completion_items(self):
        has_kyc_documents = bool(
            self.kyc_status in {self.KYC_PENDING, self.KYC_APPROVED}
            or self.government_id_upload
            or self.cac_certificate_upload
        )
        return [
            {"key": "identity", "label": "Business identity", "weight": 10, "complete": bool(self.business_name and self.contact_person and self.provider_type), "url": "profile"},
            {"key": "description", "label": "Business description", "weight": 8, "complete": bool(self.description and self.years_of_experience), "url": "profile"},
            {"key": "profile_image", "label": "Profile image", "weight": 6, "complete": bool(self.profile_image), "url": "profile"},
            {"key": "business_logo", "label": "Business logo", "weight": 6, "complete": bool(self.business_logo), "url": "profile"},
            {"key": "business_banner", "label": "Business banner", "weight": 7, "complete": bool(self.business_banner), "url": "profile"},
            {"key": "contact", "label": "Contact information", "weight": 10, "complete": bool(self.phone_number and self.email), "url": "profile"},
            {"key": "location", "label": "Address and location", "weight": 10, "complete": bool(self.address and self.city and self.state and self.country), "url": "profile"},
            {"key": "coverage", "label": "Service coverage", "weight": 7, "complete": bool(self.service_coverage), "url": "coverage"},
            {"key": "services", "label": "At least one active service", "weight": 10, "complete": self.pk is not None and self.services.filter(is_active=True).exists(), "url": "services"},
            {"key": "project", "label": "At least one project", "weight": 8, "complete": self.pk is not None and self.portfolio_items.exists(), "url": "projects"},
            {"key": "kyc", "label": "KYC documents", "weight": 8, "complete": has_kyc_documents, "url": "kyc"},
            {"key": "bank", "label": "Payout details", "weight": 5, "complete": bool(self.bank_details), "url": "settings"},
            {"key": "hours", "label": "Business hours", "weight": 5, "complete": bool(self.business_hours_data or self.business_hours), "url": "availability"},
        ]

    @property
    def profile_missing_steps(self):
        return [item for item in self.profile_completion_items if not item["complete"]]

    @property
    def approved_project_count(self):
        if not self.pk:
            return 0
        return self.portfolio_items.filter(
            approval_status=ServicePortfolio.STATUS_APPROVED,
            is_active=True,
        ).count()

    @property
    def project_views_count(self):
        if not self.pk:
            return 0
        return self.portfolio_items.aggregate(total=models.Sum("views_count"))["total"] or 0

    @property
    def project_video_views_count(self):
        if not self.pk:
            return 0
        return self.portfolio_items.aggregate(total=models.Sum("video_views_count"))["total"] or 0

    @property
    def project_leads_count(self):
        if not self.pk:
            return 0
        return self.quote_requests.exclude(source_project__isnull=True).count()

    @property
    def sensitive_update_locked(self):
        if self.sensitive_update_cooldown_unlocked_until and self.sensitive_update_cooldown_unlocked_until > timezone.now():
            return False
        if not self.last_sensitive_update_approved_at:
            return False
        return self.last_sensitive_update_approved_at + timedelta(days=14) > timezone.now()

    @property
    def sensitive_update_available_at(self):
        if not self.sensitive_update_locked:
            return None
        return self.last_sensitive_update_approved_at + timedelta(days=14)


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
    projects_enabled = models.BooleanField(
        default=True,
        help_text="Show approved professional projects on the marketplace homepage.",
    )
    projects_eyebrow = models.CharField(max_length=100, default="Real Arolana professional work", blank=True)
    projects_title = models.CharField(max_length=180, default="Projects & Proof Network")
    projects_subtitle = models.CharField(
        max_length=500,
        default="Explore verified installations, repairs, equipment deployments, and customer outcomes.",
    )
    projects_button_text = models.CharField(max_length=80, default="Explore Completed Projects")
    projects_limit = models.PositiveSmallIntegerField(default=8)

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


class ProviderProfileChangeRequest(BaseModel):
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
    ]
    provider = models.ForeignKey(
        ServiceProviderProfile,
        on_delete=models.CASCADE,
        related_name="profile_change_requests",
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="provider_profile_change_requests",
        blank=True,
        null=True,
    )
    old_values = models.JSONField(default=dict, blank=True)
    proposed_values = models.JSONField(default=dict, blank=True)
    sensitive_fields = models.JSONField(default=list, blank=True)
    proposed_file = models.FileField(upload_to="installers/profile-change-requests/%Y/%m/", blank=True, null=True)
    proposed_file_field = models.CharField(max_length=80, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    admin_note = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="reviewed_provider_profile_change_requests",
        blank=True,
        null=True,
    )
    reviewed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["provider", "status", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.provider} profile change - {self.status}"


class ProviderKYCDocument(BaseModel):
    DOCUMENT_GOVERNMENT_ID = "government_id"
    DOCUMENT_CAC_CERTIFICATE = "cac_certificate"
    DOCUMENT_ADDRESS_PROOF = "address_proof"
    DOCUMENT_SELFIE = "selfie"
    DOCUMENT_OTHER = "other"
    DOCUMENT_TYPES = [
        (DOCUMENT_GOVERNMENT_ID, "Government ID"),
        (DOCUMENT_CAC_CERTIFICATE, "CAC / Business Certificate"),
        (DOCUMENT_ADDRESS_PROOF, "Address Proof"),
        (DOCUMENT_SELFIE, "Selfie / Profile Verification"),
        (DOCUMENT_OTHER, "Other Document"),
    ]
    provider = models.ForeignKey(
        ServiceProviderProfile,
        on_delete=models.CASCADE,
        related_name="kyc_documents",
    )
    document_type = models.CharField(max_length=40, choices=DOCUMENT_TYPES)
    file = models.FileField(upload_to="installers/kyc/%Y/%m/")
    note = models.CharField(max_length=240, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.provider} - {self.get_document_type_display()}"


class ProviderSubscriptionPlan(BaseModel):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    price_monthly = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    price_yearly = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    benefits = models.JSONField(default=list, blank=True)
    display_order = models.PositiveIntegerField(default=0)
    is_default = models.BooleanField(default=False)

    class Meta:
        ordering = ["display_order", "price_monthly", "name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_default:
            ProviderSubscriptionPlan.objects.exclude(pk=self.pk).update(is_default=False)


class PublicProjectQuerySet(models.QuerySet):
    def public(self):
        return self.filter(
            approval_status=ServicePortfolio.STATUS_APPROVED,
            is_active=True,
            provider__is_active=True,
            provider__verification_status__in=[
                ServiceProviderProfile.STATUS_APPROVED,
                ServiceProviderProfile.STATUS_VERIFIED,
            ],
        )

    def optimized(self):
        return self.select_related(
            "provider",
            "provider__user",
            "service_category",
        ).prefetch_related(
            Prefetch(
                "media_items",
                queryset=ServiceProjectMedia.objects.filter(
                    approval_status=ServiceProjectMedia.STATUS_APPROVED,
                    is_active=True,
                ).order_by("-is_featured", "display_order", "id"),
                to_attr="_public_media_items",
            ),
            "project_products__product",
            "project_products__product__vendor",
        )


class ServicePortfolio(models.Model):
    """Canonical Arolana completed-project record.

    The original portfolio fields remain intact for backwards compatibility.
    New web and mobile project experiences use the richer fields below.
    """
    STATUS_DRAFT = "draft"
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REQUIRES_CHANGES = "requires_changes"
    STATUS_REJECTED = "rejected"
    STATUS_SUSPENDED = "suspended"
    APPROVAL_STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_PENDING, "Pending review"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REQUIRES_CHANGES, "Requires changes"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_SUSPENDED, "Suspended"),
    ]
    PROJECT_TYPE_CHOICES = [
        ("installation", "Installation"),
        ("repair", "Repair"),
        ("maintenance", "Maintenance"),
        ("consulting", "Consulting"),
        ("deployment", "Deployment"),
        ("training", "Training"),
        ("before_after", "Before and after"),
        ("other", "Other"),
    ]
    CUSTOMER_TYPE_CHOICES = [
        ("private", "Private customer"),
        ("business", "Business"),
        ("government", "Government"),
        ("education", "Education"),
        ("religious", "Religious organization"),
        ("nonprofit", "Nonprofit"),
        ("other", "Other"),
    ]
    VIDEO_SOURCE_CHOICES = [
        ("none", "No video"),
        ("youtube", "YouTube"),
        ("external", "External video"),
        ("upload", "Arolana upload"),
    ]

    provider = models.ForeignKey(
        ServiceProviderProfile,
        on_delete=models.CASCADE,
        related_name="portfolio_items",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="created_service_projects",
        blank=True,
        null=True,
    )
    title = models.CharField(max_length=180)
    slug = models.SlugField(max_length=240, unique=True, blank=True)
    short_summary = models.CharField(max_length=500, blank=True)
    description = models.TextField(blank=True)
    image = models.ImageField(
        upload_to=ProtectedImageUploadPath("installers/portfolio"),
        blank=True,
        null=True,
    )
    project_type = models.CharField(
        max_length=30,
        choices=PROJECT_TYPE_CHOICES,
        default="installation",
        db_index=True,
    )
    service_category = models.ForeignKey(
        ServiceCategory,
        on_delete=models.PROTECT,
        related_name="projects",
        blank=True,
        null=True,
    )
    country = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True, db_index=True)
    city = models.CharField(max_length=100, blank=True, db_index=True)
    location_display = models.CharField(max_length=220, blank=True)
    video_url = models.URLField(blank=True)
    video_source = models.CharField(max_length=20, choices=VIDEO_SOURCE_CHOICES, default="none")
    local_video = models.FileField(upload_to="installers/projects/videos/%Y/%m/", blank=True, null=True)
    video_thumbnail = models.ImageField(
        upload_to=ProtectedImageUploadPath("installers/projects/video-thumbnails"),
        blank=True,
        null=True,
    )
    video_duration = models.PositiveIntegerField(default=0, help_text="Duration in seconds.")
    project_location = models.CharField(max_length=180, blank=True)
    completed_at = models.DateField(blank=True, null=True)
    project_duration_text = models.CharField(max_length=120, blank=True)
    customer_type = models.CharField(max_length=30, choices=CUSTOMER_TYPE_CHOICES, blank=True)
    customer_name_display = models.CharField(max_length=180, blank=True)
    customer_name_private = models.CharField(max_length=180, blank=True)
    customer_consent_to_publish = models.BooleanField(default=False)
    project_value_min = models.DecimalField(max_digits=14, decimal_places=2, blank=True, null=True)
    project_value_max = models.DecimalField(max_digits=14, decimal_places=2, blank=True, null=True)
    project_value_currency = models.CharField(max_length=8, default="NGN")
    show_project_value = models.BooleanField(default=False)
    challenge = models.TextField(blank=True)
    solution = models.TextField(blank=True)
    implementation_process = models.TextField(blank=True)
    project_result = models.TextField(blank=True)
    customer_outcome = models.TextField(blank=True)
    technologies_used = models.JSONField(default=list, blank=True)
    services_performed = models.JSONField(default=list, blank=True)
    approval_status = models.CharField(
        max_length=24,
        choices=APPROVAL_STATUS_CHOICES,
        default=STATUS_DRAFT,
        db_index=True,
    )
    moderation_notes = models.TextField(blank=True)
    is_verified_project = models.BooleanField(default=False, db_index=True)
    is_featured = models.BooleanField(default=False, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    views_count = models.PositiveIntegerField(default=0)
    video_views_count = models.PositiveIntegerField(default=0)
    product_click_count = models.PositiveIntegerField(default=0)
    provider_click_count = models.PositiveIntegerField(default=0)
    quote_requests_count = models.PositiveIntegerField(default=0)
    shares_count = models.PositiveIntegerField(default=0)
    saves_count = models.PositiveIntegerField(default=0)
    published_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = PublicProjectQuerySet.as_manager()

    class Meta:
        ordering = ["-is_featured", "-published_at", "-completed_at", "-created_at"]
        indexes = [
            models.Index(fields=["approval_status", "is_active", "-published_at"]),
            models.Index(fields=["service_category", "approval_status", "-completed_at"]),
            models.Index(fields=["country", "state", "city"]),
            models.Index(fields=["provider", "approval_status", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.provider}: {self.title}"

    def save(self, *args, **kwargs):
        protect_uploaded_image(self, "image", block_cross_vendor_duplicates=True)
        protect_uploaded_image(self, "video_thumbnail", block_cross_vendor_duplicates=True)
        if not self.created_by_id and self.provider_id:
            self.created_by_id = self.provider.user_id
        if not self.country and self.provider_id:
            self.country = self.provider.country
        if not self.state and self.provider_id:
            self.state = self.provider.state
        if not self.city and self.provider_id:
            self.city = self.provider.city
        if not self.location_display:
            self.location_display = self.project_location or ", ".join(
                value for value in [self.city, self.state, self.country] if value
            )
        if not self.project_location:
            self.project_location = self.location_display
        if not self.video_source or self.video_source == "none":
            if self.local_video:
                self.video_source = "upload"
            elif "youtu" in (self.video_url or "").lower():
                self.video_source = "youtube"
            elif self.video_url:
                self.video_source = "external"
        if not self.slug:
            stem = slugify(
                " ".join(
                    value for value in [self.title, self.city, self.provider.business_name]
                    if value
                )
            )[:205] or "arolana-project"
            self.slug = f"{stem}-{uuid.uuid4().hex[:8]}"
        if self.approval_status == self.STATUS_APPROVED and not self.published_at:
            self.published_at = timezone.now()
        super().save(*args, **kwargs)
        record_protected_image(self, "image")
        record_protected_image(self, "video_thumbnail")

    def get_absolute_url(self):
        return reverse("projects:detail", kwargs={"slug": self.slug})

    @cached_property
    def featured_media(self):
        prefetched = getattr(self, "_public_media_items", None)
        if prefetched is not None:
            return prefetched[0] if prefetched else None
        return self.media_items.filter(approval_status=ServiceProjectMedia.STATUS_APPROVED).order_by(
            "-is_featured", "display_order", "id"
        ).first()

    @cached_property
    def public_media(self):
        prefetched = getattr(self, "_public_media_items", None)
        if prefetched is not None:
            return prefetched
        return self.media_items.filter(
            approval_status=ServiceProjectMedia.STATUS_APPROVED,
            is_active=True,
        ).order_by("display_order", "id")

    @property
    def has_video(self):
        return bool(self.local_video or self.video_url or self.media_items.filter(media_type="video").exists())

    @property
    def video_embed_url(self):
        value = (self.video_url or "").strip()
        if not value:
            return ""
        if self.video_source != "youtube":
            return value
        try:
            parsed = urlparse(value if "://" in value else f"https://youtu.be/{value}")
            host = parsed.netloc.lower().replace("www.", "")
            video_id = ""
            if host == "youtu.be":
                video_id = parsed.path.strip("/").split("/")[0]
            elif "youtube.com" in host:
                if parsed.path.startswith(("/embed/", "/shorts/")):
                    video_id = parsed.path.strip("/").split("/")[1]
                else:
                    video_id = parse_qs(parsed.query).get("v", [""])[0]
            if video_id:
                return f"https://www.youtube-nocookie.com/embed/{video_id}?playsinline=1&rel=0&modestbranding=1"
        except (IndexError, ValueError):
            pass
        return ""

    @property
    def completion_percent(self):
        checks = [
            self.title,
            self.short_summary,
            self.description or self.challenge,
            self.service_category_id,
            self.location_display,
            self.completed_at,
            self.image or self.media_items.exists(),
            self.project_result or self.customer_outcome,
        ]
        return round(sum(bool(value) for value in checks) / len(checks) * 100)

    @property
    def vendor(self):
        return self.provider.user if self.provider_id else None


class ServiceProjectMedia(BaseModel):
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending review"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
    ]
    MEDIA_TYPES = [
        ("image", "Image"),
        ("video", "Video"),
        ("before_image", "Before image"),
        ("during_image", "During image"),
        ("after_image", "After image"),
        ("progress_image", "Progress image"),
        ("document", "Document"),
    ]
    project = models.ForeignKey(ServicePortfolio, on_delete=models.CASCADE, related_name="media_items")
    media_type = models.CharField(max_length=24, choices=MEDIA_TYPES, default="image", db_index=True)
    image = models.ImageField(
        upload_to=ProtectedImageUploadPath("installers/projects/gallery"),
        blank=True,
        null=True,
    )
    video = models.FileField(upload_to="installers/projects/videos/%Y/%m/", blank=True, null=True)
    external_video_url = models.URLField(blank=True)
    thumbnail = models.ImageField(
        upload_to=ProtectedImageUploadPath("installers/projects/thumbnails"),
        blank=True,
        null=True,
    )
    caption = models.CharField(max_length=300, blank=True)
    alt_text = models.CharField(max_length=220, blank=True)
    display_order = models.PositiveIntegerField(default=0)
    is_featured = models.BooleanField(default=False)
    approval_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)

    class Meta:
        ordering = ["display_order", "id"]
        indexes = [
            models.Index(fields=["project", "approval_status", "display_order"]),
            models.Index(fields=["media_type", "approval_status"]),
        ]

    def __str__(self):
        return f"{self.project.title} - {self.get_media_type_display()}"

    @property
    def vendor(self):
        return self.project.provider.user if self.project_id else None

    def save(self, *args, **kwargs):
        protect_uploaded_image(self, "image", block_cross_vendor_duplicates=True)
        protect_uploaded_image(self, "thumbnail", block_cross_vendor_duplicates=True)
        super().save(*args, **kwargs)
        record_protected_image(self, "image")
        record_protected_image(self, "thumbnail")


class ServiceProjectProduct(models.Model):
    project = models.ForeignKey(ServicePortfolio, on_delete=models.CASCADE, related_name="project_products")
    product = models.ForeignKey("products.Product", on_delete=models.CASCADE, related_name="service_projects")
    usage_note = models.CharField(max_length=500, blank=True)
    quantity_used = models.PositiveIntegerField(default=1)
    is_primary_product = models.BooleanField(default=False)
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["display_order", "id"]
        constraints = [
            models.UniqueConstraint(fields=["project", "product"], name="unique_project_product")
        ]

    def __str__(self):
        return f"{self.project.title} / {self.product}"


class ServiceProjectModerationLog(models.Model):
    project = models.ForeignKey(ServicePortfolio, on_delete=models.CASCADE, related_name="moderation_history")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, blank=True, null=True)
    old_status = models.CharField(max_length=24, blank=True)
    new_status = models.CharField(max_length=24)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class SavedServiceProject(models.Model):
    project = models.ForeignKey(ServicePortfolio, on_delete=models.CASCADE, related_name="saved_by")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="saved_service_projects")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "user"], name="unique_saved_service_project")
        ]


class ServiceProjectReport(models.Model):
    project = models.ForeignKey(ServicePortfolio, on_delete=models.CASCADE, related_name="reports")
    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, blank=True, null=True)
    reason = models.CharField(max_length=120)
    details = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=[("new", "New"), ("reviewed", "Reviewed"), ("dismissed", "Dismissed")],
        default="new",
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)


class ServiceProjectEvent(models.Model):
    EVENT_TYPES = [
        ("view", "View"),
        ("video_view", "Video view"),
        ("product_click", "Product click"),
        ("provider_click", "Provider click"),
        ("share", "Share"),
        ("save", "Save"),
        ("quote_request", "Quote request"),
    ]
    project = models.ForeignKey(ServicePortfolio, on_delete=models.CASCADE, related_name="events")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, blank=True, null=True)
    event_type = models.CharField(max_length=30, choices=EVENT_TYPES, db_index=True)
    session_key = models.CharField(max_length=80, blank=True)
    source = models.CharField(max_length=80, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["project", "event_type", "-created_at"]),
        ]


class ServiceQuoteRequest(BaseModel):
    STATUS_CHOICES = [
        ("new", "New"),
        ("under_review", "Under review"),
        ("assigned", "Assigned"),
        ("accepted", "Accepted"),
        ("rejected_by_provider", "Rejected by provider"),
        ("on_the_way", "On the way"),
        ("in_progress", "In progress"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
        ("closed", "Closed"),
        ("contacted", "Contacted"),
        ("quoted", "Quoted"),
        ("rejected", "Rejected"),
    ]
    URGENCY_CHOICES = [
        ("normal", "Normal"),
        ("urgent", "Urgent"),
        ("emergency", "Emergency"),
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
    source_project = models.ForeignKey(
        ServicePortfolio,
        on_delete=models.SET_NULL,
        related_name="quote_requests",
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
    preferred_date = models.DateField(blank=True, null=True)
    preferred_time = models.TimeField(blank=True, null=True)
    budget = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    contact_preference = models.CharField(max_length=80, blank=True)
    urgency = models.CharField(max_length=20, choices=URGENCY_CHOICES, default="normal")
    provider_note = models.TextField(blank=True)
    completion_photo = models.ImageField(
        upload_to="installers/completions/%Y/%m/",
        blank=True,
        null=True,
    )
    admin_note = models.TextField(blank=True)
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="assigned_service_quote_requests",
        blank=True,
        null=True,
    )
    assigned_at = models.DateTimeField(blank=True, null=True)
    accepted_at = models.DateTimeField(blank=True, null=True)
    completed_at = models.DateTimeField(blank=True, null=True)
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
