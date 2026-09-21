from pathlib import Path

from django.test import SimpleTestCase


class Phase65ApprovedDowngradeTests(SimpleTestCase):
    def test_unattached_approved_candidate_can_be_demoted_for_re_review(self):
        import catalog_imports.services.manual_creative_downgrade as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        self.assertIn("ImportMediaCandidate.STATUS_APPROVED", source)
        self.assertIn("candidate.status = ImportMediaCandidate.STATUS_READY_REVIEW", source)
        self.assertIn("candidate.selected_for_product = False", source)
        self.assertIn("candidate.approved_at = None", source)
