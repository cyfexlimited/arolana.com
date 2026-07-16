from __future__ import annotations

from django import forms
from django.core.exceptions import ValidationError as DjangoValidationError

from products.models import Product
from core.html_sanitization import normalize_rich_text_input

from .models import (
    ProviderService,
    ServiceCategory,
    ServicePortfolio,
    ServiceProjectMedia,
    ServiceProjectProduct,
    ServiceProviderProfile,
    ServiceQuoteRequest,
    ServiceReview,
    validate_project_external_video_url,
)


INPUT_CLASS = (
    "w-full rounded-xl border border-slate-200 bg-white "
    "px-4 py-3 outline-none focus:border-blue-500 "
    "focus:ring-4 focus:ring-blue-100"
)


# =============================================================================
# BASE STYLED FORM
# =============================================================================


class StyledModelForm(forms.ModelForm):
    """
    Shared styled ModelForm for the installer/service marketplace.
    """

    def __init__(
        self,
        *args,
        **kwargs,
    ):
        super().__init__(
            *args,
            **kwargs,
        )

        for field in self.fields.values():
            existing = field.widget.attrs.get(
                "class",
                "",
            )

            field.widget.attrs["class"] = (
                f"{existing} {INPUT_CLASS}"
            ).strip()


# =============================================================================
# PROVIDER REGISTRATION
# =============================================================================


class ProviderRegistrationForm(
    StyledModelForm
):
    """
    Service-provider onboarding form.

    Sensitive KYC uploads are validated through the validators attached to:

    - government_id_upload
    - cac_certificate_upload
    """

    class Meta:
        model = ServiceProviderProfile

        fields = [
            "business_name",
            "contact_person",
            "provider_type",
            "phone_number",
            "whatsapp_number",
            "email",
            "website",
            "country",
            "state",
            "city",
            "address",
            "service_coverage",
            "description",
            "years_of_experience",
            "cac_number",
            "government_id_upload",
            "cac_certificate_upload",
            "profile_image",
            "business_logo",
            "business_banner",
            "preferred_language",
            "support_phone",
            "support_email",
            "support_whatsapp",
            "business_hours",
            "availability_note",
        ]

        widgets = {
            "description": forms.Textarea(
                attrs={
                    "rows": 5,
                }
            ),
            "address": forms.Textarea(
                attrs={
                    "rows": 3,
                }
            ),
            "service_coverage": forms.Textarea(
                attrs={
                    "rows": 3,
                }
            ),
            "business_hours": forms.Textarea(
                attrs={
                    "rows": 3,
                }
            ),
        }

    def clean(self):
        cleaned_data = super().clean()

        government_id = cleaned_data.get(
            "government_id_upload"
        )

        cac_certificate = cleaned_data.get(
            "cac_certificate_upload"
        )

        cac_number = (
            cleaned_data.get(
                "cac_number"
            )
            or ""
        ).strip()

        if (
            cac_certificate
            and not cac_number
        ):
            self.add_error(
                "cac_number",
                (
                    "Enter the CAC or business registration "
                    "number associated with the uploaded certificate."
                ),
            )

        return cleaned_data


# =============================================================================
# PROVIDER WORKSPACE PROFILE
# =============================================================================


class ProviderWorkspaceProfileForm(
    StyledModelForm
):
    """
    Provider-owned public profile editor.

    KYC and sensitive verification files are intentionally excluded.
    Those changes should use the protected approval workflow.
    """

    class Meta:
        model = ServiceProviderProfile

        fields = [
            "business_name",
            "contact_person",
            "provider_type",
            "phone_number",
            "whatsapp_number",
            "email",
            "website",
            "country",
            "state",
            "city",
            "address",
            "service_coverage",
            "description",
            "years_of_experience",
            "support_phone",
            "support_email",
            "support_whatsapp",
        ]

        widgets = {
            "description": forms.Textarea(
                attrs={
                    "rows": 6,
                }
            ),
            "address": forms.Textarea(
                attrs={
                    "rows": 3,
                }
            ),
            "service_coverage": forms.Textarea(
                attrs={
                    "rows": 3,
                }
            ),
        }


# =============================================================================
# PROVIDER AVAILABILITY
# =============================================================================


