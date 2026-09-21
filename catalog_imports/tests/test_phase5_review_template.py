from pathlib import Path

from django.conf import settings
from django.template.loader import get_template
from django.test import SimpleTestCase


class Phase5ReviewTemplateTests(SimpleTestCase):
    def test_review_template_compiles(self):
        template = get_template("admin/catalog_imports/importitem/media_review.html")
        self.assertIsNotNone(template)

    def test_review_template_has_large_reference_comparison(self):
        path = (
            Path(settings.BASE_DIR)
            / "catalog_imports"
            / "templates"
            / "admin"
            / "catalog_imports"
            / "importitem"
            / "media_review.html"
        )
        source = path.read_text(encoding="utf-8")
        self.assertIn("compare-modal", source)
        self.assertIn("Generated candidate", source)
        self.assertIn("Official manufacturer reference", source)
        self.assertIn("candidate.reference_urls", source)
        self.assertIn("data-open-review-modal", source)
