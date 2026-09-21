import json
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from catalog_imports.services.web_evidence import (
    _parse_json_object,
    _sanitize_payload,
    deterministic_identity_check,
    trusted_manufacturer_domains,
)


class Phase52WebEvidenceTests(SimpleTestCase):
    def test_sony_style_model_in_url_passes_deterministic_identity(self):
        payload = {
            "exact_identity_confirmed": True,
            "name": "Sony PXW-Z200 4K XDCAM Camcorder",
            "brand": "Sony",
            "model": "PXW-Z200",
        }
        result = deterministic_identity_check(
            "https://www.bhphotovideo.com/c/product/1848319-REG/sony_pxw_z200_4k_1_cmos.html",
            payload,
            expected_brand="Sony",
        )
        self.assertTrue(result["passed"])
        self.assertTrue(result["identifier_match"])

    def test_wrong_model_is_rejected_even_if_provider_says_confirmed(self):
        payload = {
            "exact_identity_confirmed": True,
            "name": "Sony PXW-Z190 Camcorder",
            "brand": "Sony",
            "model": "PXW-Z190",
        }
        result = deterministic_identity_check(
            "https://retailer.example/sony_pxw_z200_camera.html",
            payload,
            expected_brand="Sony",
        )
        self.assertFalse(result["passed"])

    def test_sanitizer_drops_nonmanufacturer_urls_and_price(self):
        clean = _sanitize_payload(
            {
                "exact_identity_confirmed": True,
                "official_product_url": "https://pro.sony/products/pxw-z200",
                "name": "PXW-Z200",
                "brand": "Sony",
                "model": "PXW-Z200",
                "price": "999",
                "source_price": "999",
                "evidence_urls": [
                    "https://pro.sony/products/pxw-z200",
                    "https://random-retailer.example/pxw-z200",
                ],
            },
            ["pro.sony"],
            [],
        )
        self.assertEqual(clean["evidence_urls"], ["https://pro.sony/products/pxw-z200"])
        self.assertNotIn("price", clean)
        self.assertNotIn("source_price", clean)

    def test_json_fence_is_tolerated(self):
        value = _parse_json_object('```json\\n{"exact_identity_confirmed": true}\\n```')
        self.assertTrue(value["exact_identity_confirmed"])

    def test_domains_can_come_from_manual_manufacturer_and_brand_website(self):
        item = SimpleNamespace(
            manufacturer_url="https://pro.sony/en_MV/pdf/pxw-z200",
            secondary_evidence_urls="https://www.sony.com/support/pxw-z200",
            batch=SimpleNamespace(
                default_brand=SimpleNamespace(website="https://www.sony.com")
            ),
        )
        domains = trusted_manufacturer_domains(item, profile=None)
        self.assertIn("pro.sony", domains)
        self.assertIn("sony.com", domains)