class ProviderAvailabilityForm(
    StyledModelForm
):
    class Meta:
        model = ServiceProviderProfile

        fields = [
            "availability_status",
            "availability_note",
            "business_hours",
            "business_hours_data",
        ]

        widgets = {
            "business_hours": forms.Textarea(
                attrs={
                    "rows": 3,
                }
            ),
            "business_hours_data": forms.Textarea(
                attrs={
                    "rows": 8,
                    "placeholder": (
                        '{"monday": {'
                        '"enabled": true, '
                        '"open": "09:00", '
                        '"close": "17:00"'
                        "}}"
                    ),
                }
            ),
        }


# =============================================================================
# PROVIDER SETTINGS
# =============================================================================


class ProviderWorkspaceSettingsForm(
    StyledModelForm
):
    notify_in_app = forms.BooleanField(
        required=False,
        initial=True,
    )

    notify_email = forms.BooleanField(
        required=False,
        initial=True,
    )

    notify_push = forms.BooleanField(
        required=False,
        initial=True,
    )

    notify_new_jobs = forms.BooleanField(
        required=False,
        initial=True,
    )

    notify_quotes = forms.BooleanField(
        required=False,
        initial=True,
    )

    notify_reviews = forms.BooleanField(
        required=False,
        initial=True,
    )

    bank_name = forms.CharField(
        required=False,
    )

    account_name = forms.CharField(
        required=False,
    )

    account_number = forms.CharField(
        required=False,
    )

    class Meta:
        model = ServiceProviderProfile

        fields = [
            "preferred_language",
            "support_phone",
            "support_email",
            "support_whatsapp",
        ]

    def __init__(
        self,
        *args,
        **kwargs,
    ):
        super().__init__(
            *args,
            **kwargs,
        )

        if (
            not self.instance
            or not self.instance.pk
        ):
            return

        preferences = (
            self.instance.notification_preferences
            or {}
        )

        for key in (
            "in_app",
            "email",
            "push",
            "new_jobs",
            "quotes",
            "reviews",
        ):
            self.fields[
                f"notify_{key}"
            ].initial = preferences.get(
                key,
                True,
            )

        bank = (
            self.instance.bank_details
            or {}
        )

        for key in (
            "bank_name",
            "account_name",
            "account_number",
        ):
            self.fields[
                key
            ].initial = bank.get(
                key,
                "",
            )

    def save(
        self,
        commit=True,
    ):
        instance = super().save(
            commit=False
        )

        instance.notification_preferences = {
            key: bool(
                self.cleaned_data.get(
                    f"notify_{key}"
                )
            )
            for key in (
                "in_app",
                "email",
                "push",
                "new_jobs",
                "quotes",
                "reviews",
            )
        }

        bank_details = {}

        for key in (
            "bank_name",
            "account_name",
            "account_number",
        ):
            value = (
                self.cleaned_data.get(
                    key
                )
                or ""
            ).strip()

            if value:
                bank_details[key] = value

        instance.bank_details = (
            bank_details
        )

        if commit:
            instance.save()

        return instance


# =============================================================================
# PROVIDER SERVICE
# =============================================================================


