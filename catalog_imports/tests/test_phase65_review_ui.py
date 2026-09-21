from django.template.loader import get_template
from django.test import SimpleTestCase


class Phase65ReviewUITests(SimpleTestCase):
    def test_review_page_exposes_strict_reference_warning_and_downgrade(self):
        template = get_template(
            "admin/catalog_imports/importitem/media_review.html"
        )
        source = template.template.source
        self.assertIn("STRICT ROLE MATCH NOT VERIFIED", source)
        self.assertIn("Factual approval blocked", source)
        self.assertIn("Downgrade approval to creative / re-review", source)
        self.assertIn("role-matched references used for this generation", source)
