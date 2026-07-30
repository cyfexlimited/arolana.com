from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class VendorDetailTemplateTests(SimpleTestCase):
    def test_vendor_actions_wrap_inside_hero_card(self):
        template = (
            Path(settings.BASE_DIR) / "templates" / "vendors" / "detail.html"
        ).read_text()

        self.assertIn("flex: 1 1 100%;", template)
        self.assertIn("max-width: 100%;", template)
        self.assertIn("flex: 1 1 10.75rem;", template)
        self.assertIn("text-overflow: ellipsis;", template)
        self.assertNotIn("safeFollowing", template)
