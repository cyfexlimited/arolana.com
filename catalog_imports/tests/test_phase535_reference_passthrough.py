from pathlib import Path

from django.test import SimpleTestCase


class Phase535ReferencePassthroughTests(SimpleTestCase):
    def test_manufacturer_reference_reader_uses_semantic_reference_urls(self):
        import catalog_imports.services.media_references as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        self.assertIn("def _semantic_image_urls", source)
        self.assertIn(
            "for url in _semantic_image_urls(evidence.extracted_payload):",
            source,
        )
