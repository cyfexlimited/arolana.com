from django.test import SimpleTestCase

from catalog_imports.services.product_draft_sync import (
    product_dimension_unit,
    product_weight_unit,
)


class Phase62VerifiedDraftSyncUnitTests(SimpleTestCase):
    def test_universal_lb_maps_to_product_lbs_choice(self):
        self.assertEqual(product_weight_unit("lb"), "lbs")
        self.assertEqual(product_weight_unit("lbs"), "lbs")

    def test_supported_product_units_are_preserved(self):
        self.assertEqual(product_weight_unit("kg"), "kg")
        self.assertEqual(product_weight_unit("g"), "g")
        self.assertEqual(product_weight_unit("oz"), "oz")
        self.assertEqual(product_dimension_unit("mm"), "mm")
        self.assertEqual(product_dimension_unit("cm"), "cm")
        self.assertEqual(product_dimension_unit("in"), "in")

    def test_unsupported_dimension_unit_fails_closed(self):
        self.assertEqual(product_dimension_unit("m"), "")
