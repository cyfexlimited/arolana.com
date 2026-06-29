from django.test import TestCase

from products.models import Category


class MobileHomePayloadTests(TestCase):
    def test_home_payload_serializes_categories_without_images(self):
        Category.objects.create(
            name="Investor Demo Category",
            slug="investor-demo-category",
            is_active=True,
        )

        response = self.client.get("/api/mobile/home/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        categories = payload.get("mega_categories") or payload.get("categories") or []
        category = next(
            item for item in categories if item.get("slug") == "investor-demo-category"
        )
        self.assertIn("thumbnail_url", category)
        self.assertIn("image_url", category)
        self.assertIn("original_url", category)
        self.assertIn("category_image_url", category)
        self.assertIn("category_banner_url", category)
        self.assertIn("category_icon", category)
