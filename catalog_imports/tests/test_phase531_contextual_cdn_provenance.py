from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from catalog_imports.services.official_media_acquisition import (
    _extract_contextual_official_images,
)


class Phase531ContextualCDNProvenanceTests(SimpleTestCase):
    @patch("catalog_imports.services.official_media_acquisition._probe_context_image")
    def test_exact_model_embedded_cdn_image_can_support_main(self, probe):
        probe.return_value = {
            "url": "https://cdn.example.net/assets/a1b2c3",
            "content_type": "image/jpeg",
            "width": 1200,
            "height": 800,
        }
        html = (
            '<html><body>'
            '<h2>Sony PXW-Z200</h2>'
            '<img src="https://cdn.example.net/assets/a1b2c3" '
            'alt="Sony PXW-Z200 professional camcorder">'
            '</body></html>'
        )

        rows = _extract_contextual_official_images(
            SimpleNamespace(),
            html=html,
            page_url="https://www.sony.com.tw/product/PXW-Z200",
            expected_model="PXW-Z200",
        )
        self.assertEqual(len(rows), 1)
        self.assertIn("arolana_verified=1", rows[0]["reference_url"])
        self.assertIn("arolana_view=main", rows[0]["reference_url"])

    @patch("catalog_imports.services.official_media_acquisition._probe_context_image")
    def test_rear_context_remains_explicitly_rear(self, probe):
        probe.return_value = {
            "url": "https://cdn.example.net/z200-rear.jpg",
            "content_type": "image/jpeg",
            "width": 1400,
            "height": 900,
        }
        html = (
            '<html><body>'
            '<h3>PXW-Z200 rear view and media slots</h3>'
            '<img src="https://cdn.example.net/z200-rear.jpg" '
            'alt="3/4 rear view of PXW-Z200 camera with dual media slots">'
            '</body></html>'
        )

        rows = _extract_contextual_official_images(
            SimpleNamespace(),
            html=html,
            page_url="https://pro.sony/product/PXW-Z200",
            expected_model="PXW-Z200",
        )
        self.assertEqual(len(rows), 1)
        self.assertIn("back", rows[0]["reference_url"])
        self.assertIn("ports_detail", rows[0]["reference_url"])
