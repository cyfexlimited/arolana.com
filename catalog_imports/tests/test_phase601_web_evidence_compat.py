from pathlib import Path

from django.test import SimpleTestCase


class Phase601WebEvidenceCompatibilityTests(SimpleTestCase):
    def test_phase53_media_discovery_exports_are_preserved(self):
        from catalog_imports.services import web_evidence

        self.assertTrue(callable(web_evidence.discover_manufacturer_web_identity))
        self.assertTrue(callable(web_evidence.discover_official_media_mirrors))
        self.assertTrue(callable(web_evidence.discover_official_media_sources))
        self.assertTrue(callable(web_evidence.retrieve_manufacturer_web_evidence))

    def test_phase60_product_data_fields_are_still_present(self):
        from catalog_imports.services import web_evidence

        source = Path(web_evidence.__file__).read_text(encoding="utf-8")
        self.assertIn('"country_of_origin"', source)
        self.assertIn('"weight"', source)
        self.assertIn('"warranty"', source)
        self.assertIn('"shipping"', source)
        self.assertIn("NEVER invent delivery days", source)

    def test_retailer_price_boundary_is_still_preserved(self):
        from catalog_imports.services import web_evidence

        source = Path(web_evidence.__file__).read_text(encoding="utf-8")
        self.assertIn(
            'for forbidden in ("price", "source_price", "currency", "source_currency", "msrp")',
            source,
        )
