from django.core.cache import cache
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings

from .middleware import ArolanaRateLimitMiddleware, ArolanaSecurityHeadersMiddleware


class ArolanaSecurityMiddlewareTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @override_settings(
        AROLANA_SECURITY_HEADERS_ENABLED=True,
        AROLANA_SECURITY_HEADERS={
            "Content-Security-Policy": "default-src 'self'; object-src 'none'",
            "Permissions-Policy": "camera=(), microphone=(self)",
            "X-Permitted-Cross-Domain-Policies": "none",
        },
    )
    def test_security_headers_are_added(self):
        middleware = ArolanaSecurityHeadersMiddleware(lambda request: HttpResponse("ok"))
        response = middleware(self.factory.get("/"))

        self.assertEqual(response["Content-Security-Policy"], "default-src 'self'; object-src 'none'")
        self.assertEqual(response["Permissions-Policy"], "camera=(), microphone=(self)")
        self.assertEqual(response["X-Permitted-Cross-Domain-Policies"], "none")

    @override_settings(
        AROLANA_RATE_LIMIT_ENABLED=True,
        AROLANA_RATE_LIMIT_RULES=[
            {
                "name": "test-login",
                "paths": ["/accounts/login/"],
                "methods": ["POST"],
                "limit": 1,
                "window": 60,
            }
        ],
    )
    def test_rate_limiter_blocks_after_limit(self):
        cache.clear()
        middleware = ArolanaRateLimitMiddleware(lambda request: HttpResponse("ok"))

        first = middleware(self.factory.post("/accounts/login/", HTTP_USER_AGENT="test-agent"))
        second = middleware(self.factory.post("/accounts/login/", HTTP_USER_AGENT="test-agent"))

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
        self.assertEqual(second["Retry-After"], "60")
