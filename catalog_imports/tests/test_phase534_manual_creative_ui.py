from pathlib import Path

from django.template.loader import get_template
from django.test import SimpleTestCase


class Phase534ManualCreativeUITests(SimpleTestCase):
    def test_review_template_has_manual_creative_downgrade_action(self):
        template = get_template(
            "admin/catalog_imports/importitem/media_review.html"
        )
        source = template.template.source
        self.assertIn("Downgrade to manual creative", source)
        self.assertIn("manual creative — unverified appearance", source)

    def test_admin_exposes_manual_creative_downgrade_endpoint(self):
        import catalog_imports.admin as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        self.assertIn("downgrade_manual_creative_view", source)
        self.assertIn("downgrade_to_manual_creative", source)
        self.assertIn("can_downgrade_manual_creative", source)
