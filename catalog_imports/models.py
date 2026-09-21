from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class ImportSource(TimeStampedModel):
    MODE_GENERIC = "generic"
    MODE_ADAPTER = "adapter"
    MODE_API = "api"
    MODE_CHOICES = [
        (MODE_GENERIC, "Generic structured-page extractor"),
        (MODE_ADAPTER, "Dedicated website adapter"),
        (MODE_API, "Official/API connector"),
    ]

    name = models.CharField(max_length=120, unique=True)
    domain = models.CharField(max_length=255, unique=True, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    extraction_mode = models.CharField(
        max_length=20,
        choices=MODE_CHOICES,
        default=MODE_GENERIC,
    )
    default_currency = models.CharField(max_length=3, default="NGN")
    adapter_key = models.CharField(
        max_length=120,
        blank=True,
        help_text="Registry key for a dedicated adapter when extraction_mode=adapter.",
    )
    configuration = models.JSONField(
        default=dict,
        blank=True,
        help_text="Source-specific options. Do not store secrets here.",
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class BrandVerificationProfile(TimeStampedModel):
    """Admin-configured official manufacturer identity for a brand.

    This is configuration, not extractor code, so the importer remains universal.
    """

    brand_name = models.CharField(max_length=120, unique=True, db_index=True)
    manufacturer_name = models.CharField(max_length=160, blank=True)
    official_domain = models.CharField(
        max_length=255,
        blank=True,
        help_text="Official manufacturer domain, e.g. logitech.com.",
    )
    aliases = models.JSONField(
        default=list,
        blank=True,
        help_text="Optional brand aliases/model-family tokens used for conservative matching.",
    )
    is_active = models.BooleanField(default=True, db_index=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["brand_name"]

    def __str__(self):
        return self.brand_name


class ImportPricingRule(TimeStampedModel):
    ROUND_NONE = "none"
    ROUND_100 = "100"
    ROUND_500 = "500"
    ROUND_1000 = "1000"
    ROUND_CHOICES = [
        (ROUND_NONE, "No rounding"),
        (ROUND_100, "Nearest 100"),
        (ROUND_500, "Nearest 500"),
        (ROUND_1000, "Nearest 1,000"),
    ]

    name = models.CharField(max_length=160)
    is_active = models.BooleanField(default=True, db_index=True)
    priority = models.PositiveIntegerField(
        default=100,
        help_text="Higher priority wins when multiple rules match.",
    )
    source = models.ForeignKey(
        ImportSource,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="pricing_rules",
    )
    brand_match = models.CharField(
        max_length=120,
        blank=True,
        help_text="Optional case-insensitive brand name selector.",
    )
    category_match = models.CharField(
        max_length=160,
        blank=True,
        help_text="Optional case-insensitive category/slug selector.",
    )
    product_identifier_match = models.CharField(
        max_length=160,
        blank=True,
        help_text="Optional SKU/model/name selector for one product or product family.",
    )
    fixed_markup = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    percentage_markup = models.DecimalField(
        max_digits=7,
        decimal_places=3,
        default=Decimal("0.000"),
        validators=[MinValueValidator(Decimal("0.000"))],
        help_text="Example: 12.5 means +12.5%.",
    )
    rounding_mode = models.CharField(
        max_length=10,
        choices=ROUND_CHOICES,
        default=ROUND_NONE,
    )

    class Meta:
        ordering = ["-priority", "name"]

    def __str__(self):
        return self.name


class ImportBatch(TimeStampedModel):
    MODE_URLS = "urls"
    MODE_NAMES = "names"
    MODE_MIXED = "mixed"
    INPUT_MODE_CHOICES = [
        (MODE_URLS, "Product URLs"),
        (MODE_NAMES, "Product names / model numbers"),
        (MODE_MIXED, "Mixed URLs and product names"),
    ]

    STATUS_DRAFT = "draft"
    STATUS_ANALYSING = "analysing"
    STATUS_REVIEW = "review"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_ANALYSING, "Analysing"),
        (STATUS_REVIEW, "Ready for review"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_FAILED, "Failed"),
    ]

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="catalog_import_batches",
    )
    source = models.ForeignKey(
        ImportSource,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="batches",
        help_text="Leave blank to auto-detect sources per item.",
    )
    input_mode = models.CharField(
        max_length=20,
        choices=INPUT_MODE_CHOICES,
        default=MODE_MIXED,
    )
    original_input = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_DRAFT,
        db_index=True,
    )
    pricing_rule = models.ForeignKey(
        ImportPricingRule,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="batches",
        help_text="Optional explicit rule. Otherwise the pricing engine selects the best match.",
    )
    max_images = models.PositiveSmallIntegerField(
        default=10,
        validators=[MinValueValidator(1), MaxValueValidator(10)],
    )
    verify_against_manufacturer = models.BooleanField(default=True)
    generate_or_prepare_images = models.BooleanField(default=True)
    reject_watermarked_images = models.BooleanField(default=True)
    remove_source_identity = models.BooleanField(default=True)
    require_human_approval = models.BooleanField(default=True)

    # Draft destination defaults. These belong to the importer only and do not
    # change the existing Products/Vendor flows. Individual items may override
    # them before a Product draft is prepared.
    target_vendor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="catalog_import_destination_batches",
        limit_choices_to={"user_type": "vendor"},
        help_text="Vendor that will own newly prepared Arolana product drafts.",
    )
    default_category = models.ForeignKey(
        "products.Category",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="catalog_import_default_batches",
        help_text="Optional default destination category for this batch.",
    )
    default_brand = models.ForeignKey(
        "products.Brand",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="catalog_import_default_batches",
        help_text="Optional destination brand override. Exact existing-brand matching is attempted when blank.",
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Import batch #{self.pk or 'new'}"


class ImportItem(TimeStampedModel):
    STATUS_QUEUED = "queued"
    STATUS_EXTRACTING = "extracting"
    STATUS_NORMALIZED = "normalized"
    STATUS_VERIFYING = "verifying"
    STATUS_READY = "ready"
    STATUS_DRAFT_CREATED = "draft_created"
    STATUS_BLOCKED = "blocked"
    STATUS_IMPORTED = "imported"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_QUEUED, "Queued"),
        (STATUS_EXTRACTING, "Extracting"),
        (STATUS_NORMALIZED, "Normalized"),
        (STATUS_VERIFYING, "Verifying"),
        (STATUS_READY, "Ready for review"),
        (STATUS_DRAFT_CREATED, "Arolana draft created"),
        (STATUS_BLOCKED, "Blocked by quality checks"),
        (STATUS_IMPORTED, "Imported"),
        (STATUS_FAILED, "Failed"),
    ]

    batch = models.ForeignKey(
        ImportBatch,
        on_delete=models.CASCADE,
        related_name="items",
    )
    input_value = models.TextField(
        help_text="Original URL, product name, model number, or identifier supplied by the admin.",
    )
    source = models.ForeignKey(
        ImportSource,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="items",
    )
    source_url = models.URLField(max_length=1000, blank=True)
    source_external_id = models.CharField(max_length=255, blank=True, db_index=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_QUEUED,
        db_index=True,
    )

    raw_payload = models.JSONField(default=dict, blank=True)
    normalized_payload = models.JSONField(default=dict, blank=True)
    verification_report = models.JSONField(default=dict, blank=True)
    contamination_report = models.JSONField(default=dict, blank=True)
    image_report = models.JSONField(default=dict, blank=True)
    duplicate_report = models.JSONField(default=dict, blank=True)

    source_price = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
    )
    source_currency = models.CharField(max_length=3, blank=True)
    pricing_rule = models.ForeignKey(
        ImportPricingRule,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="items",
    )
    calculated_price = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
    )

    manufacturer_url = models.URLField(
        max_length=1000,
        blank=True,
        help_text=(
            "Optional official manufacturer product URL used as authoritative identity/spec evidence. "
            "It never replaces the retailer price."
        ),
    )
    secondary_evidence_urls = models.TextField(
        blank=True,
        help_text="Optional one evidence URL per line. Used only as supporting evidence.",
    )
    manual_verified_source_price = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=(
            "Optional price manually verified by an admin when the retailer page cannot be fetched. "
            "Requires a price evidence URL before it is accepted."
        ),
    )
    manual_price_evidence_url = models.URLField(
        max_length=1000,
        blank=True,
        help_text="URL where the manually entered current source price was verified.",
    )
    identity_verified = models.BooleanField(default=False, db_index=True)
    specifications_verified = models.BooleanField(default=False, db_index=True)
    price_verified = models.BooleanField(default=False, db_index=True)
    hold_reason = models.CharField(max_length=120, blank=True, db_index=True)

    # Per-item destination overrides used only when preparing the final Arolana
    # draft. They never alter the existing manual Add Product or vendor flows.
    target_vendor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="catalog_import_destination_items",
        limit_choices_to={"user_type": "vendor"},
    )
    target_category = models.ForeignKey(
        "products.Category",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="catalog_import_destination_items",
    )
    target_brand = models.ForeignKey(
        "products.Brand",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="catalog_import_destination_items",
    )
    existing_product_match = models.ForeignKey(
        "products.Product",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="catalog_import_duplicate_matches",
        help_text="Exact/strong existing-product match detected before draft creation.",
    )
    draft_preparation_report = models.JSONField(default=dict, blank=True)
    draft_prepared_at = models.DateTimeField(null=True, blank=True)
    media_plan_prepared_at = models.DateTimeField(null=True, blank=True)

    created_product = models.ForeignKey(
        "products.Product",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="catalog_import_items",
    )
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ["id"]
        indexes = [
            models.Index(fields=["batch", "status"]),
            models.Index(fields=["source", "source_external_id"]),
        ]

    def __str__(self):
        return self.input_value[:120]


