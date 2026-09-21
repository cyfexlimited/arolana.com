from pathlib import Path

from django.test import SimpleTestCase


class Phase533MediaPlanWiringTests(SimpleTestCase):
    def test_future_plans_use_dynamic_verified_slot_selector(self):
        import catalog_imports.services.media_plan as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        self.assertIn("select_dynamic_verified_slots(", source)
        self.assertIn('dynamic_selection["slots"]', source)
        self.assertIn('"dynamic_verified_replacements"', source)
        self.assertIn("dynamic_slot_metadata(profile, slot)", source)
