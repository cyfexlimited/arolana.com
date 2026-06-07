from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone


def send_vendor_password_changed_email(user):
    """Send a non-sensitive security confirmation after a vendor password change."""
    email = (getattr(user, "email", "") or "").strip()
    if not email:
        return False

    name = user.get_full_name() or getattr(user, "username", "") or "Vendor"
    changed_at = timezone.localtime().strftime("%d %b %Y at %I:%M %p")
    subject = "Your Arolana vendor password was changed"
    message = (
        f"Dear {name},\n\n"
        "This is a security confirmation that the password/PIN for your Arolana "
        f"vendor account was changed successfully on {changed_at}.\n\n"
        "Your password is never included in email. If you made this change, no "
        "further action is required.\n\n"
        "If you did not make this change, reset your password immediately and "
        "contact Arolana Support:\n"
        "Email: support@arolana.com\n"
        "Call: +2349033713922\n"
        "WhatsApp: +2349132924620\n\n"
        "Thank you for keeping your Arolana account secure.\n\n"
        "Arolana Security Team"
    )
    try:
        return bool(
            send_mail(
                subject,
                message,
                getattr(settings, "DEFAULT_FROM_EMAIL", "support@arolana.com"),
                [email],
                fail_silently=False,
            )
        )
    except Exception:
        # A temporary email-provider issue must not roll back a valid password change.
        return False
