from pathlib import Path

from django.test import SimpleTestCase


class Phase64MediaInlineLabelTests(SimpleTestCase):
    def test_import_item_inline_uses_profile_label_and_review_state(self):
        import catalog_imports.admin as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        self.assertIn('"media_view_label"', source)
        self.assertIn('"review_state"', source)
        self.assertIn("def _candidate_review_state", source)
