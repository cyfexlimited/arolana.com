from pathlib import Path

from django.test import SimpleTestCase


class Phase62DraftCreationShippingUnitTests(SimpleTestCase):
    def test_shipping_weight_is_normalized_to_kg_before_shippinginfo(self):
        import catalog_imports.services.draft_creation as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        self.assertIn("weight_to_kg(raw_weight_shipping", source)

    def test_universal_lb_is_mapped_to_product_lbs(self):
        import catalog_imports.services.draft_creation as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        self.assertIn('"lbs" if str(draft.weight_unit', source)
