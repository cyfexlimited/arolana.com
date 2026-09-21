from django import forms
from django.contrib.auth import get_user_model

from .models import ImportBatch, ImportPricingRule, ImportSource
from products.models import Brand, Category


class BulkImportForm(forms.Form):
    source = forms.ModelChoiceField(
        queryset=ImportSource.objects.filter(is_active=True).order_by("name"),
        required=False,
        help_text="Optional. Leave blank to detect the source from each URL.",
    )
    products = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 14, "style": "width:100%;font-family:monospace"}),
        help_text=(
            "One product URL or product/model name per line. Direct URLs are analysed immediately. "
            "If a retailer blocks server access, the item is held for official-manufacturer/price evidence rather than guessed."
        ),
    )
    pricing_rule = forms.ModelChoiceField(
        queryset=ImportPricingRule.objects.filter(is_active=True).order_by("-priority", "name"),
        required=False,
        help_text="Leave blank for automatic rule selection.",
    )

    # Destination defaults are optional during evidence analysis. They become
    # mandatory only when the admin prepares an actual Product draft.
    target_vendor = forms.ModelChoiceField(
        queryset=get_user_model().objects.none(),
        required=False,
        help_text="Optional default vendor that will own newly prepared Arolana drafts.",
    )
    default_category = forms.ModelChoiceField(
        queryset=Category.objects.none(),
        required=False,
        help_text="Optional default Arolana category for products in this batch.",
    )
    default_brand = forms.ModelChoiceField(
        queryset=Brand.objects.none(),
        required=False,
        help_text="Optional brand override. Leave blank to match an existing Arolana brand by verified name.",
    )

    max_images = forms.IntegerField(min_value=1, max_value=10, initial=10)
    verify_against_manufacturer = forms.BooleanField(required=False, initial=True)
    generate_or_prepare_images = forms.BooleanField(required=False, initial=True)
    reject_watermarked_images = forms.BooleanField(required=False, initial=True)
    remove_source_identity = forms.BooleanField(required=False, initial=True)
    require_human_approval = forms.BooleanField(required=False, initial=True, disabled=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        User = get_user_model()
        self.fields["target_vendor"].queryset = User.objects.filter(user_type="vendor").order_by("email")
        self.fields["default_category"].queryset = Category.objects.filter(is_active=True).order_by("name")
        self.fields["default_brand"].queryset = Brand.objects.filter(is_active=True).order_by("name")

    def clean_products(self):
        value = self.cleaned_data["products"]
        lines = [line.strip() for line in value.splitlines() if line.strip()]
        if not lines:
            raise forms.ValidationError("Enter at least one product URL or product/model name.")
        if len(lines) > 50:
            raise forms.ValidationError("Use at most 50 lines per import batch.")
        return value
