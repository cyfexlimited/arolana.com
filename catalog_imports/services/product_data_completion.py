"""Phase 6.0 — Product data completion and final readiness audit.

This phase deliberately separates:
1. Manufacturer-verifiable facts:
   identity, specifications, physical attributes, package facts, warranty.
2. Retailer/vendor commercial facts:
   price, availability, free shipping, delivery promise.
3. Arolana-generated content:
   original description and SEO built from verified facts.

Nothing is invented to make a field look complete.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional, Tuple

from catalog_imports.schema import UniversalProductDraft


WEIGHT_UNITS = {"g", "kg", "lb", "oz"}
DIMENSION_UNITS = {"mm", "cm", "m", "in"}

_WEIGHT_TO_KG = {
    "kg": Decimal("1"),
    "g": Decimal("0.001"),
    "lb": Decimal("0.45359237"),
    "oz": Decimal("0.028349523125"),
}


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _decimal(value) -> Optional[Decimal]:
    if value in (None, ""):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if result < 0:
        return None
    return result


def _normalize_weight_unit(value: Any) -> str:
    raw = _text(value).lower().replace("lbs", "lb").replace("pounds", "lb").replace("pound", "lb")
    raw = raw.replace("kilograms", "kg").replace("kilogram", "kg")
    raw = raw.replace("grams", "g").replace("gram", "g")
    raw = raw.replace("ounces", "oz").replace("ounce", "oz")
    return raw if raw in WEIGHT_UNITS else ""


def _normalize_dimension_unit(value: Any) -> str:
    raw = _text(value).lower()
    aliases = {
        "millimeter": "mm", "millimeters": "mm",
        "centimeter": "cm", "centimeters": "cm",
        "meter": "m", "meters": "m",
        "inch": "in", "inches": "in", '"': "in",
    }
    raw = aliases.get(raw, raw)
    return raw if raw in DIMENSION_UNITS else ""


def weight_to_kg(value, unit) -> Optional[Decimal]:
    amount = _decimal(value)
    normalized = _normalize_weight_unit(unit)
    if amount is None or not normalized:
        return None
    return (amount * _WEIGHT_TO_KG[normalized]).quantize(Decimal("0.001"))


def _flatten_specs(value: Any, prefix: str = "") -> List[Tuple[str, str]]:
    rows: List[Tuple[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            label = _text(key)
            full = f"{prefix} {label}".strip()
            if isinstance(child, (dict, list, tuple)):
                rows.extend(_flatten_specs(child, full))
            else:
                val = _text(child)
                if val:
                    rows.append((full, val))
    elif isinstance(value, (list, tuple)):
        for child in value:
            if isinstance(child, (dict, list, tuple)):
                rows.extend(_flatten_specs(child, prefix))
            else:
                val = _text(child)
                if val:
                    rows.append((prefix, val))
    return rows


def _parse_weight(value: str):
    text = _text(value).lower()
    match = re.search(r"(?<![\d.])(\d+(?:\.\d+)?)\s*(kg|g|lbs?|pounds?|oz|ounces?)\b", text)
    if not match:
        return None, ""
    amount = _decimal(match.group(1))
    unit = _normalize_weight_unit(match.group(2))
    return amount, unit


def _parse_dimensions(value: str):
    text = _text(value).lower().replace("×", "x")
    # Examples: 12.3 x 8.4 x 5.5 in; 312 × 213 × 140 mm
    match = re.search(
        r"(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)"
        r"\s*(mm|cm|m|in|inch|inches|\")(?=\s|$|[,;)\]])",
        text,
    )
    if not match:
        return None
    unit = _normalize_dimension_unit(match.group(4))
    if not unit:
        return None
    return {
        "length": _decimal(match.group(1)),
        "width": _decimal(match.group(2)),
        "height": _decimal(match.group(3)),
        "unit": unit,
    }


def _warranty_from_text(value: str):
    text = _text(value)
    lower = text.lower()
    years = 0
    months = 0
    year_match = re.search(r"\b(\d+)\s*[- ]?\s*years?\b", lower)
    month_match = re.search(r"\b(\d+)\s*[- ]?\s*months?\b", lower)
    if year_match:
        years = int(year_match.group(1))
    if month_match:
        months = int(month_match.group(1))
    if not years and not months:
        return {}
    return {
        "duration_years": years,
        "duration_months": months,
        "coverage_details": text,
    }


def enrich_verified_draft_from_specs(draft: UniversalProductDraft) -> Dict:
    """Fill explicit top-level facts from already verified structured specs.

    This is label-driven extraction only. It never infers missing values.
    """
    rows = _flatten_specs(draft.specifications or {})
    changes = []

    shipping = dict(draft.shipping or {})
    warranty = dict(draft.warranty or {})

    for raw_label, value in rows:
        label = _text(raw_label).lower()
        value_text = _text(value)
        if not value_text:
            continue

        is_package = any(token in label for token in ("package", "packaging", "shipping", "carton", "gross"))
        is_weight = "weight" in label
        is_dimensions = any(token in label for token in ("dimension", "dimensions", "size (w", "size w", "w x h x d", "l x w x h"))

        if is_weight:
            amount, unit = _parse_weight(value_text)
            if amount is not None and unit:
                if is_package:
                    if shipping.get("weight_shipping") in (None, ""):
                        kg = weight_to_kg(amount, unit)
                        if kg is not None:
                            shipping["weight_shipping"] = str(kg)
                            shipping["weight_shipping_unit"] = "kg"
                            shipping["weight_shipping_source_text"] = value_text
                            changes.append("shipping.weight_shipping")
                elif draft.weight is None:
                    draft.weight = amount
                    draft.weight_unit = unit
                    changes.extend(["weight", "weight_unit"])

        if is_dimensions:
            parsed = _parse_dimensions(value_text)
            if parsed:
                if is_package:
                    if not _text(shipping.get("dimensions_package")):
                        shipping["dimensions_package"] = value_text[:100]
                        changes.append("shipping.dimensions_package")
                elif (
                    draft.dimensions_length is None
                    and draft.dimensions_width is None
                    and draft.dimensions_height is None
                ):
                    draft.dimensions_length = parsed["length"]
                    draft.dimensions_width = parsed["width"]
                    draft.dimensions_height = parsed["height"]
                    draft.dimension_unit = parsed["unit"]
                    changes.extend([
                        "dimensions_length",
                        "dimensions_width",
                        "dimensions_height",
                        "dimension_unit",
                    ])

        if not draft.country_of_origin and (
            "country of origin" in label or label.endswith("origin")
        ):
            draft.country_of_origin = value_text[:120]
            changes.append("country_of_origin")

        if not warranty and "warranty" in label:
            parsed_warranty = _warranty_from_text(value_text)
            if parsed_warranty:
                warranty.update(parsed_warranty)
                changes.append("warranty")

        if "certification" in label or "compliance" in label or "certified" in label:
            values = [
                _text(part)
                for part in re.split(r"[,;/|]+", value_text)
                if _text(part)
            ]
            existing = [str(row).strip() for row in (draft.certifications or []) if str(row).strip()]
            seen = {row.casefold() for row in existing}
            for row in values[:12]:
                if row.casefold() not in seen:
                    existing.append(row)
                    seen.add(row.casefold())
                    changes.append("certifications")
            draft.certifications = existing[:20]

    if shipping:
        draft.shipping = shipping
    if warranty:
        draft.warranty = warranty

    return {
        "changed": bool(changes),
        "fields": sorted(set(changes)),
        "source": "verified_structured_specifications",
    }


def build_product_data_completion_report(
    draft: UniversalProductDraft,
    *,
    identity_verified=False,
    specifications_verified=False,
    price_verified=False,
    calculated_price=None,
) -> Dict:
    """Describe what is complete and what still needs manual/source input."""
    shipping = dict(draft.shipping or {})
    warranty = dict(draft.warranty or {})

    has_identifier = bool(
        _text(draft.model)
        or _text(draft.manufacturer_sku)
        or _text(draft.gtin)
        or _text(draft.ean)
        or _text(draft.upc)
    )
    has_specs = bool(draft.specifications or _text(draft.specifications_html))
    has_features = bool([x for x in (draft.key_features or []) if _text(x)])
    has_package_contents = bool([x for x in (draft.package_contents or []) if _text(x)])

    has_weight = draft.weight is not None and bool(_normalize_weight_unit(draft.weight_unit))
    has_dimensions = all(
        value is not None
        for value in (
            draft.dimensions_length,
            draft.dimensions_width,
            draft.dimensions_height,
        )
    ) and bool(_normalize_dimension_unit(draft.dimension_unit))

    has_package_weight = shipping.get("weight_shipping") not in (None, "")
    has_package_dimensions = bool(_text(shipping.get("dimensions_package")))
    has_delivery = bool(
        shipping.get("estimated_delivery_days_min")
        and shipping.get("estimated_delivery_days_max")
    )
    has_shipping_restrictions = bool(_text(shipping.get("shipping_restrictions")))
    has_hazmat_fact = "hazmat" in shipping
    has_warranty = bool(
        warranty.get("duration_years")
        or warranty.get("duration_months")
        or _text(warranty.get("coverage_details") or warranty.get("coverage"))
        or _text(warranty.get("terms_url"))
    )

    critical = {
        "identity_verified": bool(identity_verified),
        "name": bool(_text(draft.name)),
        "brand": bool(_text(draft.brand or draft.manufacturer)),
        "identifier": has_identifier,
        "specifications_verified": bool(specifications_verified and has_specs),
        "source_price_verified": bool(price_verified),
        "arolana_price_calculated": calculated_price is not None,
    }

    content = {
        "verified_specs_available": has_specs,
        "key_features_available": has_features,
        "package_contents_available": has_package_contents,
        "description_can_be_generated": bool(
            _text(draft.name)
            and (has_features or has_specs)
        ),
        "seo_can_be_generated": bool(_text(draft.name)),
    }

    physical = {
        "net_weight": has_weight,
        "product_dimensions": has_dimensions,
        "country_of_origin": bool(_text(draft.country_of_origin)),
        "manufacturer_address": bool(_text(draft.manufacturer_address)),
        "certifications": bool(draft.certifications),
    }

    shipping_report = {
        "package_weight": has_package_weight,
        "package_dimensions": has_package_dimensions,
        "shipping_restrictions": has_shipping_restrictions,
        "hazmat_fact": has_hazmat_fact,
        "delivery_range": has_delivery,
        "free_shipping": bool(shipping.get("free_shipping")) if "free_shipping" in shipping else False,
        "delivery_source_rule": (
            "Seller/vendor fulfillment data only. Manufacturer evidence must not invent delivery days or free shipping."
        ),
    }

    warranty_report = {
        "manufacturer_warranty": has_warranty,
    }

    missing_critical = [key for key, value in critical.items() if not value]
    manual_follow_up = []

    if not has_weight:
        manual_follow_up.append("Net/product weight is not verified.")
    if not has_dimensions:
        manual_follow_up.append("Product dimensions are not verified.")
    if not has_package_weight:
        manual_follow_up.append("Package/shipping weight is not verified.")
    if not has_package_dimensions:
        manual_follow_up.append("Package dimensions are not verified.")
    if not has_warranty:
        manual_follow_up.append("Manufacturer warranty details are not verified.")
    if not has_delivery:
        manual_follow_up.append(
            "Delivery-day range is seller/vendor fulfillment data and should be entered manually unless the selected source explicitly provides it."
        )

    status = "ready" if not missing_critical else "needs_attention"

    return {
        "version": "6.0",
        "status": status,
        "critical": critical,
        "missing_critical": missing_critical,
        "content": content,
        "physical": physical,
        "shipping": shipping_report,
        "warranty": warranty_report,
        "manual_follow_up": manual_follow_up,
        "rules": {
            "manufacturer_facts_only": True,
            "retailer_price_preserved": True,
            "delivery_not_invented": True,
            "free_shipping_not_invented": True,
            "missing_optional_fields_do_not_block_draft": True,
        },
    }
