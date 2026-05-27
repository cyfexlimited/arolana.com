import dns.resolver
from django.core.exceptions import ValidationError
from email_validator import validate_email, EmailNotValidError


DISPOSABLE_EMAIL_DOMAINS = {
    "mailinator.com",
    "tempmail.com",
    "10minutemail.com",
    "guerrillamail.com",
    "yopmail.com",
    "trashmail.com",
    "fakeinbox.com",
    "getnada.com",
    "sharklasers.com",
}


BLOCKED_EMAIL_DOMAINS = {
    "example.com",
    "test.com",
    "invalid.com",
    "localhost",
}


def validate_real_email_address(email):
    """
    Strong email validation for Arolana registration.

    Checks:
    - Email format
    - Normalized email
    - Disposable email domains
    - Blocked/test domains
    - MX DNS records
    """

    if not email:
        raise ValidationError("Email address is required.")

    email = str(email).strip().lower()

    try:
        result = validate_email(
            email,
            check_deliverability=False,
        )
        normalized_email = result.normalized.lower()
    except EmailNotValidError:
        raise ValidationError("Please enter a valid email address.")

    domain = normalized_email.split("@")[-1]

    if domain in BLOCKED_EMAIL_DOMAINS:
        raise ValidationError("This email domain is not allowed.")

    if domain in DISPOSABLE_EMAIL_DOMAINS:
        raise ValidationError("Temporary or disposable email addresses are not allowed.")

    try:
        mx_records = dns.resolver.resolve(domain, "MX")
        if not mx_records:
            raise ValidationError("This email domain cannot receive emails.")
    except Exception:
        raise ValidationError("This email domain is not valid or cannot receive emails.")

    return normalized_email