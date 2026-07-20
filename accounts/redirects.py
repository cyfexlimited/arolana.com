"""Safe, shared post-authentication redirect handling."""

import time
from urllib.parse import unquote, urlencode, urlparse

from django.conf import settings
from django.core.exceptions import DisallowedHost
from django.urls import NoReverseMatch, reverse
from django.utils.http import url_has_allowed_host_and_scheme


PENDING_LOGIN_REDIRECT_SESSION_KEY = "pending_login_redirect"
PENDING_LOGIN_REDIRECT_CREATED_AT_SESSION_KEY = (
    "pending_login_redirect_created_at"
)

# These keys were used by the older multi-step login implementation. Reading
# them keeps logins that were already in progress during a deployment working,
# while all new flows are promoted to the shared key above.
LEGACY_PENDING_LOGIN_REDIRECT_SESSION_KEYS = (
    "pre_2fa_next",
    "pending_email_verification_next",
)

AUTH_HANDOFF_SESSION_KEYS = (
    PENDING_LOGIN_REDIRECT_SESSION_KEY,
    PENDING_LOGIN_REDIRECT_CREATED_AT_SESSION_KEY,
    *LEGACY_PENDING_LOGIN_REDIRECT_SESSION_KEYS,
    "pre_2fa_user_id",
    "pre_2fa_remember",
    "pending_email_verification_user_id",
    "email_verification_send_failed",
    "reset_user_id",
    # django-allauth handoff/staging state.
    "account_login",
    "account_authentication_methods",
    "account_verified_email",
    "_password_reset_key",
    "socialaccount_states",
    "socialaccount_sociallogin",
)

MAX_LOGIN_REDIRECT_LENGTH = 4096
DEFAULT_LOGIN_REDIRECT_SESSION_TTL = 30 * 60

AUTH_HANDOFF_URL_NAMES = (
    "accounts:login",
    "account_login",
    "accounts:logout",
    "account_logout",
    "accounts:register",
    "account_signup",
    "accounts:verify_2fa",
    "accounts:verify_email",
    "accounts:forgot_password",
    "accounts:reset_password_verify",
)


def _configured_redirect_hosts():
    hosts = getattr(settings, "LOGIN_REDIRECT_ALLOWED_HOSTS", ())
    if isinstance(hosts, str):
        hosts = hosts.split(",")
    return {
        str(host).strip()
        for host in hosts
        if str(host).strip() and "*" not in str(host)
    }


def _allowed_redirect_hosts(request):
    hosts = _configured_redirect_hosts()
    try:
        hosts.add(request.get_host())
    except DisallowedHost:
        # A rejected Host header must never become an allowed redirect host.
        pass
    return hosts


def _auth_handoff_paths():
    paths = set()
    for url_name in AUTH_HANDOFF_URL_NAMES:
        try:
            path = reverse(url_name)
            paths.add(path.rstrip("/") or "/")
        except NoReverseMatch:
            continue
    return paths


def safe_login_redirect_url(request, value):
    """Return ``value`` unchanged only when it is a safe internal URL."""
    if not isinstance(value, str):
        return None

    if not value or len(value) > MAX_LOGIN_REDIRECT_LENGTH:
        return None

    # Do not silently normalize whitespace/control-character payloads into a
    # different URL. Django will encode these in a redirect response, but they
    # are not meaningful intended destinations.
    if value != value.strip() or any(ord(character) < 32 for character in value):
        return None

    try:
        parsed = urlparse(value)
    except ValueError:
        return None

    # Returning to an authentication handoff page can bounce an authenticated
    # user straight back through the login/OTP flow. Reject those endpoints as
    # destinations while still allowing ordinary account pages.
    normalized_path = (unquote(parsed.path).rstrip("/") or "/")
    if normalized_path in _auth_handoff_paths():
        return None

    # Login destinations are either root-relative paths or absolute URLs for
    # the current/explicitly approved Arolana host. Bare relative strings can
    # otherwise produce surprising redirects relative to /accounts/.
    if not value.startswith("/") and not (parsed.scheme and parsed.netloc):
        return None

    try:
        is_allowed = url_has_allowed_host_and_scheme(
            value,
            allowed_hosts=_allowed_redirect_hosts(request),
            require_https=request.is_secure(),
        )
    except (TypeError, ValueError):
        return None

    return value if is_allowed else None


def remember_login_redirect(request, *candidates):
    """Store the first safe candidate and return the current safe destination."""
    for candidate in candidates:
        safe_url = safe_login_redirect_url(request, candidate)
        if safe_url:
            request.session[PENDING_LOGIN_REDIRECT_SESSION_KEY] = safe_url
            request.session[
                PENDING_LOGIN_REDIRECT_CREATED_AT_SESSION_KEY
            ] = time.time()
            return safe_url

    return get_pending_login_redirect(request)


