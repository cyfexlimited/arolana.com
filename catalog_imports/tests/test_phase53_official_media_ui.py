from django.template.loader import get_template
from django.test import SimpleTestCase


class Phase53OfficialMediaUITests(SimpleTestCase):
    def test_generate_media_page_has_official_media_refresh_action(self):
        template = get_template(
            "admin/catalog_imports/importitem/generate_media.html"
        )
        source = template.template.source
        self.assertIn(
            "Acquire / refresh official manufacturer media",
            source,
        )
        self.assertIn("official_media_report", source)
