from django.test import RequestFactory, TestCase
from django.urls import reverse

from core.context_processors import _desktop_priority_categories, _main_categories
from core.local_cache import local_delete
from products.models import Category
from products.views import _category_hero_image, _mobile_category_payload


class CategoryNavigationTests(TestCase):
    def setUp(self):
        self.parent = Category.objects.create(
            name="Audio Visual Test",
            slug="audio-visual-test",
            order=1,
            is_active=True,
            background_image="categories/backgrounds/audio-visual-test.jpg",
        )
        for index in range(18):
            Category.objects.create(
                name=f"Active Child {index:02d}",
                slug=f"active-child-{index:02d}",
                parent=self.parent,
                order=index,
                is_active=True,
            )
        Category.objects.create(
            name="Inactive Child",
            slug="inactive-child",
            parent=self.parent,
            order=99,
            is_active=False,
        )

    def test_main_categories_prefetches_every_active_child(self):
        categories = _main_categories()
        parent = next(item for item in categories if item.pk == self.parent.pk)

        children = list(parent.children.all())

        self.assertEqual(len(children), 18)
        self.assertTrue(all(child.is_active for child in children))
        self.assertEqual(
            [child.order for child in children],
            list(range(18)),
        )

    def test_main_categories_does_not_cap_active_parent_departments(self):
        for index in range(11):
            Category.objects.create(
                name=f"Root Department {index:02d}",
                slug=f"root-department-{index:02d}",
                order=index + 10,
                is_active=True,
            )

        categories = _main_categories()

        self.assertEqual(len(categories), 12)

    def test_desktop_priority_categories_use_shared_ordered_hierarchy(self):
        first = Category.objects.create(
            name="First Priority Department",
            slug="first-priority-department",
            order=-2,
            is_navigation_featured=True,
            is_active=True,
        )
        Category.objects.create(
            name="Mega Menu Only Department",
            slug="mega-menu-only-department",
            order=-1,
            is_navigation_featured=False,
            is_active=True,
        )

        categories = _main_categories()
        priority_categories = _desktop_priority_categories(categories)

        self.assertEqual(priority_categories[0].pk, first.pk)
        self.assertEqual(
            [category.pk for category in priority_categories],
            [
                category.pk
                for category in categories
                if category.is_navigation_featured
            ],
        )
        self.assertNotIn(
            "mega-menu-only-department",
            {category.slug for category in priority_categories},
        )

    def test_desktop_mega_menu_and_mobile_drawer_share_every_category(self):
        mega_only = Category.objects.create(
            name="Mega Menu Only Department",
            slug="mega-menu-only-department",
            order=-1,
            is_navigation_featured=False,
            is_active=True,
        )
        mega_child = Category.objects.create(
            name="Mega Menu Child",
            slug="mega-menu-child",
            parent=mega_only,
            order=1,
            is_active=True,
        )
        local_delete("global_context:main_categories")

        response = self.client.get(
            f"/products/category/{self.parent.slug}/",
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        rail_html = html.split("data-desktop-category-rail", 1)[1].split(
            "data-all-categories-menu",
            1,
        )[0]
        all_categories_html = html.split("data-all-categories-menu", 1)[1].split(
            "</nav>",
            1,
        )[0]
        mobile_drawer_html = html.split("mobile-drawer-shell", 1)[1]

        self.assertIn(self.parent.name, rail_html)
        self.assertNotIn(mega_only.name, rail_html)
        self.assertIn(mega_only.name, all_categories_html)
        self.assertIn(mega_child.name, all_categories_html)
        self.assertIn(mega_only.name, mobile_drawer_html)
        self.assertIn(mega_child.name, mobile_drawer_html)
        self.assertIn('aria-label="Scroll categories left"', html)
        self.assertIn('aria-label="Scroll categories right"', html)
        self.assertIn("Shop by Department", mobile_drawer_html)
        self.assertGreaterEqual(
            html.count(reverse("products:category", args=[mega_child.slug])),
            2,
        )

    def test_mobile_payload_includes_all_active_children(self):
        request = RequestFactory().get("/api/mobile/home/")

        payload = _mobile_category_payload(request, self.parent)

        self.assertEqual(payload["children_count"], 18)
        self.assertEqual(len(payload["children"]), 18)
        self.assertNotIn(
            "inactive-child",
            {child["slug"] for child in payload["children"]},
        )

    def test_child_uses_parent_hero_when_own_images_are_missing(self):
        child = self.parent.children.get(slug="active-child-00")

        hero = _category_hero_image(child)

        self.assertEqual(hero.name, self.parent.background_image.name)

    def test_category_page_uses_original_when_optimized_hero_is_missing(self):
        response = self.client.get(
            f"/products/category/{self.parent.slug}/",
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "/media/categories/backgrounds/audio-visual-test.jpg",
        )
        self.assertNotContains(
            response,
            "/media/optimized/category_banner/categories/backgrounds/audio-visual-test.webp",
        )

    def test_category_page_has_branded_fallback_when_no_image_exists(self):
        category = Category.objects.create(
            name="No Image Category",
            slug="no-image-category",
            is_active=True,
        )

        response = self.client.get(
            f"/products/category/{category.slug}/",
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "/static/products/images/category-default.svg",
        )
