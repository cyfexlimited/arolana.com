from django.conf import settings
from django.contrib import admin, messages
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.core.mail import EmailMultiAlternatives
from django.shortcuts import redirect, render
from django.urls import path
from django.utils.html import strip_tags

from .forms import VendorAdminEmailForm


def get_vendor_email(vendor):
    """
    Safely find vendor email from Arolana VendorProfile.
    Priority:
    1. support_email
    2. user.email
    3. other possible email fields
    """

    possible_fields = [
        "support_email",
        "email",
        "business_email",
        "store_email",
        "contact_email",
    ]

    for field in possible_fields:
        value = getattr(vendor, field, None)
        if value:
            return str(value).strip()

    user = getattr(vendor, "user", None)
    if user and getattr(user, "email", None):
        return str(user.email).strip()

    return ""


def get_vendor_name(vendor):
    possible_fields = [
        "store_name",
        "business_name",
        "company_name",
        "name",
    ]

    for field in possible_fields:
        value = getattr(vendor, field, None)
        if value:
            return str(value).strip()

    user = getattr(vendor, "user", None)
    if user:
        full_name = ""
        if hasattr(user, "get_full_name"):
            full_name = user.get_full_name()
        if full_name:
            return full_name
        if getattr(user, "username", None):
            return str(user.username)

    return "Vendor"


class VendorEmailAdminMixin:
    """
    Add this mixin to your VendorProfileAdmin.

    It adds:
    - Admin action: Send email to selected vendors
    - Compose email screen
    - Bulk sending through Django email backend
    """

    actions = ["send_email_to_selected_vendors"]

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "send-email/",
                self.admin_site.admin_view(self.send_email_view),
                name="vendors_vendor_send_email",
            ),
        ]
        return custom_urls + urls

    @admin.action(description="Send email to selected vendors")
    def send_email_to_selected_vendors(self, request, queryset):
        selected = request.POST.getlist(ACTION_CHECKBOX_NAME)

        if not selected:
            self.message_user(
                request,
                "Please select at least one vendor.",
                level=messages.WARNING,
            )
            return None

        request.session["selected_vendor_ids_for_email"] = selected
        return redirect("admin:vendors_vendor_send_email")

    def send_email_view(self, request):
        vendor_ids = request.session.get("selected_vendor_ids_for_email", [])

        if not vendor_ids:
            self.message_user(
                request,
                "No vendors selected for email.",
                level=messages.WARNING,
            )
            return redirect("..")

        vendors = self.model.objects.filter(pk__in=vendor_ids)

        valid_recipients = []
        vendors_without_email = []

        for vendor in vendors:
            email = get_vendor_email(vendor)
            if email:
                valid_recipients.append((vendor, email))
            else:
                vendors_without_email.append(vendor)

        if request.method == "POST":
            form = VendorAdminEmailForm(request.POST)

            if form.is_valid():
                subject = form.cleaned_data["subject"].strip()
                message_body = form.cleaned_data["message"].strip()
                send_copy_to_admin = form.cleaned_data["send_copy_to_admin"]

                if not valid_recipients:
                    self.message_user(
                        request,
                        "None of the selected vendors has an email address.",
                        level=messages.ERROR,
                    )
                    return redirect("..")

                sent_count = 0
                failed_count = 0

                from_email = getattr(
                    settings,
                    "DEFAULT_FROM_EMAIL",
                    "Arolana Vendor Support <noreply@arolana.com>",
                )

                admin_email = getattr(settings, "DEFAULT_FROM_EMAIL", "")

                for vendor, recipient_email in valid_recipients:
                    vendor_name = get_vendor_name(vendor)

                    plain_text = message_body.replace("{{ vendor_name }}", vendor_name)

                    html_body = plain_text.replace("\n", "<br>")

                    email = EmailMultiAlternatives(
                        subject=subject,
                        body=strip_tags(plain_text),
                        from_email=from_email,
                        to=[recipient_email],
                    )

                    email.attach_alternative(html_body, "text/html")

                    if send_copy_to_admin and admin_email:
                        email.bcc = [admin_email]

                    try:
                        email.send(fail_silently=False)
                        sent_count += 1
                    except Exception:
                        failed_count += 1

                if sent_count:
                    self.message_user(
                        request,
                        f"Email sent successfully to {sent_count} vendor(s).",
                        level=messages.SUCCESS,
                    )

                if failed_count:
                    self.message_user(
                        request,
                        f"{failed_count} email(s) failed to send. Check email settings/logs.",
                        level=messages.ERROR,
                    )

                if vendors_without_email:
                    self.message_user(
                        request,
                        f"{len(vendors_without_email)} selected vendor(s) had no email address.",
                        level=messages.WARNING,
                    )

                request.session.pop("selected_vendor_ids_for_email", None)
                return redirect("..")

        else:
            form = VendorAdminEmailForm(
                initial={
                    "subject": "Complete Your Arolana Vendor KYC Verification",
                    "message": (
                        "Good day {{ vendor_name }},\n\n"
                        "Welcome to Arolana, and thank you for registering as a vendor.\n\n"
                        "To fully activate your vendor account and allow you to start selling properly on Arolana, "
                        "please complete your KYC verification in your vendor dashboard.\n\n"
                        "This helps us verify your business details, protect customers, build trust, and approve you "
                        "as a full vendor on the platform.\n\n"
                        "Please log in to your Arolana vendor account and complete the required KYC information/documents.\n\n"
                        "Once submitted, our team will review and approve your vendor profile.\n\n"
                        "Thank you,\n"
                        "Arolana Vendor Support"
                    ),
                }
            )

        context = {
            **self.admin_site.each_context(request),
            "title": "Send Email to Selected Vendors",
            "form": form,
            "vendors": vendors,
            "valid_recipients": valid_recipients,
            "vendors_without_email": vendors_without_email,
            "opts": self.model._meta,
        }

        return render(request, "admin/vendors/send_vendor_email.html", context)