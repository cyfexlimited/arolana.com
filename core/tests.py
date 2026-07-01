from types import SimpleNamespace
from unittest.mock import patch

from django.core.cache import cache
from django.http import HttpResponse
from django.template import Context, Template
from django.test import Client, RequestFactory, SimpleTestCase, TestCase, override_settings

from . import local_cache
from .media_optimization import PRESETS, get_optimized_image_url, get_safe_background_image_url
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

    @override_settings(
        OPTIMIZED_MEDIA_GENERATE_ON_REQUEST=False,
        OPTIMIZED_MEDIA_CACHE_VERSION="clarity-test",
    )
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
            "/media/optimized/product_card/products/example.webp?v=clarity-test",
        )
        storage.exists.assert_not_called()
        storage.open.assert_not_called()

    def test_optimized_image_template_filter_handles_missing_images(self):
        rendered = Template(
            "{% load optimized_images %}"
            "<img src=\"{{ image|optimized_image_url:'product_card' }}\" alt=\"Product\">"
        ).render(Context({"image": None}))

        self.assertEqual(rendered, '<img src="" alt="Product">')

    def test_customer_facing_and_legacy_presets_are_available(self):
        required_presets = {
            "product_card",
            "product_card_large",
            "product_detail",
            "product_gallery",
            "product_thumb",
            "accessory_thumb",
            "category_card",
            "category_banner",
            "hero",
            "hero_banner",
            "homepage_hero",
            "mobile_hero",
            "background_desktop",
            "background_mobile",
            "avatar",
            "logo",
            "blog_card",
            "blog_detail",
            "ad",
            "ad_card",
            "banner",
            "vendor_banner",
            "seo",
            "thumbnail",
            "video_thumb",
        }

        self.assertTrue(required_presets.issubset(PRESETS))

    @override_settings(OPTIMIZED_MEDIA_ENABLED=True)
    def test_background_url_falls_back_to_original_when_variant_is_missing(self):
        image = SimpleNamespace(
            name="homepage/backgrounds/mobile/current.png",
            url="/media/homepage/backgrounds/mobile/current.png",
        )

        with patch("core.media_optimization.default_storage") as storage:
            storage.exists.return_value = False

            result = get_safe_background_image_url(image, "background_mobile")

        self.assertEqual(result, image.url)
        storage.exists.assert_called_once_with(
            "optimized/background_mobile/homepage/backgrounds/mobile/current.webp"
        )

    @override_settings(OPTIMIZED_MEDIA_ENABLED=True)
    def test_background_url_uses_existing_optimized_variant(self):
        image = SimpleNamespace(
            name="landing_pages/backgrounds/desktop/current.jpg",
            url="/media/landing_pages/backgrounds/desktop/current.jpg",
        )

        with patch("core.media_optimization.default_storage") as storage:
            storage.exists.return_value = True
            storage.url.return_value = (
                "/media/optimized/background_desktop/"
                "landing_pages/backgrounds/desktop/current.webp"
            )

            result = get_safe_background_image_url(image, "background_desktop")

        self.assertEqual(result, storage.url.return_value)
