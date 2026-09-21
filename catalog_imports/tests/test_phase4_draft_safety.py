from django.test import SimpleTestCase

from catalog_imports.schema import UniversalProductDraft
from catalog_imports.services.draft_creation import _shipping_values, _warranty_values


class Phase4DraftSafetyTests(SimpleTestCase):
    def test_shipping_record_is_not_created_from_model_defaults(self):
        draft = UniversalProductDraft(shipping={"weight_shipping": "2.2"})
        values = _shipping_values(draft)
        self.assertFalse(values["can_create"])

    def test_missing_warranty_does_not_invent_one_year(self):
        draft = UniversalProductDraft(brand="Logitech", warranty={})
        values = _warranty_values(draft)
        self.assertFalse(values["meaningful"])
        self.assertEqual(values["years"], 0)
