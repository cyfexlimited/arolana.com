"""Provider upload CSRF protection that validates AJAX headers before bodies."""

from django.conf import settings
from django.middleware.csrf import (
    CsrfViewMiddleware,
    InvalidTokenFormat,
    REASON_NO_CSRF_COOKIE,
    RejectRequest,
    _check_token_format,
    _does_token_match,
)
from django.utils.decorators import decorator_from_middleware


class HeaderFirstCsrfViewMiddleware(CsrfViewMiddleware):
    """Use X-CSRFToken first so large AJAX bodies are not parsed for CSRF."""

    def _check_token(self, request):
        request_csrf_token = request.META.get(settings.CSRF_HEADER_NAME, "")
        if not request_csrf_token:
            return super()._check_token(request)

        try:
            csrf_secret = self._get_secret(request)
        except InvalidTokenFormat as exc:
            raise RejectRequest(f"CSRF cookie {exc.reason}.")
        if csrf_secret is None:
            raise RejectRequest(REASON_NO_CSRF_COOKIE)
        try:
            _check_token_format(request_csrf_token)
        except InvalidTokenFormat as exc:
            raise RejectRequest(
                self._bad_token_message(exc.reason, settings.CSRF_HEADER_NAME)
            )
        if not _does_token_match(request_csrf_token, csrf_secret):
            raise RejectRequest(
                self._bad_token_message("incorrect", settings.CSRF_HEADER_NAME)
            )


header_first_csrf_protect = decorator_from_middleware(HeaderFirstCsrfViewMiddleware)
