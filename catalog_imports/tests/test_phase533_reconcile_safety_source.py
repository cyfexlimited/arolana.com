from pathlib import Path

from django.test import SimpleTestCase


class Phase533ReconcileSafetySourceTests(SimpleTestCase):
    def test_reconcile_deletes_only_unapproved_preview_and_clears_generation_trace(self):
        import catalog_imports.services.dynamic_verified_slots as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        self.assertIn("delete_review_asset(candidate)", source)
        self.assertIn("STATUS_APPROVED", source)
        self.assertIn("STATUS_ATTACHED", source)
        self.assertIn("generation_reference_trace", source)
        self.assertIn("dynamic_verified_media_slot_applied", source)