class ImportEvidence(TimeStampedModel):
    ROLE_RETAILER = "retailer"
    ROLE_MANUFACTURER = "manufacturer"
    ROLE_SECONDARY = "secondary"
    ROLE_MANUAL_PRICE = "manual_price"
    ROLE_CHOICES = [
        (ROLE_RETAILER, "Retailer/source evidence"),
        (ROLE_MANUFACTURER, "Official manufacturer evidence"),
        (ROLE_SECONDARY, "Secondary supporting evidence"),
        (ROLE_MANUAL_PRICE, "Manual price evidence"),
    ]

    STATUS_QUEUED = "queued"
    STATUS_FETCHED = "fetched"
    STATUS_BLOCKED = "blocked"
    STATUS_FAILED = "failed"
    STATUS_MANUAL = "manual"
    STATUS_CHOICES = [
        (STATUS_QUEUED, "Queued"),
        (STATUS_FETCHED, "Fetched"),
        (STATUS_BLOCKED, "Blocked"),
        (STATUS_FAILED, "Failed"),
        (STATUS_MANUAL, "Manually verified"),
    ]

    item = models.ForeignKey(
        ImportItem,
        on_delete=models.CASCADE,
        related_name="evidence_records",
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, db_index=True)
    url = models.URLField(max_length=1000, blank=True)
    source_name = models.CharField(max_length=160, blank=True)
    is_authoritative = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_QUEUED, db_index=True)
    http_status = models.PositiveIntegerField(null=True, blank=True)
    extracted_payload = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["role", "id"]
        indexes = [models.Index(fields=["item", "role", "status"])]

    def __str__(self):
        return f"{self.get_role_display()} for item #{self.item_id}"


