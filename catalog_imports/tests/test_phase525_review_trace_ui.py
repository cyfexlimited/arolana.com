from pathlib import Path

from django.template.loader import get_template
from django.test import SimpleTestCase


class Phase525ReviewAndAttemptUITests(SimpleTestCase):
    def test_review_template_has_text_grounding_audit_not_legacy_copy(self):
        template = get_template(
            "admin/catalog_imports/importitem/media_review.html"
        )
        source = template.template.source
        self.assertIn("TEXT-GROUNDED CREATIVE — UNVERIFIED APPEARANCE", source)
        self.assertIn("Verified manufacturer text grounding", source)
        self.assertIn("no visual manufacturer reference image", source.lower())
        self.assertIn("text_grounding_trace", source)

    def test_generate_template_updates_attempts_from_ajax_response(self):
        template = get_template(
            "admin/catalog_imports/importitem/generate_media.html"
        )
        source = template.template.source
        self.assertIn('class="candidate-attempts"', source)
        self.assertIn("data.generation_attempts", source)

    def test_admin_returns_attempt_counter_and_text_trace_to_review(self):
        import catalog_imports.admin as admin_module

        source = Path(admin_module.__file__).read_text(encoding="utf-8")
        self.assertIn('"generation_attempts": candidate.generation_attempts', source)
        self.assertIn("text_grounding_trace_for_candidate", source)
        self.assertIn('"is_text_grounded_creative": is_text_grounded_creative', source)
