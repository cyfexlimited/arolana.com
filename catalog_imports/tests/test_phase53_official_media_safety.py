from types import SimpleNamespace

from django.test import SimpleTestCase

from catalog_imports.services.official_media_acquisition import (
    _page_exact_identity,
)


class Phase53OfficialMediaSafetyTests(SimpleTestCase):
    def test_exact_model_in_official_page_can_confirm_sparse_media_page(self):
        item = SimpleNamespace(
            input_value="https://retailer.example/sony_pxw_z200_camera.html",
            normalized_payload={
                "name": "Sony PXW-Z200",
                "brand": "Sony",
                "manufacturer": "Sony",
                "model": "PXW-Z200",
                "manufacturer_sku": "PXW-Z200",
            },
        )
        draft = SimpleNamespace(
            name="Sony PXW-Z200 Product Gallery",
            brand="Sony",
            manufacturer="Sony",
            model="",
            manufacturer_sku="",
            gtin="",
            ean="",
            upc="",
        )
        result = _page_exact_identity(
            item,
            draft,
            "https://pro.sony/media/pxw-z200/gallery",
            "Sony",
        )
        self.assertTrue(result["passed"])