def capture_request_login_redirect(request):
    """Capture valid POST then GET ``next``, retaining a safe session value."""
    return remember_login_redirect(
        request,
        request.POST.get("next"),
        request.GET.get("next"),
    )


def capture_login_entry_redirect(request):
    """
    Start or clear a browser login flow.

    A standalone GET of the login page intentionally cancels abandoned
    destination and partial-auth state so a later direct login is clean.
    Multi-step handoffs link back with an explicit validated ``next``; their
    UI can request an account-switch cancellation with ``cancel_auth=1``.
    """
    if request.method != "GET":
        return capture_request_login_redirect(request)

    candidate = safe_login_redirect_url(request, request.GET.get("next"))
    cancel_auth = request.GET.get("cancel_auth") in {"1", "true", "yes"}
    if cancel_auth or not candidate:
        clear_auth_handoff_session(request)
    else:
        clear_pending_login_redirect(request)
    if candidate:
        return remember_login_redirect(request, candidate)
    return None


def _pending_redirect_is_expired(request):
    created_at = request.session.get(
        PENDING_LOGIN_REDIRECT_CREATED_AT_SESSION_KEY
    )
    if created_at is None:
        # Accept and timestamp pre-deployment sessions once.
        request.session[
            PENDING_LOGIN_REDIRECT_CREATED_AT_SESSION_KEY
        ] = time.time()
        return False

    try:
        age = time.time() - float(created_at)
        ttl = int(
            getattr(
                settings,
                "LOGIN_REDIRECT_SESSION_TTL",
                DEFAULT_LOGIN_REDIRECT_SESSION_TTL,
            )
        )
    except (TypeError, ValueError):
        return True
    return age < 0 or age > max(ttl, 0)


def get_pending_login_redirect(request):
    """Return a safe pending destination without consuming it."""
    for key in (
        PENDING_LOGIN_REDIRECT_SESSION_KEY,
        *LEGACY_PENDING_LOGIN_REDIRECT_SESSION_KEYS,
    ):
        candidate = request.session.get(key)
        safe_url = safe_login_redirect_url(request, candidate)
        if safe_url:
            if (
                key == PENDING_LOGIN_REDIRECT_SESSION_KEY
                and _pending_redirect_is_expired(request)
            ):
                clear_pending_login_redirect(request)
                continue
            if key != PENDING_LOGIN_REDIRECT_SESSION_KEY:
                return remember_login_redirect(request, safe_url)
            return safe_url
        if candidate is not None:
            request.session.pop(key, None)
        if key == PENDING_LOGIN_REDIRECT_SESSION_KEY:
            request.session.pop(
                PENDING_LOGIN_REDIRECT_CREATED_AT_SESSION_KEY,
                None,
            )
    return None


def clear_pending_login_redirect(request):
    for key in (
        PENDING_LOGIN_REDIRECT_SESSION_KEY,
        *LEGACY_PENDING_LOGIN_REDIRECT_SESSION_KEYS,
        PENDING_LOGIN_REDIRECT_CREATED_AT_SESSION_KEY,
    ):
        request.session.pop(key, None)


def clear_completed_auth_handoff_session(request):
    """Clear abandoned partial-auth state after a successful login."""
    completed_keys = set(AUTH_HANDOFF_SESSION_KEYS) - {
        # allauth intentionally keeps this successful-auth audit in-session.
        "account_authentication_methods",
    }
    for key in completed_keys:
        request.session.pop(key, None)


def clear_auth_handoff_session(request):
    """Clear redirect and temporary authentication state on logout."""
    for key in AUTH_HANDOFF_SESSION_KEYS:
        request.session.pop(key, None)


def login_url_with_pending_redirect(request):
    """Return the login URL carrying the current safe destination, if any."""
    login_url = reverse("accounts:login")
    destination = get_pending_login_redirect(request)
    if not destination:
        return login_url
    return f"{login_url}?{urlencode({'next': destination})}"


def role_login_redirect_url(user):
    """Return a sensible direct-login destination for an Arolana role."""
    if not user or not getattr(user, "is_authenticated", False):
        return reverse("home")

    if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
        return reverse("dashboard:admin_home")

    if hasattr(user, "service_provider_profile"):
        return reverse("provider_workspace:dashboard")

    if getattr(user, "user_type", "") in {"vendor", "manufacturer"} or hasattr(
        user, "vendor_profile"
    ):
        return reverse("dashboard:vendor_home")

    if hasattr(user, "rider_profile"):
        return reverse("deliveries:rider_dashboard")

    return reverse("home")


def resolve_post_login_redirect(request, user=None):
    """
    Resolve and consume the post-login destination.

    Priority is valid POST ``next``, valid GET ``next``, safe session state,
    role fallback, then the homepage.
    """
    destination = capture_request_login_redirect(request)
    clear_completed_auth_handoff_session(request)
    if destination:
        return destination

    try:
        return role_login_redirect_url(user or request.user)
    except NoReverseMatch:
        return reverse("home")
