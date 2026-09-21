from django.template.loader import get_template
from django.test import SimpleTestCase


class Phase537GenerateTemplateTests(SimpleTestCase):
    def test_generate_page_explains_practical_completion(self):
        template = get_template(
            "admin/catalog_imports/importitem/generate_media.html"
        )
        source = template.template.source
        self.assertIn("Media sufficient:", source)
        self.assertIn("bulk generation paused", source)
        self.assertIn("Open Product admin / add remaining images", source)
        self.assertIn("Optional. Leave this slot empty", source)
        self.assertIn("if (btn)", source)
