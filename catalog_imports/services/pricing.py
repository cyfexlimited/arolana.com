from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Tuple

from django.conf import settings

from catalog_imports.models import ImportPricingRule, ImportSource
from catalog_imports.schema import UniversalProductDraft

try:
    from currency.models import Currency
    from currency.utils.exchange_rates import CurrencyConverter
except ImportError:  # pragma: no cover - importer can still handle same-currency sources
    Currency = None
    CurrencyConverter = None


ROUNDING_QUANTA = {
    ImportPricingRule.ROUND_100: Decimal("100"),
    ImportPricingRule.ROUND_500: Decimal("500"),
    ImportPricingRule.ROUND_1000: Decimal("1000"),
}


def _matches_text(selector: str, *values: str) -> bool:
    selector = (selector or "").strip().lower()
    if not selector:
        return True
    return any(selector in (value or "").strip().lower() for value in values)


def rule_matches(rule: ImportPricingRule, draft: UniversalProductDraft, source: Optional[ImportSource]) -> bool:
    if not rule.is_active:
        return False
    if rule.source_id and (not source or rule.source_id != source.id):
        return False
    if not _matches_text(rule.brand_match, draft.brand, draft.manufacturer):
        return False
    if not _matches_text(rule.category_match, draft.category, draft.subcategory):
        return False
    if not _matches_text(
        rule.product_identifier_match,
        draft.name,
        draft.model,
        draft.manufacturer_sku,
        draft.gtin,
        draft.ean,
        draft.upc,
    ):
        return False
    return True


def select_rule(draft: UniversalProductDraft, source: Optional[ImportSource] = None) -> Optional[ImportPricingRule]:
    queryset = ImportPricingRule.objects.filter(is_active=True).select_related("source").order_by("-priority", "id")
    for rule in queryset:
        if rule_matches(rule, draft, source):
            return rule
    return None


def apply_rule(source_price, rule: ImportPricingRule) -> Decimal:
    """Apply markup to a price that is ALREADY in Arolana's base currency."""
    price = Decimal(str(source_price))
    percentage = Decimal(str(rule.percentage_markup or 0)) / Decimal("100")
    result = price + Decimal(str(rule.fixed_markup or 0)) + (price * percentage)

    quantum = ROUNDING_QUANTA.get(rule.rounding_mode)
    if quantum:
        result = (result / quantum).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * quantum

    return result.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _base_currency_code() -> str:
    return str(
        getattr(settings, "AROLANA_BASE_CURRENCY", None)
        or getattr(settings, "AROLANA_DEFAULT_CURRENCY", None)
        or getattr(settings, "CURRENCY_DEFAULT", None)
        or "NGN"
    ).upper()


def convert_source_price_to_base(source_price, source_currency_code: str):
    """Convert retailer price into Arolana base currency, failing closed.

    A fixed ₦ markup must never be numerically added to a USD/EUR/etc price.
    """
    amount = Decimal(str(source_price))
    source_code = str(source_currency_code or "").strip().upper()
    base_code = _base_currency_code()

    if not source_code:
        raise ValueError("Source currency is missing; pricing cannot be calculated safely.")

    if source_code == base_code:
        return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), {
            "conversion_applied": False,
            "source_currency": source_code,
            "base_currency": base_code,
            "rate_source": "same_currency",
        }

    if Currency is None or CurrencyConverter is None:
        raise ValueError(
            f"Currency conversion is unavailable; cannot apply a {base_code} markup to a {source_code} price."
        )

    from_currency = Currency.objects.filter(code=source_code, is_active=True).first()
    to_currency = (
        Currency.objects.filter(code=base_code, is_active=True).first()
        or Currency.objects.filter(is_base=True, is_active=True).first()
    )
    if not from_currency:
        raise ValueError(f"Active currency {source_code} is not configured.")
    if not to_currency:
        raise ValueError(f"Arolana base currency {base_code} is not configured.")

    try:
        converted = Decimal(
            str(CurrencyConverter.convert(amount, from_currency, to_currency))
        )
    except Exception as exc:
        raise ValueError(
            f"Could not convert {source_code} retailer price to {to_currency.code}; pricing is held."
        ) from exc

    if converted <= 0:
        raise ValueError(
            f"Currency conversion returned an invalid {to_currency.code} amount; pricing is held."
        )

    return converted.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), {
        "conversion_applied": True,
        "source_currency": source_code,
        "base_currency": str(to_currency.code).upper(),
        "rate_source": "currency.CurrencyConverter",
        "source_amount": str(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "converted_amount": str(converted.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
    }


def calculate_price_breakdown(
    draft: UniversalProductDraft,
    source: Optional[ImportSource] = None,
    explicit_rule: Optional[ImportPricingRule] = None,
):
    if draft.source_price is None:
        raise ValueError("Cannot calculate Arolana price without a source price.")

    rule = explicit_rule or select_rule(draft, source)
    if not rule:
        raise ValueError("No active import pricing rule matched this product.")

    source_currency = (
        str(draft.source_currency or "").strip().upper()
        or str(getattr(source, "default_currency", "") or "").strip().upper()
    )
    base_price, conversion = convert_source_price_to_base(
        draft.source_price,
        source_currency,
    )
    calculated = apply_rule(base_price, rule)
    return {
        "calculated_price": calculated,
        "rule": rule,
        "source_price": Decimal(str(draft.source_price)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        ),
        "source_currency": source_currency,
        "base_price": base_price,
        "base_currency": conversion["base_currency"],
        "conversion": conversion,
    }


def calculate_price(
    draft: UniversalProductDraft,
    source: Optional[ImportSource] = None,
    explicit_rule: Optional[ImportPricingRule] = None,
) -> Tuple[Decimal, ImportPricingRule]:
    """Backward-compatible two-value API."""
    breakdown = calculate_price_breakdown(
        draft,
        source=source,
        explicit_rule=explicit_rule,
    )
    return breakdown["calculated_price"], breakdown["rule"]
