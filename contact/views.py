import logging

from django.conf import settings
from django.contrib import messages
from django.core.mail import send_mail
from django.shortcuts import get_object_or_404, redirect, render

from vendors.models import VendorProfile
from .models import ContactMessage

logger = logging.getLogger(__name__)


def get_client_ip(request):
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def contact_view(request, vendor_id=None):
    vendor = None

    if vendor_id:
        vendor = get_object_or_404(VendorProfile, id=vendor_id)

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        email = request.POST.get("email", "").strip()
        subject = request.POST.get("subject", "").strip()
        message = request.POST.get("message", "").strip()

        posted_vendor_id = request.POST.get("vendor_id")
        if posted_vendor_id and not vendor:
            vendor = VendorProfile.objects.filter(id=posted_vendor_id).first()

        if not name or not email or not subject or not message:
            messages.error(request, "Please complete all required fields.")
            return redirect("contact")

        contact_message = ContactMessage.objects.create(
            name=name,
            email=email,
            subject=subject,
            message=message,
            vendor=vendor,
            user=request.user if request.user.is_authenticated else None,
            ip_address=get_client_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
        )

        email_subject = f"Arolana Contact Message: {subject}"
        email_body = (
            f"New contact message received on Arolana.\n\n"
            f"Name: {name}\n"
            f"Email: {email}\n"
            f"Vendor: {vendor.store_name if vendor else 'General Support'}\n"
            f"Subject: {subject}\n\n"
            f"Message:\n{message}\n\n"
            f"Message ID: {contact_message.id}"
        )

        recipient = getattr(settings, "SUPPORT_EMAIL", settings.DEFAULT_FROM_EMAIL)

        try:
            send_mail(
                subject=email_subject,
                message=email_body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[recipient],
                fail_silently=False,
            )
            messages.success(request, "Your message has been sent. We’ll get back to you soon.")
        except Exception as exc:
            logger.exception("Contact email failed: %s", exc)
            messages.warning(
                request,
                "Your message was saved, but email notification could not be sent. Our team will still review it.",
            )

        return redirect("contact:index")

    return render(request, "support/contact.html", {"vendor": vendor})