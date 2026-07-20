from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import (
    PasswordResetForm,
    SetPasswordForm,
    PasswordChangeForm,
    UserCreationForm,
)
from django.core.exceptions import ValidationError
import re

try:
    import dns.resolver
except Exception:
    dns = None

try:
    from email_validator import validate_email, EmailNotValidError
except Exception:
    validate_email = None
    EmailNotValidError = Exception


User = get_user_model()


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
    "dispostable.com",
    "temp-mail.org",
    "maildrop.cc",
    "throwawaymail.com",
}


BLOCKED_EMAIL_DOMAINS = {
    "example.com",
    "test.com",
    "invalid.com",
    "localhost",
}


COMMON_EMAIL_TYPOS = {
    "gmail.con": "gmail.com",
    "gmail.co": "gmail.com",
    "gamil.com": "gmail.com",
    "gmial.com": "gmail.com",
    "gmai.com": "gmail.com",
    "yahoo.coom": "yahoo.com",
    "yahoo.con": "yahoo.com",
    "yaho.com": "yahoo.com",
    "yahoomail.com": "yahoo.com",
    "hotmail.con": "hotmail.com",
    "hotmai.com": "hotmail.com",
    "outlook.con": "outlook.com",
    "icloud.con": "icloud.com",
}


def validate_password_strength(password):
    """
    Arolana password strength rule.
    """

    if not password:
        raise ValidationError("Password is required.")

    if len(password) < 8:
        raise ValidationError("Password must be at least 8 characters long.")

    if not re.search(r"[A-Z]", password):
        raise ValidationError("Password must contain at least one uppercase letter.")

    if not re.search(r"[a-z]", password):
        raise ValidationError("Password must contain at least one lowercase letter.")

    if not re.search(r"[0-9]", password):
        raise ValidationError("Password must contain at least one number.")

    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        raise ValidationError(
            "Password must contain at least one special character (!@#$%^&* etc.)."
        )

    return password


def normalize_and_validate_real_email(email):
    """
    Strong Arolana email validation.

    Blocks:
    - invalid email format
    - common typo domains like yahoo.coom
    - fake/test domains
    - disposable email domains
    - domains without MX record

    This prevents wrong emails from creating pending/unverified users.
    """

    if not email:
        raise ValidationError("Email address is required.")

    email = str(email).strip().lower()

    if validate_email:
        try:
            result = validate_email(
                email,
                check_deliverability=False,
            )
            email = result.normalized.lower()
        except EmailNotValidError:
            raise ValidationError("Please enter a valid email address.")
    else:
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            raise ValidationError("Please enter a valid email address.")

    domain = email.split("@")[-1].strip().lower()

    if not domain:
        raise ValidationError("Please enter a valid email address.")

    if domain in COMMON_EMAIL_TYPOS:
        correct_domain = COMMON_EMAIL_TYPOS[domain]
        raise ValidationError(
            f"This email domain looks incorrect. Did you mean @{correct_domain}?"
        )

    if domain in BLOCKED_EMAIL_DOMAINS:
        raise ValidationError("This email domain is not allowed.")

    if domain in DISPOSABLE_EMAIL_DOMAINS:
        raise ValidationError("Temporary or disposable email addresses are not allowed.")

    if ".." in domain or domain.startswith(".") or domain.endswith("."):
        raise ValidationError("Please enter a valid email address.")

    if dns and getattr(settings, "AROLANA_EMAIL_MX_VALIDATION_ENABLED", not settings.DEBUG):
        try:
            mx_records = dns.resolver.resolve(domain, "MX")
            if not mx_records:
                raise ValidationError("This email domain cannot receive emails.")
        except ValidationError:
            raise
        except Exception:
            raise ValidationError(
                "This email domain is not valid or cannot receive emails."
            )

    return email


class CustomPasswordResetForm(PasswordResetForm):
    email = forms.EmailField(
        label="Email Address",
        widget=forms.EmailInput(
            attrs={
                "class": "w-full px-4 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500",
                "placeholder": "Enter your email address",
                "required": True,
            }
        ),
    )

    def clean_email(self):
        email = self.cleaned_data.get("email")
        return normalize_and_validate_real_email(email)


class CustomSetPasswordForm(SetPasswordForm):
    new_password1 = forms.CharField(
        label="New Password",
        widget=forms.PasswordInput(
            attrs={
                "class": "w-full px-4 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500",
                "placeholder": "Enter new password",
                "required": True,
            }
        ),
        help_text=(
            "Password must be at least 8 characters and include uppercase, "
            "lowercase, number, and special character."
        ),
    )

    new_password2 = forms.CharField(
        label="Confirm Password",
        widget=forms.PasswordInput(
            attrs={
                "class": "w-full px-4 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500",
                "placeholder": "Confirm new password",
                "required": True,
            }
        ),
    )

    def clean_new_password1(self):
        password = self.cleaned_data.get("new_password1")
        return validate_password_strength(password)


class CustomChangePasswordForm(PasswordChangeForm):
    new_password1 = forms.CharField(
        label="New Password",
        widget=forms.PasswordInput(
            attrs={
                "class": "w-full px-4 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500",
                "placeholder": "Enter new password",
                "required": True,
            }
        ),
        help_text=(
            "Password must be at least 8 characters and include uppercase, "
            "lowercase, number, and special character."
        ),
    )

    new_password2 = forms.CharField(
        label="Confirm New Password",
        widget=forms.PasswordInput(
            attrs={
                "class": "w-full px-4 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500",
                "placeholder": "Confirm new password",
                "required": True,
            }
        ),
    )

    def clean_new_password1(self):
        password = self.cleaned_data.get("new_password1")
        return validate_password_strength(password)


class CustomSignupForm(UserCreationForm):
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(
            attrs={
                "class": "w-full px-4 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500",
                "placeholder": "Email address",
                "autocomplete": "email",
            }
        ),
    )

    password1 = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(
            attrs={
                "class": "w-full px-4 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500",
                "placeholder": "Create password",
                "autocomplete": "new-password",
            }
        ),
        help_text=(
            "Password must be at least 8 characters and include uppercase, "
            "lowercase, number, and special character."
        ),
    )

    password2 = forms.CharField(
        label="Confirm Password",
        widget=forms.PasswordInput(
            attrs={
                "class": "w-full px-4 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500",
                "placeholder": "Confirm password",
                "autocomplete": "new-password",
            }
        ),
    )

    class Meta:
        model = User
        fields = ("email", "password1", "password2")

    def clean_email(self):
        email = self.cleaned_data.get("email")
        email = normalize_and_validate_real_email(email)

        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("A user with that email already exists.")

        return email

    def clean_password1(self):
        password = self.cleaned_data.get("password1")
        return validate_password_strength(password)

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"].lower()

        if hasattr(user, "username") and not user.username:
            user.username = user.email

        if commit:
            user.save()

        return user


try:
    from allauth.account.forms import SignupForm as AllauthSignupForm

    class ArolanaAllauthSignupForm(AllauthSignupForm):
        def clean_email(self):
            email = self.cleaned_data.get("email")
            email = normalize_and_validate_real_email(email)

            if User.objects.filter(email__iexact=email).exists():
                raise ValidationError("A user with that email already exists.")

            return email

        def clean_password1(self):
            password = self.cleaned_data.get("password1")
            return validate_password_strength(password)

except Exception:
    pass
