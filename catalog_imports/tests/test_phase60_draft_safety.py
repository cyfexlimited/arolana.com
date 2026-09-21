from pathlib import Path

from django.test import SimpleTestCase


class Phase60DraftSafetyTests(SimpleTestCase):
    def test_shippinginfo_still_requires_real_delivery_range(self):
        import catalog_imports.services.draft_creation as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        self.assertIn(
            '"can_create": bool(min_days and max_days and min_days > 0 and max_days >= min_days)',
            source,
        )
        self.assertIn(
            "shipping_info_not_created_without_verified_delivery_range",
            source,
        )
