from pathlib import Path

from django.template.loader import get_template
from django.test import SimpleTestCase


class Phase533AdminUITests(SimpleTestCase):
    def test_generate_page_has_explicit_apply_verified_slots_action(self):
        template = get_template(
            "admin/catalog_imports/importitem/generate_media.html"
        )
        source = template.template.source
        self.assertIn("Apply {{ dynamic_slot_report.available_count }} verified factual slot", source)
        self.assertIn("approved/attached media is never changed", source)
        self.assertIn("unapproved creative preview will be discarded", source)

    def test_admin_has_dynamic_slot_post_endpoint(self):
        import catalog_imports.admin as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        self.assertIn("apply_dynamic_verified_slots_view", source)
        self.assertIn("reconcile_existing_media_plan", source)
        self.assertIn("dynamic_verified_slot_report", source)
