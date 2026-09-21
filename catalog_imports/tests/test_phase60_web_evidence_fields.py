from pathlib import Path

from django.test import SimpleTestCase


class Phase60WebEvidenceFieldTests(SimpleTestCase):
    def test_web_evidence_requests_physical_warranty_and_package_facts(self):
        import catalog_imports.services.web_evidence as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        for token in (
            '"country_of_origin"',
            '"weight"',
            '"dimensions_length"',
            '"warranty"',
            '"shipping"',
            "NEVER invent delivery days",
        ):
            self.assertIn(token, source)

    def test_draft_data_passes_new_fields_to_universal_draft(self):
        import catalog_imports.services.web_evidence as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        self.assertIn('"country_of_origin", "manufacturer_address", "certifications"', source)
        self.assertIn('"warranty", "shipping"', source)
