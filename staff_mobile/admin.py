from django import forms
from django.contrib import admin

from .models import RiderCredential, StaffMobileToken


@admin.register(StaffMobileToken)
class StaffMobileTokenAdmin(admin.ModelAdmin):
    list_display = ["role", "user", "rider", "device_name", "is_active", "last_used_at", "created_at"]
    list_filter = ["role", "is_active", "created_at", "last_used_at"]
    search_fields = ["user__username", "user__email", "rider__user__email", "rider__phone", "token"]
    readonly_fields = ["token", "last_used_at", "created_at", "updated_at"]
    autocomplete_fields = ["user", "rider"]


class RiderCredentialForm(forms.ModelForm):
    raw_pin = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="Enter a new rider PIN here. Leave blank to keep the current PIN.",
    )

    class Meta:
        model = RiderCredential
        fields = ["rider", "raw_pin", "is_active"]


@admin.register(RiderCredential)
class RiderCredentialAdmin(admin.ModelAdmin):
    form = RiderCredentialForm
    list_display = ["rider", "created_at", "updated_at"]
    search_fields = ["rider__user__first_name", "rider__user__last_name", "rider__user__email", "rider__phone"]
    autocomplete_fields = ["rider"]
    readonly_fields = ["created_at", "updated_at"]

    def save_model(self, request, obj, form, change):
        raw_pin = form.cleaned_data.get("raw_pin")
        if raw_pin:
            obj.set_pin(raw_pin)
        super().save_model(request, obj, form, change)
