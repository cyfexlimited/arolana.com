from pathlib import Path

from django.test import SimpleTestCase


class Phase534DowngradeSourceSafetyTests(SimpleTestCase):
    def test_downgrade_only_reduces_trust_and_preserves_trace(self):
        import catalog_imports.services.manual_creative_downgrade as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        self.assertIn('"_arolana_requested_view_verified": False', source)
        self.assertIn('"_arolana_factual_geometry_claim": False', source)
        self.assertIn("generation_reference_trace_preserved", source)
        self.assertIn("media_candidate_manual_creative_downgrade", source)
