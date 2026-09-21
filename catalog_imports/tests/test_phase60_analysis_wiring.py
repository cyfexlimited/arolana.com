from pathlib import Path

from django.test import SimpleTestCase


class Phase60AnalysisWiringTests(SimpleTestCase):
    def test_analysis_enriches_verified_specs_before_completion_audit(self):
        import catalog_imports.services.analysis as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        enrich_at = source.index("enrich_verified_draft_from_specs(final_draft)")
        completion_at = source.index("build_product_data_completion_report(")
        report_at = source.index('"product_data_completion": product_data_completion')
        self.assertLess(enrich_at, completion_at)
        self.assertLess(completion_at, report_at)
