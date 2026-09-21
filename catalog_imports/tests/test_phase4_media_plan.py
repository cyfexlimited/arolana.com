from django.test import SimpleTestCase

from catalog_imports.services.media_plan import VIEW_PLAN, generation_prompt


class DummyBatch:
    max_images = 10


class DummyItem:
    normalized_payload = {
        "name": "Logitech MeetUp 2",
        "brand": "Logitech",
        "model": "960-001681",
    }
    batch = DummyBatch()


class Phase4MediaPlanTests(SimpleTestCase):
    def test_view_plan_never_exceeds_ten(self):
        self.assertLessEqual(len(VIEW_PLAN), 10)
        self.assertEqual(len(set(VIEW_PLAN)), len(VIEW_PLAN))

    def test_generation_prompt_requires_exact_product_and_no_guessing(self):
        prompt = generation_prompt(DummyItem(), VIEW_PLAN[0])
        self.assertIn("960-001681", prompt)
        self.assertIn("Do not invent", prompt)
        self.assertIn("held for manual review instead of guessing", prompt)