class ProviderServiceForm(
    StyledModelForm
):
    class Meta:
        model = ProviderService
        fields = [
            "category",
            "service_name",
            "short_description",
            "description",
            "starting_price",
            "is_active",
        ]
        help_texts = {
            "short_description": "Up to 240 characters for profile and marketplace cards.",
            "description": (
                "Explain what is included, the systems or brands you support, the customer "
                "types you serve, and what customers should expect."
            ),
            "starting_price": (
                "Enter the minimum professional fee. Customers can still request a custom quote."
            ),
        }
        labels = {
            "service_name": "Service name",
            "short_description": "Service summary",
            "description": "Full service description",
            "starting_price": "Starting price",
            "is_active": "Active and visible to customers",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = ServiceCategory.objects.filter(is_active=True).order_by("name")
        self.fields["service_name"].widget.attrs.setdefault(
            "placeholder", "Conference Room Design, Installation & Integration"
        )
        self.fields["short_description"].widget.attrs.setdefault(
            "placeholder", "A concise summary customers can scan on service cards"
        )
        self.fields["description"].widget.attrs.setdefault("data-min-height", "280")

    def clean_service_name(self):
        value = " ".join((self.cleaned_data.get("service_name") or "").split())
        if len(value) < 3:
            raise forms.ValidationError("Enter a clear service name of at least 3 characters.")
        return value

    def clean_short_description(self):
        return " ".join((self.cleaned_data.get("short_description") or "").split())

    def clean_description(self):
        value = normalize_rich_text_input(self.cleaned_data.get("description"))
        if len(value) > 20000:
            raise forms.ValidationError("Keep the full service description under 20,000 characters.")
        return value


# =============================================================================
# SERVICE PORTFOLIO
# =============================================================================


class ServicePortfolioForm(
    StyledModelForm
):
    services_performed = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={
                "rows": 3,
                "placeholder": (
                    "Installation, configuration, testing"
                ),
            }
        ),
    )

    technologies_used = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={
                "rows": 3,
                "placeholder": (
                    "Video conferencing, networking, "
                    "control system"
                ),
            }
        ),
    )

    products_used = (
        forms.ModelMultipleChoiceField(
            queryset=Product.objects.none(),
            required=False,
            help_text=(
                "Select approved Arolana products "
                "used in this project."
            ),
        )
    )

    class Meta:
        model = ServicePortfolio

        fields = [
            "title",
            "short_summary",
            "project_type",
            "service_category",
            "completed_at",
            "country",
            "state",
            "city",
            "location_display",
            "project_duration_text",
            "description",
            "challenge",
            "solution",
            "implementation_process",
            "project_result",
            "customer_outcome",
            "services_performed",
            "technologies_used",
            "customer_type",
            "customer_name_display",
            "customer_consent_to_publish",
            "project_value_min",
            "project_value_max",
            "project_value_currency",
            "show_project_value",
            "products_used",
        ]

        widgets = {
            "description": forms.Textarea(
                attrs={
                    "rows": 5,
                }
            ),
            "challenge": forms.Textarea(
                attrs={
                    "rows": 4,
                }
            ),
            "solution": forms.Textarea(
                attrs={
                    "rows": 4,
                }
            ),
            "implementation_process": (
                forms.Textarea(
                    attrs={
                        "rows": 5,
                    }
                )
            ),
            "project_result": forms.Textarea(
                attrs={
                    "rows": 4,
                }
            ),
            "customer_outcome": forms.Textarea(
                attrs={
                    "rows": 4,
                }
            ),
            "completed_at": forms.DateInput(
                attrs={
                    "type": "date",
                }
            ),
        }

    def __init__(
        self,
        *args,
        **kwargs,
    ):
        super().__init__(
            *args,
            **kwargs,
        )

        self.fields[
            "products_used"
        ].queryset = (
            Product.objects
            .filter(
                is_active=True,
                approval_status="approved",
            )
            .select_related(
                "brand",
                "category",
            )
            .prefetch_related(
                "variants",
                "images",
            )
            .order_by(
                "name"
            )
        )

        if (
            self.instance
            and self.instance.pk
        ):
            self.fields[
                "products_used"
            ].initial = (
                self.instance
                .project_products
                .values_list(
                    "product_id",
                    flat=True,
                )
            )

        for json_field in (
            "services_performed",
            "technologies_used",
        ):
            value = self.initial.get(
                json_field
            )

            if (
                not value
                and self.instance
                and self.instance.pk
            ):
                value = getattr(
                    self.instance,
                    json_field,
                    [],
                )

            if isinstance(
                value,
                list,
            ):
                self.initial[
                    json_field
                ] = ", ".join(
                    str(item)
                    for item in value
                )

    def clean(self):
        cleaned = super().clean()

        title = (
            cleaned.get(
                "title"
            )
            or ""
        ).strip()

        if len(title) < 8:
            self.add_error(
                "title",
                (
                    "Use a descriptive project title "
                    "of at least 8 characters."
                ),
            )

        for json_field in (
            "services_performed",
            "technologies_used",
        ):
            value = cleaned.get(
                json_field
            )

            if isinstance(
                value,
                str,
            ):
                cleaned[
                    json_field
                ] = [
                    item.strip()
                    for item
                    in value.replace(
                        "\n",
                        ",",
                    ).split(
                        ","
                    )
                    if item.strip()
                ]

        min_value = cleaned.get(
            "project_value_min"
        )

        max_value = cleaned.get(
            "project_value_max"
        )

        if (
            min_value is not None
            and max_value is not None
            and min_value > max_value
        ):
            self.add_error(
                "project_value_max",
                (
                    "Maximum project value cannot be "
                    "less than minimum project value."
                ),
            )

        return cleaned

    def save(
        self,
        commit=True,
    ):
        project = super().save(
            commit=commit
        )

        if commit:
            products = list(
                self.cleaned_data.get(
                    "products_used",
                    [],
                )
            )

            product_ids = [
                product.pk
                for product in products
            ]

            project.project_products.exclude(
                product_id__in=product_ids
            ).delete()

            existing = set(
                project.project_products
                .values_list(
                    "product_id",
                    flat=True,
                )
            )

            new_links = []

            for index, product in enumerate(
                products
            ):
                if product.pk in existing:
                    continue

                new_links.append(
                    ServiceProjectProduct(
                        project=project,
                        product=product,
                        display_order=index,
                    )
                )

            if new_links:
                ServiceProjectProduct.objects.bulk_create(
                    new_links
                )

        return project


