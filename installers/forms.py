from django import forms
from products.models import Product

from .models import (
    ProviderService,
    ServicePortfolio,
    ServiceProjectMedia,
    ServiceProjectProduct,
    ServiceProviderProfile,
    ServiceQuoteRequest,
    ServiceReview,
)


INPUT_CLASS = "w-full rounded-xl border border-slate-200 bg-white px-4 py-3 outline-none focus:border-blue-500 focus:ring-4 focus:ring-blue-100"


class StyledModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            existing = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing} {INPUT_CLASS}".strip()


class ProviderRegistrationForm(StyledModelForm):
    class Meta:
        model = ServiceProviderProfile
        fields = [
            "business_name", "contact_person", "provider_type", "phone_number",
            "whatsapp_number", "email", "website", "country", "state", "city",
            "address", "service_coverage", "description", "years_of_experience",
            "cac_number", "government_id_upload", "cac_certificate_upload",
            "profile_image", "business_logo", "business_banner",
            "preferred_language", "support_phone", "support_email", "support_whatsapp",
            "business_hours", "availability_note",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 5}),
            "address": forms.Textarea(attrs={"rows": 3}),
        }


class ProviderWorkspaceProfileForm(StyledModelForm):
    """Provider-owned profile editor that feeds the existing approval service."""

    class Meta:
        model = ServiceProviderProfile
        fields = [
            "business_name", "contact_person", "provider_type", "phone_number",
            "whatsapp_number", "email", "website", "country", "state", "city",
            "address", "service_coverage", "description", "years_of_experience",
            "support_phone", "support_email", "support_whatsapp",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 6}),
            "address": forms.Textarea(attrs={"rows": 3}),
            "service_coverage": forms.Textarea(attrs={"rows": 3}),
        }


class ProviderAvailabilityForm(StyledModelForm):
    class Meta:
        model = ServiceProviderProfile
        fields = [
            "availability_status", "availability_note", "business_hours",
            "business_hours_data",
        ]
        widgets = {
            "business_hours": forms.Textarea(attrs={"rows": 3}),
            "business_hours_data": forms.Textarea(
                attrs={
                    "rows": 8,
                    "placeholder": '{"monday": {"enabled": true, "open": "09:00", "close": "17:00"}}',
                }
            ),
        }


