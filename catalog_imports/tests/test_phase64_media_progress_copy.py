from django.template.loader import get_template
from django.test import SimpleTestCase


class Phase64MediaProgressCopyTests(SimpleTestCase):
    def test_template_distinguishes_reference_images_from_gallery_images(self):
        template = get_template(
            "admin/catalog_imports/importitem/generate_media.html"
        )
        source = template.template.source
        self.assertIn("Gallery progress:", source)
        self.assertIn("Reference images are verification evidence", source)
        self.assertIn('data-label="{{ row.display_label|escape }}"', source)
