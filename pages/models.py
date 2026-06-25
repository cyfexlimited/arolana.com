from django.db import models
from django.urls import reverse
from django.utils import timezone
from django_ckeditor_5.fields import CKEditor5Field

from core.models import BaseModel


class Page(BaseModel):
    """Editable pages like About Us, Privacy Policy, Terms, etc."""

    title = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    content = CKEditor5Field(help_text="Main page content")
    meta_description = models.CharField(max_length=500, blank=True)
    meta_keywords = models.CharField(max_length=500, blank=True)
    sidebar_content = CKEditor5Field(blank=True, help_text="Optional sidebar content")
    show_in_footer = models.BooleanField(default=False)
    show_in_header = models.BooleanField(default=False)
    footer_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["title"]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("pages:detail", args=[self.slug])


class ContactPageSettings(BaseModel):
    """Editable contact page support panel."""

    title = models.CharField(max_length=120, default="Arolana Contact Settings")
    support_email = models.EmailField(default="contact@arolana.com")
    support_phone = models.CharField(max_length=50, default="+2349132924620")
    coverage_text = models.CharField(
        max_length=255,
        default="Nigeria, Africa, and global marketplace support",
    )
    protection_title = models.CharField(max_length=120, default="Marketplace Protection")
    protection_text = models.TextField(
        default="For order issues, include your order number, delivery tracking code, vendor name, and screenshots where possible."
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Contact Page Setting"
        verbose_name_plural = "Contact Page Settings"
        ordering = ["-is_active", "-updated_at"]

    def __str__(self):
        return self.title


class ContactQuickAction(BaseModel):
    """Editable quick links for the contact page."""

    label = models.CharField(max_length=80)
    url = models.CharField(max_length=300, help_text="Use a path like /help/ or a full URL.")
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["order", "label"]

    def __str__(self):
        return self.label


class SupportTopic(BaseModel):
    """Support topics with optional images/icons."""

    title = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    icon = models.CharField(
        max_length=80,
        blank=True,
        help_text="FontAwesome icon class, e.g. fas fa-truck",
    )
    image = models.ImageField(
        upload_to="support/topics/",
        null=True,
        blank=True,
        help_text="Optional topic image/icon",
    )
    description = models.TextField(blank=True)
    button_text = models.CharField(max_length=50, default="Learn More")
    button_url = models.CharField(max_length=500, blank=True)
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["order", "title"]

    def __str__(self):
        return self.title


class SupportArticle(BaseModel):
    """Detailed support articles."""

    title = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    category = models.ForeignKey(
        SupportTopic,
        on_delete=models.CASCADE,
        related_name="articles",
    )
    content = CKEditor5Field()
    image = models.ImageField(upload_to="support/articles/", null=True, blank=True)
    views = models.PositiveIntegerField(default=0)
    helpful_count = models.PositiveIntegerField(default=0)
    not_helpful_count = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("pages:article_detail", args=[self.slug])


class FAQ(BaseModel):
    """Frequently Asked Questions."""

    CATEGORY_CHOICES = [
        ("general", "General"),
        ("orders", "Orders & Shipping"),
        ("returns", "Returns & Refunds"),
        ("vendors", "Vendor Help"),
        ("account", "Account"),
        ("products", "Products"),
        ("payments", "Payments"),
        ("security", "Security & Trust"),
    ]

    question = models.CharField(max_length=500)
    answer = CKEditor5Field()
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES, default="general")
    image = models.ImageField(
        upload_to="support/faqs/",
        null=True,
        blank=True,
        help_text="Optional image for this FAQ",
    )
    order = models.PositiveIntegerField(default=0)
    is_featured = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["category", "order", "question"]
        verbose_name = "FAQ"
        verbose_name_plural = "FAQs"

    def __str__(self):
        return self.question


class HelpCenterHero(BaseModel):
    """Hero section for Help Center."""

    title = models.CharField(max_length=200, default="How Can We Help You?")
    subtitle = models.CharField(max_length=500, blank=True)
    background_image = models.ImageField(upload_to="support/hero/", null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Help Center Hero"
        verbose_name_plural = "Help Center Heroes"
        ordering = ["-is_active", "-updated_at"]

    def __str__(self):
        return self.title


class CareerCategory(BaseModel):
    """Categories for job positions."""

    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    icon = models.CharField(max_length=80, blank=True)
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "Career Categories"
        ordering = ["order", "name"]

    def __str__(self):
        return self.name


class JobPosition(BaseModel):
    """Job positions/openings."""

    JOB_TYPES = [
        ("full_time", "Full Time"),
        ("part_time", "Part Time"),
        ("contract", "Contract"),
        ("internship", "Internship"),
        ("remote", "Remote"),
    ]

    EXPERIENCE_LEVELS = [
        ("entry", "Entry Level"),
        ("junior", "Junior"),
        ("mid", "Mid Level"),
        ("senior", "Senior"),
        ("lead", "Lead"),
        ("manager", "Manager"),
        ("director", "Director"),
    ]

    title = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    category = models.ForeignKey(
        CareerCategory,
        on_delete=models.CASCADE,
        related_name="positions",
    )

    job_type = models.CharField(max_length=20, choices=JOB_TYPES, default="full_time")
    experience_level = models.CharField(max_length=20, choices=EXPERIENCE_LEVELS, default="mid")
    location = models.CharField(max_length=200)
    salary_range = models.CharField(max_length=100, blank=True)

    description = models.TextField(help_text="Brief description of the role")
    responsibilities = CKEditor5Field(help_text="Key responsibilities")
    requirements = CKEditor5Field(help_text="Required qualifications and skills")
    benefits = CKEditor5Field(blank=True, help_text="Benefits specific to this position")

    is_featured = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    publish_date = models.DateTimeField(auto_now_add=True)
    closing_date = models.DateTimeField(null=True, blank=True)

    application_email = models.EmailField(default="careers@arolana.com")
    application_url = models.URLField(blank=True)

    class Meta:
        ordering = ["-is_featured", "-publish_date"]

    def __str__(self):
        return f"{self.title} - {self.category.name}"

    def is_open(self):
        if self.closing_date:
            return self.closing_date >= timezone.now()
        return True

    def get_absolute_url(self):
        return reverse("pages:job_detail", args=[self.slug])


class JobApplication(BaseModel):
    """Track job applications."""

    STATUS_CHOICES = [
        ("pending", "Pending Review"),
        ("reviewed", "Reviewed"),
        ("interview", "Interview Stage"),
        ("rejected", "Rejected"),
        ("accepted", "Accepted"),
    ]

    position = models.ForeignKey(
        JobPosition,
        on_delete=models.CASCADE,
        related_name="applications",
    )
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(max_length=30, blank=True)
    cover_letter = models.TextField(blank=True)
    resume = models.FileField(
        upload_to="job_applications/resumes/",
        blank=True,
        null=True,
        help_text="Upload resume, PDF or DOC",
    )
    portfolio_url = models.URLField(blank=True)
    linkedin_url = models.URLField(blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    notes = models.TextField(blank=True, help_text="Internal notes")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.first_name} {self.last_name} - {self.position.title}"