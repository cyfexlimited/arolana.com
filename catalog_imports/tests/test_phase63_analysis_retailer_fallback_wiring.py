from pathlib import Path

from django.test import SimpleTestCase


class Phase63AnalysisRetailerFallbackWiringTests(SimpleTestCase):
    def test_blocked_direct_source_uses_restricted_retailer_web_fallback(self):
        import catalog_imports.services.analysis as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        self.assertIn("retrieve_retailer_web_evidence", source)
        self.assertIn("if retailer_draft is None and source_access_error:", source)
        self.assertIn('"retailer_web_fallback": retailer_web_report', source)
        self.assertIn('"recovered_via_retailer_web_search"', source)

    def test_retailer_web_price_remains_source_price_not_manufacturer_price(self):
        import catalog_imports.services.analysis as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        self.assertIn('"verified_via_retailer_web_search"', source)
        self.assertIn("retailer_draft.source_price", source)
