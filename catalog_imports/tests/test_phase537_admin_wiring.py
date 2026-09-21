from pathlib import Path

from django.test import SimpleTestCase


class Phase537AdminWiringTests(SimpleTestCase):
    def test_generate_view_stops_only_bulk_queue_after_sufficient_media(self):
        import catalog_imports.admin as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        self.assertIn("media_completion = practical_media_completion(obj)", source)
        self.assertIn('not media_completion["stop_bulk_generation"]', source)
        self.assertIn('"optional_after_sufficient"', source)
        self.assertIn('"product_change_url"', source)
