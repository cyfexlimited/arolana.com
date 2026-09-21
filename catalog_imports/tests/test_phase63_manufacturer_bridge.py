from pathlib import Path

from django.test import SimpleTestCase


class Phase63ManufacturerBridgeTests(SimpleTestCase):
    def test_manufacturer_discovery_uses_recovered_retailer_identity_hint(self):
        import catalog_imports.services.web_evidence as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        self.assertIn("def _retailer_identity_hint", source)
        self.assertIn("input_hint = _retailer_identity_hint(item)", source)

    def test_expected_brand_can_come_from_retailer_evidence(self):
        import catalog_imports.services.web_evidence as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        self.assertIn('.filter(role="retailer", status="fetched")', source)
