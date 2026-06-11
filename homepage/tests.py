from types import SimpleNamespace

from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from core.local_cache import local_delete
from homepage.models import HomepageBanner, HomepageCategory
from homepage.templatetags.homepage_tags import (
    homepage_banner,
    homepage_categories,
)
from products.models import Category


class StorefrontUrlTests(SimpleTestCase):
    def test_storefront_namespaces_prefer_public_routes(self):
        self.assertEqual(reverse("products:list"), "/products/")
        self.assertEqual(
            reverse("search_ai:advanced_search"),
            "/search/advanced/",
        )


class HomepageCategoryTests(TestCase):
    def setUp(self):
        local_delete("homepage:categories")

    def test_only_active_categories_with_valid_relations_are_rendered(self):
        active_category = Category.objects.create(
            name="Active",
            slug="active",
            is_active=True,
        )
        inactive_category = Category.objects.create(
            name="Inactive",
            slug="inactive",
            is_active=False,
        )
        active_homepage_category = HomepageCategory.objects.create(
            category=active_category,
            display_order=1,
        )
        HomepageCategory.objects.create(
            category=inactive_category,
            display_order=2,
        )
        HomepageCategory.objects.create(
            category=None,
            display_order=3,
        )

        context = homepage_categories(
            {"request": RequestFactory().get("/")}
        )

        self.assertEqual(context["categories"], [active_homepage_category])


class HomepageBannerTests(TestCase):
    def setUp(self):
        local_delete("homepage:banners:v4:top:all")

    def test_full_width_setting_is_exposed_to_template(self):
        HomepageBanner.objects.create(
            title="Full width",
            placement="top",
            full_width=True,
        )

        context = homepage_banner(
            {"request": RequestFactory().get("/")},
            "top",
        )

        self.assertTrue(context["has_full_width_banner"])

    @override_settings(OPTIMIZED_MEDIA_ENABLED=False)
    def test_image_only_banner_uses_full_strength_background_and_click_target(self):
        banner = HomepageBanner(
            title="Image promotion",
            button_text="Shop now",
            button_url="/products/",
            banner_style="image_only",
            content_layout="image_only",
            background_opacity=0.2,
        )
        banner.background_image = SimpleNamespace(
            image=SimpleNamespace(
                name="homepage/banner.gif",
                url="/media/homepage/banner.gif",
            )
        )
        banner.left_images = []
        banner.center_images = []
        banner.right_images = []

        html = render_to_string(
            "homepage/banner.html",
            {
                "banners": [banner],
                "placement": "top",
                "has_full_width_banner": False,
            },
        )

        self.assertIn("ah-banner-image-only-active", html)
        self.assertIn("--ah-banner-bg-opacity: 1;", html)
        self.assertIn('class="ah-banner-image-only-link"', html)
