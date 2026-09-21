from typing import Dict, List

from catalog_imports.schema import UniversalProductDraft


CRITICAL_IDENTITY_FIELDS = ("name", "brand")


def validate_draft(draft: UniversalProductDraft, require_price: bool = True) -> Dict:
    errors: List[str] = []
    warnings: List[str] = []

    for field_name in CRITICAL_IDENTITY_FIELDS:
        if not str(getattr(draft, field_name, "") or "").strip():
            errors.append(f"Missing critical identity field: {field_name}")

    if not (draft.model or draft.manufacturer_sku or draft.gtin or draft.ean or draft.upc):
        warnings.append("No model/SKU/GTIN/EAN/UPC was extracted; exact product verification will be harder.")

    if require_price and draft.source_price is None:
        errors.append("Missing source price.")

    if not draft.description and not draft.specifications and not draft.specifications_html:
        warnings.append("Product has no usable description/specification content yet.")

    return {
        "passed": not errors,
        "errors": errors,
        "warnings": warnings,
    }