# =============================================================================
# PROJECT MEDIA
# =============================================================================


class ServiceProjectMediaForm(
    StyledModelForm
):
    class Meta:
        model = ServiceProjectMedia

        fields = [
            "media_type",
            "stage",
            "image",
            "video",
            "document",
            "external_video_url",
            "thumbnail",
            "caption",
            "alt_text",
            "display_order",
            "is_featured",
            "is_cover",
        ]

    def clean(self):
        cleaned = super().clean()

        media_type = cleaned.get(
            "media_type"
        )

        image = cleaned.get(
            "image"
        )

        video = cleaned.get(
            "video"
        )

        document = cleaned.get(
            "document"
        )

        external_video_url = (
            cleaned.get(
                "external_video_url"
            )
            or ""
        ).strip()

        if external_video_url:
            try:
                cleaned["external_video_url"] = (
                    validate_project_external_video_url(external_video_url)
                )
            except DjangoValidationError as exc:
                self.add_error("external_video_url", exc)

        if video and external_video_url:
            self.add_error(
                "external_video_url",
                "Use either a local video or an external video URL, not both.",
            )

        if (
            media_type == ServiceProjectMedia.TYPE_IMAGE
            and not image
            and not (
                self.instance
                and self.instance.pk
                and self.instance.image
            )
        ):
            self.add_error(
                "image",
                (
                    "Upload an image for the selected "
                    "media type."
                ),
            )

        if (
            media_type == ServiceProjectMedia.TYPE_DOCUMENT
            and not document
            and not (
                self.instance
                and self.instance.pk
                and self.instance.document
            )
        ):
            self.add_error(
                "document",
                "Upload a document for document media.",
            )

        if (
            media_type == "video"
            and not video
            and not external_video_url
            and not (
                self.instance
                and self.instance.pk
                and self.instance.video
            )
        ):
            self.add_error(
                "video",
                (
                    "Upload a video or provide an external "
                    "video URL."
                ),
            )

        return cleaned


class MultipleProjectMediaInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleProjectMediaField(forms.FileField):
    def clean(self, data, initial=None):
        single_clean = super().clean
        if not data:
            return []
        files = data if isinstance(data, (list, tuple)) else [data]
        return [single_clean(item, initial) for item in files]


