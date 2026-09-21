from types import SimpleNamespace

from django.test import SimpleTestCase

from catalog_imports.services.content import (
    build_description_html,
    build_seo,
)


class Phase60ContentTests(SimpleTestCase):
    def _draft(self):
        return SimpleNamespace(
            name="PXW-Z200",
            brand="Sony",
            manufacturer="Sony",
            model="PXW-Z200",
            manufacturer_sku="",
            category="Professional Camcorder",
            subcategory="",
            key_features=["4K recording", "20x optical zoom"],
            package_contents=["Camcorder", "Power adapter"],
            warranty={},
            weight="2.0",
            weight_unit="kg",
            dimensions_length="175",
            dimensions_width="201",
            dimensions_height="371",
            dimension_unit="mm",
            tags=[],
        )

    def test_description_is_arolana_original_and_product_focused(self):
        html = build_description_html(self._draft())
        self.assertIn("Key features", html)
        self.assertIn("Physical details", html)
        self.assertIn("What's in the box", html)
        self.assertNotIn("verified product information", html.lower())

    def test_seo_is_bounded(self):
        seo = build_seo(self._draft())
        self.assertLessEqual(len(seo["meta_title"]), 60)
        self.assertLessEqual(len(seo["meta_description"]), 160)
        self.assertLessEqual(len(seo["meta_keywords"]), 200)
