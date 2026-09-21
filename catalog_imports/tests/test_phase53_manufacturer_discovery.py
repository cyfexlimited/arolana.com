from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from catalog_imports.services.web_evidence import (
    _host_looks_like_brand,
    discover_manufacturer_web_identity,
)


class Phase53ManufacturerDiscoveryTests(SimpleTestCase):
    def test_brand_domain_heuristic_accepts_sony_and_logitech(self):
        self.assertTrue(_host_looks_like_brand("pro.sony", "Sony"))
        self.assertTrue(_host_looks_like_brand("www.logitech.com", "Logitech"))

    def test_brand_domain_heuristic_rejects_retailer(self):
        self.assertFalse(_host_looks_like_brand("bhphotovideo.com", "Sony"))

    @patch("catalog_imports.services.web_evidence._provider_request")
    def test_discovery_requires_exact_model_and_official_brand_host(self, provider):
        provider.return_value = {
            "output": [
                {
                    "type": "web_search_call",
                    "action": {
                        "sources": [
                            {
                                "url": "https://pro.sony/products/handheld-camcorders/pxw-z200"
                            }
                        ]
                    },
                },
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": (
                                '{"exact_identity_confirmed":true,'
                                '"official_product_url":"https://pro.sony/products/handheld-camcorders/pxw-z200",'
                                '"official_domain":"pro.sony",'
                                '"name":"Sony PXW-Z200",'
                                '"brand":"Sony",'
                                '"manufacturer":"Sony",'
                                '"model":"PXW-Z200",'
                                '"manufacturer_sku":"PXW-Z200",'
                                '"gtin":"","ean":"","upc":"","evidence_urls":[]}'
                            ),
                        }
                    ],
                },
            ]
        }

        item = SimpleNamespace(
            input_value=(
                "https://www.bhphotovideo.com/c/product/1848319-REG/"
                "sony_pxw_z200_4k_1_cmos.html"
            ),
            source_url=(
                "https://www.bhphotovideo.com/c/product/1848319-REG/"
                "sony_pxw_z200_4k_1_cmos.html"
            ),
            manufacturer_url="",
            secondary_evidence_urls="",
            normalized_payload={},
            batch=SimpleNamespace(
                default_brand=SimpleNamespace(
                    name="Sony",
                    website="",
                )
            ),
        )

        result = discover_manufacturer_web_identity(item)
        self.assertTrue(result["verified"])
        self.assertEqual(result["official_domain"], "pro.sony")
        self.assertTrue(result["identity"]["identifier_match"])