class ServiceProjectBulkMediaForm(forms.Form):
    files = MultipleProjectMediaField(
        required=False,
        widget=MultipleProjectMediaInput(
            attrs={
                "accept": (
                    "image/jpeg,image/png,image/webp,image/avif,image/gif,"
                    "video/mp4,video/quicktime,video/webm,video/x-m4v,"
                    "application/pdf,application/vnd.openxmlformats-"
                    "officedocument.wordprocessingml.document"
                ),
            }
        ),
        help_text="Select several images, videos, or supporting documents at once.",
    )
    stage = forms.ChoiceField(
        choices=ServiceProjectMedia.STAGE_CHOICES,
        initial=ServiceProjectMedia.STAGE_GENERAL,
    )
    caption = forms.CharField(max_length=300, required=False)
    alt_text = forms.CharField(max_length=220, required=False)
    external_video_url = forms.URLField(required=False)
    thumbnail = forms.ImageField(required=False)
    make_first_image_cover = forms.BooleanField(required=False, initial=False)
    mark_featured = forms.BooleanField(
        required=False,
        initial=False,
        label="Feature uploaded media",
    )
    display_order_start = forms.IntegerField(
        required=False,
        min_value=0,
        label="Starting display order",
        help_text="Leave blank to add these files after the current gallery.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            existing = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing} {INPUT_CLASS}".strip()

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("files") and not cleaned.get("external_video_url"):
            raise forms.ValidationError("Select one or more files, or add a supported video URL.")
        if cleaned.get("external_video_url") and cleaned.get("stage") == ServiceProjectMedia.STAGE_SUPPORTING_DOCUMENT:
            self.add_error("stage", "An external video cannot use the supporting document stage.")
        external_video_url = (cleaned.get("external_video_url") or "").strip()
        if external_video_url:
            try:
                cleaned["external_video_url"] = (
                    validate_project_external_video_url(external_video_url)
                )
            except DjangoValidationError as exc:
                self.add_error("external_video_url", exc)
        return cleaned


# =============================================================================
# SERVICE QUOTE REQUEST
# =============================================================================


class ServiceQuoteRequestForm(
    StyledModelForm
):
    class Meta:
        model = ServiceQuoteRequest

        fields = [
            "provider",
            "category",
            "product",
            "source_project",
            "name",
            "phone",
            "whatsapp",
            "email",
            "state",
            "city",
            "address",
            "service_needed",
            "message",
            "preferred_date",
            "preferred_time",
            "budget",
            "contact_preference",
            "urgency",
        ]

        widgets = {
            "source_project": (
                forms.HiddenInput()
            ),
            "address": forms.Textarea(
                attrs={
                    "rows": 3,
                }
            ),
            "message": forms.Textarea(
                attrs={
                    "rows": 5,
                }
            ),
            "preferred_date": forms.DateInput(
                attrs={
                    "type": "date",
                }
            ),
            "preferred_time": forms.TimeInput(
                attrs={
                    "type": "time",
                }
            ),
        }

    def __init__(
        self,
        *args,
        **kwargs,
    ):
        super().__init__(
            *args,
            **kwargs,
        )

        self.fields[
            "provider"
        ].queryset = (
            ServiceProviderProfile
            .objects
            .public()
        )

        self.fields[
            "provider"
        ].required = False

        self.fields[
            "category"
        ].required = False

        self.fields[
            "product"
        ].required = False

        self.fields[
            "source_project"
        ].queryset = (
            ServicePortfolio
            .objects
            .public()
        )

        self.fields[
            "source_project"
        ].required = False


# =============================================================================
# SERVICE REVIEW
# =============================================================================


class ServiceReviewForm(
    StyledModelForm
):
    class Meta:
        model = ServiceReview

        fields = [
            "rating",
            "professionalism_rating",
            "communication_rating",
            "quality_rating",
            "timeliness_rating",
            "comment",
        ]

        widgets = {
            "rating": forms.Select(
                choices=[
                    (
                        value,
                        (
                            f"{value} "
                            f"star{'s' if value != 1 else ''}"
                        ),
                    )
                    for value
                    in range(
                        5,
                        0,
                        -1,
                    )
                ]
            ),
            "professionalism_rating": (
                forms.Select(
                    choices=[
                        (
                            value,
                            value,
                        )
                        for value
                        in range(
                            5,
                            0,
                            -1,
                        )
                    ]
                )
            ),
            "communication_rating": (
                forms.Select(
                    choices=[
                        (
                            value,
                            value,
                        )
                        for value
                        in range(
                            5,
                            0,
                            -1,
                        )
                    ]
                )
            ),
            "quality_rating": forms.Select(
                choices=[
                    (
                        value,
                        value,
                    )
                    for value
                    in range(
                        5,
                        0,
                        -1,
                    )
                ]
            ),
            "timeliness_rating": (
                forms.Select(
                    choices=[
                        (
                            value,
                            value,
                        )
                        for value
                        in range(
                            5,
                            0,
                            -1,
                        )
                    ]
                )
            ),
            "comment": forms.Textarea(
                attrs={
                    "rows": 5,
                }
            ),
        }

    def clean_comment(self):
        comment = (
            self.cleaned_data.get(
                "comment"
            )
            or ""
        ).strip()

        if len(comment) < 10:
            raise forms.ValidationError(
                (
                    "Please write a review of at least "
                    "10 characters."
                )
            )

        return comment
