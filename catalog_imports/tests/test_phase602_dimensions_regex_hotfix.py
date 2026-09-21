from decimal import Decimal

from django.test import SimpleTestCase

from catalog_imports.services.product_data_completion import _parse_dimensions


class Phase602DimensionsRegexHotfixTests(SimpleTestCase):
    def test_metric_dimensions_parse(self):
        value = _parse_dimensions("175 x 201 x 371 mm")
        self.assertIsNotNone(value)
        self.assertEqual(value["length"], Decimal("175"))
        self.assertEqual(value["width"], Decimal("201"))
        self.assertEqual(value["height"], Decimal("371"))
        self.assertEqual(value["unit"], "mm")

    def test_inches_dimensions_parse(self):
        value = _parse_dimensions("20 x 15 x 12 in")
        self.assertIsNotNone(value)
        self.assertEqual(value["unit"], "in")

    def test_quote_dimensions_parse(self):
        value = _parse_dimensions('20 x 15 x 12"')
        self.assertIsNotNone(value)
        self.assertEqual(value["unit"], "in")
