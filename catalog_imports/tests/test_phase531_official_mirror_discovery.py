from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from catalog_imports.services.web_evidence import discover_official_media_mirrors


class Phase531OfficialMirrorDiscoveryTests(SimpleTestCase):
    @patch("catalog_imports.services.web_evidence._provider_request")
    def test_verified_regional_brand_page_is_admitted(self, provider):
        provider.return_value = {
            "output": [
                {
                    "type": "web_search_call",
                    "action": {
                        "sources": [
                            {
                                "url": "https://www.sony.com.tw/corporate/home/NewsCenter/Detail/PXW-Z200"
                            }
                        ]
                    },
                },
                {
                    "type": "message",
                    "content": [{
                        "type": "output_text",
                        "text": (
                            '{"exact_identity_confirmed":true,'
                            '"brand":"Sony","model":"PXW-Z200",'
                            '"pages":[{"url":"https://www.sony.com.tw/corporate/home/NewsCenter/Detail/PXW-Z200",'
                            '"kind":"corporate_news","exact_model_confirmed":true}]}'
                        ),
                    }],
                },
            ]
        }

        item = SimpleNamespace(
            input_value="https://retailer.example/sony_pxw_z200_camera",
            source_url="https://retailer.example/sony_pxw_z200_camera",
            normalized_payload={
                "name": "Sony PXW-Z200",
                "brand": "Sony",
                "manufacturer": "Sony",
                "model": "PXW-Z200",
                "manufacturer_sku": "PXW-Z200",
            },
            batch=SimpleNamespace(
                default_brand=SimpleNamespace(name="Sony", website="")
            ),
        )

        result = discover_official_media_mirrors(item)
        self.assertTrue(result["verified"])
        self.assertEqual(len(result["pages"]), 1)
        self.assertEqual(result["pages"][0]["host"], "www.sony.com.tw")
