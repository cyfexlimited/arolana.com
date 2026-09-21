from django.test import SimpleTestCase

from catalog_imports.schema import UniversalProductDraft
from catalog_imports.services.content import build_description_html, build_seo, build_specifications_html


class Phase4ContentTests(SimpleTestCase):
    def test_content_is_arolana_original_and_does_not_copy_source_description(self):
        draft = UniversalProductDraft(
            source_name="Paykobo",
            name="Logitech MeetUp 2",
            brand="Logitech",
            model="960-001681",
            description="Paykobo exclusive marketing wording that must not be copied.",
            key_features=["4K camera", "USB connectivity"],
            package_contents=["MeetUp 2", "Power supply"],
        )
        html = build_description_html(draft)
        self.assertIn("Logitech MeetUp 2", html)
        self.assertIn("4K camera", html)
        self.assertNotIn("Paykobo", html)
        self.assertNotIn("exclusive marketing wording", html)

    def test_seo_limits(self):
        draft = UniversalProductDraft(
            name="Logitech MeetUp 2 Video Conferencing Camera",
            brand="Logitech",
            model="960-001681",
            category="Video Conferencing",
        )
        seo = build_seo(draft)
        self.assertLessEqual(len(seo["meta_title"]), 60)
        self.assertLessEqual(len(seo["meta_description"]), 160)
        self.assertLessEqual(len(seo["meta_keywords"]), 200)

    def test_structured_specs_are_rendered_as_clean_table(self):
        draft = UniversalProductDraft(
            specifications={"Dimensions": "469.2 x 73.3 x 73 mm", "Weight": "1.8 kg"}
        )
        html = build_specifications_html(draft)
        self.assertIn("Dimensions", html)
        self.assertIn("1.8 kg", html)
        self.assertNotIn("<script", html.lower())
