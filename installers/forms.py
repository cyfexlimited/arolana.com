from django import forms

from .models import (
    ProviderService,
    ServicePortfolio,
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
            "cac_number", "government_id_upload", "profile_image",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 5}),
            "address": forms.Textarea(attrs={"rows": 3}),
        }


class ProviderServiceForm(StyledModelForm):
    class Meta:
        model = ProviderService
        fields = ["category", "service_name", "description", "starting_price", "is_active"]
        widgets = {"description": forms.Textarea(attrs={"rows": 4})}


class ServicePortfolioForm(StyledModelForm):
    class Meta:
        model = ServicePortfolio
        fields = ["title", "description", "image", "video_url", "project_location", "completed_at"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "completed_at": forms.DateInput(attrs={"type": "date"}),
        }


class ServiceQuoteRequestForm(StyledModelForm):
    class Meta:
        model = ServiceQuoteRequest
        fields = [
            "provider", "category", "product", "name", "phone", "whatsapp",
            "email", "state", "city", "address", "service_needed", "message",
        ]
        widgets = {
            "address": forms.Textarea(attrs={"rows": 3}),
            "message": forms.Textarea(attrs={"rows": 5}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["provider"].queryset = ServiceProviderProfile.objects.public()
        self.fields["provider"].required = False
        self.fields["category"].required = False
        self.fields["product"].required = False


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