class ImportCategoryMapping(TimeStampedModel):
    """Configurable source-category -> Arolana category mapping.

    The matching data lives in the database rather than source-specific code,
    which keeps the importer universal.
    """

    source = models.ForeignKey(
        ImportSource,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="category_mappings",
    )
    source_category_match = models.CharField(max_length=180, blank=True)
    source_subcategory_match = models.CharField(max_length=180, blank=True)
    target_category = models.ForeignKey(
        "products.Category",
        on_delete=models.CASCADE,
        related_name="catalog_import_mappings",
    )
    priority = models.PositiveIntegerField(default=100)
    is_active = models.BooleanField(default=True, db_index=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-priority", "id"]

    def __str__(self):
        label = self.source_category_match or self.source_subcategory_match or "*"
        return f"{label} -> {self.target_category}"


class ImportMediaCandidate(TimeStampedModel):
    KIND_REFERENCE = "reference"
    KIND_GENERATION = "generation"
    KIND_OWNED_UPLOAD = "owned_upload"
    KIND_PREPARED = "prepared"
    KIND_CHOICES = [
        (KIND_REFERENCE, "Reference only"),
        (KIND_GENERATION, "Generation job"),
        (KIND_OWNED_UPLOAD, "Arolana-owned upload"),
        (KIND_PREPARED, "Prepared/generated result"),
    ]

    STATUS_PLANNED = "planned"
    STATUS_GENERATING = "generating"
    STATUS_REFERENCE = "reference"
    STATUS_READY_REVIEW = "ready_review"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_ATTACHED = "attached"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_PLANNED, "Planned / waiting for image provider"),
        (STATUS_GENERATING, "Generating"),
        (STATUS_REFERENCE, "Reference only"),
        (STATUS_READY_REVIEW, "Ready for review"),
        (STATUS_APPROVED, "Approved for product"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_ATTACHED, "Attached to product"),
        (STATUS_FAILED, "Generation failed"),
    ]

    VIEW_MAIN = "main"
    VIEW_FRONT = "front"
    VIEW_LEFT = "left_angle"
    VIEW_RIGHT = "right_angle"
    VIEW_SIDE = "side"
    VIEW_BACK = "back"
    VIEW_TOP = "top_detail"
    VIEW_PORTS = "ports_detail"
    VIEW_PACKAGE = "package_contents"
    VIEW_LIFESTYLE = "lifestyle"
    VIEW_CLOSEUP = "closeup"
    VIEW_CHOICES = [
        (VIEW_MAIN, "Main / hero"),
        (VIEW_FRONT, "Front"),
        (VIEW_LEFT, "Left angle"),
        (VIEW_RIGHT, "Right angle"),
        (VIEW_SIDE, "Side"),
        (VIEW_BACK, "Back"),
        (VIEW_TOP, "Top / detail"),
        (VIEW_PORTS, "Ports / controls detail"),
        (VIEW_PACKAGE, "Package / contents"),
        (VIEW_LIFESTYLE, "Lifestyle"),
        (VIEW_CLOSEUP, "Close-up"),
    ]

    WATERMARK_UNKNOWN = "unknown"
    WATERMARK_CLEAR = "clear"
    WATERMARK_DETECTED = "detected"
    WATERMARK_CHOICES = [
        (WATERMARK_UNKNOWN, "Not checked"),
        (WATERMARK_CLEAR, "No watermark detected"),
        (WATERMARK_DETECTED, "Watermark detected"),
    ]

    RIGHTS_UNKNOWN = "unknown"
    RIGHTS_CONFIRMED = "confirmed"
    RIGHTS_REJECTED = "rejected"
    RIGHTS_CHOICES = [
        (RIGHTS_UNKNOWN, "Not confirmed"),
        (RIGHTS_CONFIRMED, "Usage rights confirmed"),
        (RIGHTS_REJECTED, "Do not use"),
    ]

    item = models.ForeignKey(
        ImportItem,
        on_delete=models.CASCADE,
        related_name="media_candidates",
    )
    kind = models.CharField(max_length=30, choices=KIND_CHOICES, db_index=True)
    view_role = models.CharField(max_length=40, choices=VIEW_CHOICES, blank=True, db_index=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_PLANNED, db_index=True)
    order = models.PositiveSmallIntegerField(default=0)

    source_url = models.URLField(max_length=1500, blank=True)
    # Candidate bytes intentionally remain outside model FileField/ImageField.
    # Review-stage assets are stored behind a configurable Django storage alias
    # and referenced only by alias/key until a human approves them. This keeps
    # catalog_imports compatible with Arolana's private-upload classification.
    asset_storage_alias = models.CharField(
        max_length=80,
        blank=True,
        help_text="Django storage alias containing a review-stage asset.",
    )
    asset_storage_name = models.CharField(
        max_length=1000,
        blank=True,
        help_text="Storage object/key for a review-stage asset. Not a public URL.",
    )
    asset_original_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Generated filename used to preserve the extension.",
    )
    reference_urls = models.JSONField(default=list, blank=True)
    generation_prompt = models.TextField(blank=True)
    provider_key = models.CharField(max_length=80, blank=True)
    provider_asset_id = models.CharField(max_length=255, blank=True)
    provider_response = models.JSONField(default=dict, blank=True)
    generation_attempts = models.PositiveSmallIntegerField(default=0)
    mime_type = models.CharField(max_length=120, blank=True)
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    file_size = models.PositiveBigIntegerField(null=True, blank=True)
    sha256 = models.CharField(max_length=64, blank=True, db_index=True)
    generated_at = models.DateTimeField(null=True, blank=True)

    exact_identity_required = models.BooleanField(default=True)
    exact_identity_verified = models.BooleanField(default=False)
    source_identity_check_passed = models.BooleanField(
        default=False,
        help_text="Human confirmed no retailer/source identity, watermark-like source branding, or copied seller overlay is present.",
    )
    watermark_status = models.CharField(
        max_length=20, choices=WATERMARK_CHOICES, default=WATERMARK_UNKNOWN
    )
    rights_status = models.CharField(max_length=20, choices=RIGHTS_CHOICES, default=RIGHTS_UNKNOWN)
    selected_for_product = models.BooleanField(default=False)

    reviewed_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_catalog_import_media",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rejected_catalog_import_media",
    )
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
    last_error = models.TextField(blank=True)

    attached_product_image = models.ForeignKey(
        "products.ProductImage",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="catalog_import_media_candidates",
    )
    attached_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["order", "id"]
        indexes = [
            models.Index(fields=["item", "kind", "status"]),
            models.Index(fields=["item", "sha256"]),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} / {self.get_view_role_display() or 'media'} for item #{self.item_id}"


class ImportAuditEvent(TimeStampedModel):
    item = models.ForeignKey(
        ImportItem,
        on_delete=models.CASCADE,
        related_name="audit_events",
    )
    event_type = models.CharField(max_length=80, db_index=True)
    message = models.CharField(max_length=500, blank=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.item_id}: {self.event_type}"
