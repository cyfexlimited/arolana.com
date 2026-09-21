from pathlib import Path

from django.test import SimpleTestCase


class Phase532SonyDiagnosticRegressionTests(SimpleTestCase):
    def test_acquisition_uses_selected_page_queue_not_pages_slice(self):
        import catalog_imports.services.official_media_acquisition as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        self.assertIn("page_queue = _select_media_page_queue(", source)
        self.assertIn("for page in page_queue:", source)
        self.assertNotIn("for page in pages[:12]:", source)
        self.assertIn('"selected_page_queue": page_queue', source)
