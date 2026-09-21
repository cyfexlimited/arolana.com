from pathlib import Path

from django.test import SimpleTestCase


class Phase63NoAntiBotBypassTests(SimpleTestCase):
    def test_retailer_fallback_uses_existing_web_search_provider_not_fetch_bypass(self):
        import catalog_imports.services.web_evidence as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        start = source.index("def retrieve_retailer_web_evidence")
        block = source[start:start + 9000]
        self.assertIn("_provider_request(", block)
        self.assertNotIn("fetch_html(", block)
        self.assertIn("already-indexed public search evidence", block)
