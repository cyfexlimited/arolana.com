import io
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from catalog_imports.services.media_storage import normalize_to_marketplace_webp


class Phase5MediaStorageTests(SimpleTestCase):
    def test_generated_asset_is_normalized_to_square_webp(self):
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (1200, 900), "white").save(buf, format="PNG")
        output, width, height = normalize_to_marketplace_webp(buf.getvalue(), target_size=800)
        self.assertGreater(len(output), 100)
        self.assertEqual((width, height), (800, 800))
        image = Image.open(io.BytesIO(output))
        self.assertEqual(image.format, "WEBP")
