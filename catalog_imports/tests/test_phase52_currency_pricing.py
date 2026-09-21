from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from catalog_imports.services.pricing import (
    apply_rule,
    calculate_price_breakdown,
    convert_source_price_to_base,
)


class _Manager:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, **kwargs):
        rows = self.rows
        code = kwargs.get("code")
        is_active = kwargs.get("is_active")
        is_base = kwargs.get("is_base")
        if code is not None:
            rows = [row for row in rows if row.code == code]
        if is_active is not None:
            rows = [row for row in rows if row.is_active == is_active]
        if is_base is not None:
            rows = [row for row in rows if row.is_base == is_base]
        return _Query(rows)


class _Query:
    def __init__(self, rows):
        self.rows = rows
    def first(self):
        return self.rows[0] if self.rows else None


class Phase52CurrencySafePricingTests(SimpleTestCase):
    @override_settings(AROLANA_BASE_CURRENCY="NGN")
    def test_same_currency_needs_no_converter(self):
        amount, meta = convert_source_price_to_base(Decimal("500000"), "NGN")
        self.assertEqual(amount, Decimal("500000.00"))
        self.assertFalse(meta["conversion_applied"])

    @override_settings(AROLANA_BASE_CURRENCY="NGN")
    def test_usd_is_converted_before_naira_markup(self):
        usd = SimpleNamespace(code="USD", is_active=True, is_base=False)
        ngn = SimpleNamespace(code="NGN", is_active=True, is_base=True)
        fake_currency = SimpleNamespace(objects=_Manager([usd, ngn]))
        fake_converter = SimpleNamespace(
            convert=lambda amount, from_currency, to_currency: Decimal("7484800")
        )
        rule = SimpleNamespace(
            fixed_markup=Decimal("50000"),
            percentage_markup=Decimal("0"),
            rounding_mode="none",
            name="Default import markup +₦50,000",
        )
        draft = SimpleNamespace(
            source_price=Decimal("4678"),
            source_currency="USD",
        )

        with patch("catalog_imports.services.pricing.Currency", fake_currency), \
             patch("catalog_imports.services.pricing.CurrencyConverter", fake_converter), \
             patch("catalog_imports.services.pricing.select_rule", return_value=rule):
            result = calculate_price_breakdown(draft)

        self.assertEqual(result["base_price"], Decimal("7484800.00"))
        self.assertEqual(result["calculated_price"], Decimal("7534800.00"))
        self.assertEqual(result["base_currency"], "NGN")

    @override_settings(AROLANA_BASE_CURRENCY="NGN")
    def test_cross_currency_fails_closed_when_converter_missing(self):
        with patch("catalog_imports.services.pricing.Currency", None), \
             patch("catalog_imports.services.pricing.CurrencyConverter", None):
            with self.assertRaises(ValueError):
                convert_source_price_to_base(Decimal("4678"), "USD")
