from django.template.loader import get_template
from django.test import SimpleTestCase


class Phase641MediaRetryStateHotfixTests(SimpleTestCase):
    def test_ready_review_is_terminal_in_ajax_ui(self):
        template = get_template(
            "admin/catalog_imports/importitem/generate_media.html"
        )
        source = template.template.source
        self.assertIn("const alreadyReady", source)
        self.assertIn("Already ready for review:", source)
        self.assertIn("Creative fallback ready", source)

    def test_successful_bulk_queue_stays_disabled(self):
        template = get_template(
            "admin/catalog_imports/importitem/generate_media.html"
        )
        source = template.template.source
        self.assertIn("let allSucceeded = true;", source)
        self.assertIn("Verified generation completed — review images", source)
        self.assertIn("Retry failed verified jobs", source)
