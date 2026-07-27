from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.http import HttpResponse
from django.template import Context, Template
from django.test import Client, RequestFactory, SimpleTestCase, TestCase, override_settings

from . import local_cache
from .context_processors import global_context
from .deployment_health import readiness_status
from .media_optimization import PRESETS, get_optimized_image_url, get_safe_background_image_url
from .middleware import ArolanaRateLimitMiddleware, ArolanaSecurityHeadersMiddleware
from .models import HomePageAppearance, SiteSettings


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
        SECURE_REDIRECT_EXEMPT=[r"^health/$", r"^health/live/$", r"^health/ready/$"],
    )
    def test_health_check_is_not_redirected_by_https_enforcement(self):
        response = Client().get("/health/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    @override_settings(
        DEBUG=False,
        SECURE_SSL_REDIRECT=True,
        SECURE_REDIRECT_EXEMPT=[r"^health/$", r"^health/live/$", r"^health/ready/$"],
    )
    def test_liveness_and_readiness_checks_are_not_redirected(self):
        client = Client()

        live_response = client.get("/health/live/")
        self.assertEqual(live_response.status_code, 200)
        self.assertEqual(live_response.json()["check"], "live")

        with patch("arolana_config.urls.readiness_status", return_value=(True, {"status": "ready"})):
            ready_response = client.get("/health/ready/")

        self.assertEqual(ready_response.status_code, 200)
        self.assertEqual(ready_response.json()["status"], "ready")


class DeploymentReadinessTests(TestCase):
    def setUp(self):
        SiteSettings.objects.create(site_name="Arolana Production")
        HomePageAppearance.objects.create(
            title="Production Homepage",
            desktop_position="top center",
            mobile_position="center top",
        )

    @override_settings(
        AROLANA_CACHE_REQUIRED=False,
        AROLANA_MEDIA_STORAGE_REQUIRED=False,
        AROLANA_DEPLOYMENT_ENVIRONMENT="test",
        AROLANA_CACHE_KEY_PREFIX="arolana:test",
        AWS_STORAGE_BUCKET_NAME="",
        AROLANA_PUBLIC_MEDIA_BASE_URL="http://testserver/media/",
    )
    def test_readiness_returns_ready_when_database_migrations_config_cache_and_media_pass(self):
        with patch("core.deployment_health._check_migrations") as migrations_check:
            ready, payload = readiness_status()

        self.assertTrue(ready)
        self.assertEqual(payload["status"], "ready")
        migrations_check.assert_called_once()
        self.assertTrue(payload["checks"]["critical_configuration"]["ok"])

    @override_settings(
        AROLANA_CACHE_REQUIRED=False,
        AROLANA_MEDIA_STORAGE_REQUIRED=False,
        AROLANA_DEPLOYMENT_ENVIRONMENT="test",
        AROLANA_CACHE_KEY_PREFIX="arolana:test",
        AWS_STORAGE_BUCKET_NAME="",
        AROLANA_PUBLIC_MEDIA_BASE_URL="http://testserver/media/",
    )
    def test_readiness_returns_not_ready_when_required_migrations_are_pending(self):
        with patch(
            "core.deployment_health._check_migrations",
            side_effect=RuntimeError("required migrations are not applied"),
        ):
            ready, payload = readiness_status()

        self.assertFalse(ready)
        self.assertEqual(payload["status"], "not_ready")
        self.assertEqual(payload["message"], "required migrations are not applied")

    @override_settings(
        AROLANA_CACHE_REQUIRED=False,
        AROLANA_MEDIA_STORAGE_REQUIRED=False,
        AROLANA_DEPLOYMENT_ENVIRONMENT="staging",
        AROLANA_CACHE_KEY_PREFIX="arolana",
        AWS_STORAGE_BUCKET_NAME="shared-bucket",
        AROLANA_PUBLIC_MEDIA_BASE_URL="https://arolana.com/media/",
    )
    def test_readiness_blocks_non_production_environment_with_production_resource_hints(self):
        with patch("core.deployment_health._check_migrations"):
            ready, payload = readiness_status()

        self.assertFalse(ready)
        self.assertEqual(payload["status"], "not_ready")
        self.assertEqual(payload["message"], "deployment environment isolation is not ready")
        problems = payload["checks"]["environment_isolation"]["problems"]
        self.assertIn("cache key prefix does not include deployment environment", problems)


class ConfigurationFallbackReadPathTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def tearDown(self):
        cache.clear()
        local_cache._CACHE.clear()

    def _request(self):
        request = self.factory.get("/")
        request.user = AnonymousUser()
        request.session = {}
        return request

    def test_singleton_loaders_do_not_create_defaults_unless_explicitly_requested(self):
        self.assertEqual(SiteSettings.objects.count(), 0)
        self.assertEqual(HomePageAppearance.objects.count(), 0)

        site_settings = SiteSettings.load(create=False)
        homepage_appearance = HomePageAppearance.load(create=False)

        self.assertIsNone(site_settings.pk)
        self.assertEqual(homepage_appearance.pk, 1)
        self.assertEqual(SiteSettings.objects.count(), 0)
        self.assertEqual(HomePageAppearance.objects.count(), 0)

    def test_global_context_cache_miss_reads_existing_authoritative_records(self):
        site_settings = SiteSettings.objects.create(
            site_name="Production Arolana",
            site_tagline="Real production content",
            primary_color="#123456",
        )
        homepage_appearance = HomePageAppearance.objects.create(
            title="Production Hero",
            desktop_position="top center",
            mobile_position="center top",
            make_sections_glass=False,
        )
        cache.clear()
        local_cache._CACHE.clear()

        context = global_context(self._request())

        self.assertEqual(context["site_settings"].pk, site_settings.pk)
        self.assertEqual(context["site_settings"].site_name, "Production Arolana")
        self.assertEqual(context["site_settings"].primary_color, "#123456")
        self.assertEqual(context["homepage_appearance"].pk, homepage_appearance.pk)
        self.assertEqual(context["homepage_appearance"].desktop_position, "top center")
        self.assertFalse(context["homepage_appearance"].make_sections_glass)
        self.assertEqual(SiteSettings.objects.count(), 1)
        self.assertEqual(HomePageAppearance.objects.count(), 1)

    def test_global_context_cache_miss_does_not_create_default_records(self):
        cache.clear()
        local_cache._CACHE.clear()

        context = global_context(self._request())

        self.assertEqual(context["site_settings"].site_name, "Arolana")
        self.assertIsNone(context["site_settings"].pk)
        self.assertEqual(context["homepage_appearance"].pk, 1)
        self.assertEqual(SiteSettings.objects.count(), 0)
        self.assertEqual(HomePageAppearance.objects.count(), 0)


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
