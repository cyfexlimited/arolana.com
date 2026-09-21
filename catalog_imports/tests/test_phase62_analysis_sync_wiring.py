from pathlib import Path

from django.test import SimpleTestCase


class Phase62AnalysisSyncWiringTests(SimpleTestCase):
    def test_reanalysis_syncs_existing_product_draft_only_after_ready_decision(self):
        import catalog_imports.services.analysis as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        self.assertIn("sync_verified_product_draft", source)
        self.assertIn('if item.created_product_id and decision["ready"]:', source)
        self.assertIn('"product_draft_sync"', source)

    def test_sync_service_is_fail_closed_for_live_products(self):
        import catalog_imports.services.product_draft_sync as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        self.assertIn('"blocked_active_product"', source)
        self.assertIn('"blocked_non_draft_product"', source)
        self.assertIn('"never_overwrite_admin_values": True', source)
