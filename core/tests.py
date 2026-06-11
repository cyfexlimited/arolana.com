from types import SimpleNamespace
from unittest.mock import patch

from django.core.cache import cache
from django.http import HttpResponse
from django.test import Client, RequestFactory, SimpleTestCase, TestCase, override_settings

from . import local_cache
from .media_optimization import get_optimized_image_url
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

    @override_settings(
        DEBUG=False,
        SECURE_SSL_REDIRECT=True,
        SECURE_REDIRECT_EXEMPT=[r"^health/$"],
    )
    def test_health_check_is_not_redirected_by_https_enforcement(self):
        response = Client().get("/health/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")


class PerformanceHelperTests(SimpleTestCase):
    def tearDown(self):
        cache.clear()
        local_cache._CACHE.clear()

    def test_local_cache_falls_back_to_shared_cache(self):
        local_cache.local_set("performance:test", {"ready": True}, 60)
        local_cache._CACHE.clear()

        self.assertEqual(
            local_cache.local_get("performance:test"),
            {"ready": True},
        )

    @override_settings(OPTIMIZED_MEDIA_GENERATE_ON_REQUEST=False)
    def test_optimized_image_url_skips_storage_checks_during_request(self):
        image = SimpleNamespace(
            name="products/example.jpg",
            url="/media/products/example.jpg",
        )

        with patch("core.media_optimization.default_storage") as storage:
            storage.url.return_value = "/media/optimized/product_card/products/example.webp"

            result = get_optimized_image_url(image, "product_card")

        self.assertEqual(
            result,
            "/media/optimized/product_card/products/example.webp",
        )
        storage.exists.assert_not_called()
        storage.open.assert_not_called()
