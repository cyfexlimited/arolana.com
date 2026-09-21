from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from catalog_imports.services.pricing import apply_rule


class PricingEngineTests(SimpleTestCase):
    def test_fixed_markup(self):
        rule = SimpleNamespace(
            fixed_markup=Decimal("50000"),
            percentage_markup=Decimal("0"),
            rounding_mode="none",
        )
        self.assertEqual(apply_rule(Decimal("500000"), rule), Decimal("550000.00"))

    def test_percentage_and_fixed_markup(self):
        rule = SimpleNamespace(
            fixed_markup=Decimal("25000"),
            percentage_markup=Decimal("10"),
            rounding_mode="none",
        )
        self.assertEqual(apply_rule(Decimal("500000"), rule), Decimal("575000.00"))
