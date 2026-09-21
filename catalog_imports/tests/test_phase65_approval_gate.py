from pathlib import Path

from django.test import SimpleTestCase


class Phase65ApprovalGateTests(SimpleTestCase):
    def test_media_review_service_checks_current_role_support(self):
        import catalog_imports.services.media_review as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        self.assertIn("reference_support_for_view(candidate.item, candidate.view_role)", source)
        self.assertIn("visually role-matched official", source)

    def test_main_is_exempt_and_creative_path_remains_available(self):
        import catalog_imports.services.media_review as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        self.assertIn("VIEW_MAIN) != ImportMediaCandidate.VIEW_MAIN", source)
        self.assertIn("not creative", source)
