from django.utils import timezone
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed

from staff_mobile.models import StaffMobileToken


class StaffMobileTokenAuthentication(BaseAuthentication):
    """Authenticate the existing React Native staff/vendor/provider bearer token."""

    keyword = b"bearer"

    def authenticate(self, request):
        parts = get_authorization_header(request).split()
        if not parts or parts[0].lower() != self.keyword:
            return None
        if len(parts) != 2:
            raise AuthenticationFailed("Invalid mobile authorization header.")

        try:
            raw_token = parts[1].decode("utf-8")
        except UnicodeError as exc:
            raise AuthenticationFailed("Invalid mobile authorization header.") from exc

        session = (
            StaffMobileToken.objects.select_related("user")
            .filter(token=raw_token, is_active=True, user__is_active=True)
            .first()
        )
        if not session or not session.user:
            raise AuthenticationFailed("Invalid or expired mobile session.")
        if session.role not in {"vendor", "provider", "admin"}:
            raise AuthenticationFailed("This mobile role cannot publish social content.")

        session.last_used_at = timezone.now()
        session.save(update_fields=["last_used_at", "updated_at"])
        return session.user, session
