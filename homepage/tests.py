from decimal import Decimal
from datetime import timedelta
from types import SimpleNamespace

from django.contrib import admin
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from core.local_cache import local_delete
from homepage.models import (
    HomepageBanner,
    HomepageCategory,
    HomepageSection,
    HomepageSectionProduct,
)
from homepage.templatetags.homepage_tags import (
    homepage_banner,
    homepage_categories,
    homepage_sections,
)
from products.models import Category, Product
from products.ranking import order_storefront_products
from vendors.models import VendorProfile


class StorefrontUrlTests(SimpleTestCase):
    def test_storefront_namespaces_prefer_public_routes(self):
        self.assertEqual(reverse("products:list"), "/products/")
        self.assertEqual(
            reverse("search_ai:advanced_search"),
            "/search/advanced/",
        )

    def test_homepage_section_admin_exposes_structure_controls(self):
        model_admin = admin.site._registry[HomepageSection]
        fieldset_fields = {
            field
            for _, options in model_admin.fieldsets
            for row in options["fields"]
            for field in (row if isinstance(row, tuple) else (row,))
        }

        self.assertTrue({
            "layout_style",
            "sort_mode",
            "category",
            "brand",
            "use_subscription_priority",
            "view_all_text",
            "accent_color",
            "show_add_to_cart",
        }.issubset(fieldset_fields))
        self.assertEqual(
            model_admin.inlines[0].model,
            HomepageSectionProduct,
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


class HomepageProductSectionTests(TestCase):
    def setUp(self):
        local_delete("homepage:sections")
        self.category = Category.objects.create(
            name="Section Products",
            slug="section-products",
            is_active=True,
        )

    def create_vendor(self, username, priority=0, active=False, expired=False):
        user = User.objects.create_user(
            username=username,
            email=f"{username}@example.org",
            password="StrongPass1!",
            user_type="vendor",
        )
        expiry = timezone.now() + timedelta(days=-1 if expired else 30)
        VendorProfile.objects.create(
            user=user,
            store_name=f"{username.title()} Store",
            store_slug=f"{username}-store",
            description="Test vendor",
            address_line_1="1 Marketplace Road",
            city="Lagos",
            state="Lagos",
            country="Nigeria",
            approval_status="approved",
            subscription_tier="enterprise" if priority else "free",
            subscription_active=active,
            subscription_expires_at=expiry if active else None,
            subscription_expiry=expiry if active else None,
            can_show_on_homepage=bool(priority),
            priority_score=priority,
        )
        return user

    def create_product(self, vendor, slug, **overrides):
        values = {
            "sku": f"SKU-{slug}",
            "name": slug.replace("-", " ").title(),
            "slug": slug,
            "description": "Homepage product",
            "category": self.category,
            "vendor": vendor,
            "price": Decimal("100.00"),
            "stock_quantity": 10,
            "is_active": True,
            "approval_status": "approved",
            "is_featured": True,
        }
        values.update(overrides)
        return Product.objects.create(**values)

    def test_active_higher_plan_receives_homepage_priority(self):
        free_vendor = self.create_vendor("free-vendor")
        paid_vendor = self.create_vendor("paid-vendor", priority=100, active=True)
        expired_vendor = self.create_vendor(
            "expired-vendor",
            priority=100,
            active=True,
            expired=True,
        )
        free_product = self.create_product(free_vendor, "free-product")
        paid_product = self.create_product(paid_vendor, "paid-product")
        expired_product = self.create_product(expired_vendor, "expired-product")
        section = HomepageSection.objects.create(
            title="Featured Products",
            section_type="featured",
            layout_style="compact",
            products_limit=3,
        )

        products = section.get_products()

        self.assertEqual(products[0], paid_product)
        self.assertCountEqual(products[1:], [free_product, expired_product])

    def test_curated_products_stay_first_and_admin_layout_is_rendered(self):
        free_vendor = self.create_vendor("curated-vendor")
        paid_vendor = self.create_vendor("automatic-vendor", priority=100, active=True)
        curated = self.create_product(free_vendor, "curated-product")
        automatic = self.create_product(paid_vendor, "automatic-product")
        section = HomepageSection.objects.create(
            title="Admin Picks",
            subtitle="Chosen in the homepage admin",
            section_type="featured",
            layout_style="editorial",
            products_limit=2,
            view_all_text="Browse Picks",
            accent_color="#FF7A00",
        )
        HomepageSectionProduct.objects.create(
            section=section,
            product=curated,
            display_order=1,
        )

        context = homepage_sections({"request": RequestFactory().get("/")})
        html = render_to_string("homepage/sections.html", context)

        self.assertEqual(context["sections"][0].products, [curated, automatic])
        self.assertIn("ah-trending-section", html)
        self.assertIn("Browse Picks", html)
        self.assertIn("--ah-section-accent: #FF7A00", html)

    def test_market_grid_renders_vendor_identity_and_tier_once(self):
        HomepageSection.objects.all().delete()
        vendor = self.create_vendor("single-vendor", priority=100, active=True)
        vendor.vendor_profile.is_verified = True
        vendor.vendor_profile.save(update_fields=["is_verified"])
        self.create_product(vendor, "single-vendor-product")
        HomepageSection.objects.create(
            title="New Arrivals",
            section_type="new_arrivals",
            layout_style="market_grid",
            products_limit=1,
            show_vendor=True,
            show_subscription_badge=True,
        )

        context = homepage_sections({"request": RequestFactory().get("/")})
        html = render_to_string("homepage/sections.html", context)

        self.assertEqual(html.count("Single-Vendor Store"), 1)
        self.assertEqual(html.count("Verified"), 1)
        self.assertEqual(html.count("Enterprise Vendor"), 1)

    def test_storefront_order_keeps_explicit_sort_then_plan_priority(self):
        free_vendor = self.create_vendor("sort-free")
        paid_vendor = self.create_vendor("sort-paid", priority=100, active=True)
        free_product = self.create_product(
            free_vendor,
            "free-newer",
            sales_count=20,
        )
        paid_product = self.create_product(
            paid_vendor,
            "paid-equal-sales",
            sales_count=20,
        )

        products = list(
            order_storefront_products(
                Product.objects.filter(pk__in=[free_product.pk, paid_product.pk]),
                "-sales_count",
            )
        )

        self.assertEqual(products[0], paid_product)