class ProviderWorkspaceSettingsForm(StyledModelForm):
    notify_in_app = forms.BooleanField(required=False, initial=True)
    notify_email = forms.BooleanField(required=False, initial=True)
    notify_push = forms.BooleanField(required=False, initial=True)
    notify_new_jobs = forms.BooleanField(required=False, initial=True)
    notify_quotes = forms.BooleanField(required=False, initial=True)
    notify_reviews = forms.BooleanField(required=False, initial=True)
    bank_name = forms.CharField(required=False)
    account_name = forms.CharField(required=False)
    account_number = forms.CharField(required=False)

    class Meta:
        model = ServiceProviderProfile
        fields = [
            "preferred_language", "support_phone", "support_email",
            "support_whatsapp",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance or not self.instance.pk:
            return
        preferences = self.instance.notification_preferences or {}
        for key in (
            "in_app", "email", "push", "new_jobs", "quotes", "reviews",
        ):
            self.fields[f"notify_{key}"].initial = preferences.get(key, True)
        bank = self.instance.bank_details or {}
        for key in ("bank_name", "account_name", "account_number"):
            self.fields[key].initial = bank.get(key, "")

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.notification_preferences = {
            key: bool(self.cleaned_data.get(f"notify_{key}"))
            for key in ("in_app", "email", "push", "new_jobs", "quotes", "reviews")
        }
        instance.bank_details = {
            key: (self.cleaned_data.get(key) or "").strip()
            for key in ("bank_name", "account_name", "account_number")
            if (self.cleaned_data.get(key) or "").strip()
        }
        if commit:
            instance.save()
        return instance


class ProviderServiceForm(StyledModelForm):
    class Meta:
        model = ProviderService
        fields = ["category", "service_name", "description", "starting_price", "is_active"]
        widgets = {"description": forms.Textarea(attrs={"rows": 4})}


class ServicePortfolioForm(StyledModelForm):
    services_performed = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Installation, configuration, testing"}),
    )
    technologies_used = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Video conferencing, networking, control system"}),
    )
    products_used = forms.ModelMultipleChoiceField(
        queryset=Product.objects.none(),
        required=False,
        help_text="Select approved Arolana products used in this project.",
    )

    class Meta:
        model = ServicePortfolio
        fields = [
            "title", "short_summary", "project_type", "service_category", "completed_at",
            "country", "state", "city", "location_display", "project_duration_text",
            "description", "challenge", "solution", "implementation_process",
            "project_result", "customer_outcome", "services_performed", "technologies_used",
            "customer_type", "customer_name_display", "customer_consent_to_publish",
            "project_value_min", "project_value_max", "project_value_currency",
            "show_project_value", "image", "video_source", "video_url", "local_video",
            "video_thumbnail", "video_duration",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 5}),
            "challenge": forms.Textarea(attrs={"rows": 4}),
            "solution": forms.Textarea(attrs={"rows": 4}),
            "implementation_process": forms.Textarea(attrs={"rows": 5}),
            "project_result": forms.Textarea(attrs={"rows": 4}),
            "customer_outcome": forms.Textarea(attrs={"rows": 4}),
            "completed_at": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["products_used"].queryset = Product.objects.filter(
            is_active=True,
            approval_status="approved",
        ).order_by("name")
        if self.instance and self.instance.pk:
            self.fields["products_used"].initial = self.instance.project_products.values_list("product_id", flat=True)
        for json_field in ("services_performed", "technologies_used"):
            value = self.initial.get(json_field)
            if not value and self.instance and self.instance.pk:
                value = getattr(self.instance, json_field, [])
            if isinstance(value, list):
                self.initial[json_field] = ", ".join(str(item) for item in value)

    def clean(self):
        cleaned = super().clean()
        if len((cleaned.get("title") or "").strip()) < 8:
            self.add_error("title", "Use a descriptive project title of at least 8 characters.")
        for json_field in ("services_performed", "technologies_used"):
            value = cleaned.get(json_field)
            if isinstance(value, str):
                cleaned[json_field] = [
                    item.strip() for item in value.replace("\n", ",").split(",") if item.strip()
                ]
        return cleaned

    def save(self, commit=True):
        project = super().save(commit=commit)
        if commit:
            products = self.cleaned_data.get("products_used", [])
            project.project_products.exclude(product__in=products).delete()
            existing = set(project.project_products.values_list("product_id", flat=True))
            ServiceProjectProduct.objects.bulk_create([
                ServiceProjectProduct(project=project, product=product, display_order=index)
                for index, product in enumerate(products)
                if product.id not in existing
            ])
        return project


class ServiceProjectMediaForm(StyledModelForm):
    class Meta:
        model = ServiceProjectMedia
        fields = [
            "media_type", "image", "video", "external_video_url", "thumbnail",
            "caption", "alt_text", "display_order", "is_featured",
        ]


class ServiceQuoteRequestForm(StyledModelForm):
    class Meta:
        model = ServiceQuoteRequest
        fields = [
            "provider", "category", "product", "source_project", "name", "phone", "whatsapp",
            "email", "state", "city", "address", "service_needed", "message",
            "preferred_date", "preferred_time", "budget", "contact_preference", "urgency",
        ]
        widgets = {
            "source_project": forms.HiddenInput(),
            "address": forms.Textarea(attrs={"rows": 3}),
            "message": forms.Textarea(attrs={"rows": 5}),
            "preferred_date": forms.DateInput(attrs={"type": "date"}),
            "preferred_time": forms.TimeInput(attrs={"type": "time"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["provider"].queryset = ServiceProviderProfile.objects.public()
        self.fields["provider"].required = False
        self.fields["category"].required = False
        self.fields["product"].required = False
        self.fields["source_project"].queryset = ServicePortfolio.objects.public()
        self.fields["source_project"].required = False


class ServiceReviewForm(StyledModelForm):
    class Meta:
        model = ServiceReview
        fields = [
            "rating", "professionalism_rating", "communication_rating",
            "quality_rating", "timeliness_rating", "comment",
        ]
        widgets = {
            "rating": forms.Select(choices=[(value, f"{value} star{'s' if value != 1 else ''}") for value in range(5, 0, -1)]),
            "professionalism_rating": forms.Select(choices=[(value, value) for value in range(5, 0, -1)]),
            "communication_rating": forms.Select(choices=[(value, value) for value in range(5, 0, -1)]),
            "quality_rating": forms.Select(choices=[(value, value) for value in range(5, 0, -1)]),
            "timeliness_rating": forms.Select(choices=[(value, value) for value in range(5, 0, -1)]),
            "comment": forms.Textarea(attrs={"rows": 5}),
        }
