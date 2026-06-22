from django import forms


class VendorAdminEmailForm(forms.Form):
    subject = forms.CharField(
        max_length=255,
        widget=forms.TextInput(
            attrs={
                "class": "vTextField",
                "placeholder": "Email subject",
                "style": "width: 100%; max-width: 900px;",
            }
        ),
    )

    message = forms.CharField(
        widget=forms.Textarea(
            attrs={
                "rows": 12,
                "placeholder": "Write your message to the selected vendor(s)...",
                "style": "width: 100%; max-width: 900px;",
            }
        ),
    )

    send_copy_to_admin = forms.BooleanField(
        required=False,
        initial=True,
        label="Send a copy to admin email",
    )