import hashlib
import time

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse, JsonResponse


class ArolanaSecurityHeadersMiddleware:
    """Add defense-in-depth browser security headers in production."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        if not getattr(settings, "AROLANA_SECURITY_HEADERS_ENABLED", not settings.DEBUG):
            return response

        headers = getattr(settings, "AROLANA_SECURITY_HEADERS", {})
        for header, value in headers.items():
            if value and header not in response:
                response[header] = value

        return response


class ArolanaRateLimitMiddleware:
    """Small cache-backed rate limiter for high-risk public endpoints."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not getattr(settings, "AROLANA_RATE_LIMIT_ENABLED", not settings.DEBUG):
            return self.get_response(request)

        rule = self._matching_rule(request)
        if rule and self._is_limited(request, rule):
            return self._limited_response(request, rule)

        return self.get_response(request)

    def _matching_rule(self, request):
        path = request.path_info or request.path
        method = request.method.upper()

        for rule in getattr(settings, "AROLANA_RATE_LIMIT_RULES", []):
            methods = {item.upper() for item in rule.get("methods", ["POST"])}
            if method not in methods:
                continue

            if any(path.startswith(prefix) for prefix in rule.get("paths", [])):
                return rule

        return None

    def _identity(self, request):
        user = getattr(request, "user", None)
        if user and user.is_authenticated:
            return f"user:{user.pk}"

        forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
        ip_address = forwarded_for.split(",", 1)[0].strip() if forwarded_for else ""
        ip_address = ip_address or request.META.get("REMOTE_ADDR", "unknown")
        user_agent = request.META.get("HTTP_USER_AGENT", "")[:160]
        fingerprint = hashlib.sha256(f"{ip_address}|{user_agent}".encode("utf-8")).hexdigest()[:32]
        return f"anon:{fingerprint}"

    def _cache_key(self, request, rule):
        identity = self._identity(request)
        period = int(time.time() // int(rule.get("window", 60)))
        raw_key = f"{rule.get('name', 'default')}:{identity}:{period}"
        digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        return f"arolana:rate:{digest}"

    def _is_limited(self, request, rule):
        key = self._cache_key(request, rule)
        window = int(rule.get("window", 60))
        limit = int(rule.get("limit", 60))

        added = cache.add(key, 1, timeout=window + 5)
        if added:
            return False

        try:
            count = cache.incr(key)
        except ValueError:
            cache.set(key, 1, timeout=window + 5)
            return False

        return count > limit

    def _limited_response(self, request, rule):
        message = rule.get(
            "message",
            "Too many requests. Please wait a moment and try again.",
        )
        retry_after = str(int(rule.get("window", 60)))

        expects_json = (
            "/api/" in request.path_info
            or request.headers.get("X-Requested-With") == "XMLHttpRequest"
            or "application/json" in request.headers.get("Accept", "")
        )

        if expects_json:
            response = JsonResponse({"success": False, "error": message}, status=429)
        else:
            response = HttpResponse(message, status=429, content_type="text/plain")

        response["Retry-After"] = retry_after
        return response
