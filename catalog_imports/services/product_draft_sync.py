"""Phase 6.2 — Safe verified-data sync into an existing Product draft.

Why this exists
---------------
An ImportItem may create its Product draft before later evidence enrichment
finds weight, dimensions, warranty, package facts, etc. Re-analysis updates the
ImportItem normalized payload, but historically did not backfill those newly
verified facts into the already-created inactive Product draft.

This service closes that gap safely:
- draft/inactive Product only
- verified importer item only
- fills blank fields only
- never overwrites admin-entered values
- never approves, activates, or publishes
- shipping defaults are never treated as evidence
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List

from django.db import transaction

from catalog_imports.models import ImportAuditEvent
from catalog_imports.schema import UniversalProductDraft
from catalog_imports.services.content import content_payload
from catalog_imports.services.product_data_completion import weight_to_kg


def _text(value: Any) -> str:
    return str(value or "").strip()


def _decimal(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def product_weight_unit(unit: Any) -> str:
    value = _text(unit).lower()
    # Product model uses "lbs"; UniversalProductDraft uses "lb".
    aliases = {
        "lb": "lbs",
        "lbs": "lbs",
        "pound": "lbs",
        "pounds": "lbs",
        "kg": "kg",
        "g": "g",
        "oz": "oz",
    }
    return aliases.get(value, "")


def product_dimension_unit(unit: Any) -> str:
    value = _text(unit).lower()
    return value if value in {"mm", "cm", "in"} else ""


def _meaningful_warranty(draft):
    data = dict(getattr(draft, "warranty", {}) or {})
    years = max(_int(data.get("duration_years") or data.get("years"), 0), 0)
    months = max(_int(data.get("duration_months") or data.get("months"), 0), 0)
    coverage = _text(
        data.get("coverage_details")
        or data.get("coverage")
        or data.get("description")
    )
    provider = _text(
        data.get("provider")
        or data.get("manufacturer")
        or getattr(draft, "manufacturer", "")
        or getattr(draft, "brand", "")
    )
    meaningful = bool(years or months or coverage or _text(data.get("terms_url")))
    return {
        "meaningful": meaningful,
        "years": years,
        "months": min(months, 11),
        "coverage": coverage,
        "provider": provider,
        "exclusions": _text(data.get("exclusions")),
        "registration_required": bool(data.get("registration_required", False)),
        "registration_url": _text(data.get("registration_url")),
        "terms_url": _text(data.get("terms_url")),
        "phone": _text(data.get("customer_support_phone") or data.get("support_phone")),
        "email": _text(data.get("customer_support_email") or data.get("support_email")),
    }


def _shipping_data(draft):
    data = dict(getattr(draft, "shipping", {}) or {})
    raw_weight = _decimal(data.get("weight_shipping") or data.get("shipping_weight"))
    raw_unit = _text(data.get("weight_shipping_unit") or "kg").lower()

    weight_kg = None
    if raw_weight is not None:
        weight_kg = weight_to_kg(raw_weight, raw_unit or "kg")
        # Legacy normalized payloads may already store kg without a unit.
        if weight_kg is None and not _text(data.get("weight_shipping_unit")):
            weight_kg = raw_weight

    min_days = _int(
        data.get("estimated_delivery_days_min") or data.get("delivery_days_min"),
        0,
    )
    max_days = _int(
        data.get("estimated_delivery_days_max") or data.get("delivery_days_max"),
        0,
    )

    return {
        "weight_shipping_kg": weight_kg,
        "dimensions_package": _text(
            data.get("dimensions_package") or data.get("package_dimensions")
        )[:100],
        "shipping_restrictions": _text(
            data.get("shipping_restrictions") or data.get("restrictions")
        ),
        "hazmat_present": "hazmat" in data,
        "hazmat": bool(data.get("hazmat", False)),
        "free_shipping_present": "free_shipping" in data,
        "free_shipping": bool(data.get("free_shipping", False)),
        "min_days": min_days,
        "max_days": max_days,
        "valid_delivery_range": bool(
            min_days and max_days and min_days > 0 and max_days >= min_days
        ),
    }


def _log(item, event_type, message, payload):
    ImportAuditEvent.objects.create(
        item=item,
        event_type=event_type,
        message=str(message or "")[:500],
        payload=payload or {},
    )


@transaction.atomic
def sync_verified_product_draft(item, actor=None) -> Dict:
    """Fill newly verified facts into an already-created safe Product draft."""
    item.refresh_from_db()

    report = {
        "version": "6.2",
        "status": "not_needed",
        "changed_fields": [],
        "related_records": [],
        "skipped": [],
        "safety": {
            "draft_only": True,
            "inactive_only": True,
            "blank_fields_only": True,
            "never_auto_publish": True,
            "never_overwrite_admin_values": True,
        },
    }

    if not getattr(item, "created_product_id", None):
        report["status"] = "no_product_draft"
        return report

    if not (
        getattr(item, "identity_verified", False)
        and getattr(item, "specifications_verified", False)
        and getattr(item, "price_verified", False)
    ):
        report["status"] = "verification_incomplete"
        return report

    product = item.created_product

    if bool(getattr(product, "is_active", False)):
        report["status"] = "blocked_active_product"
        return report

    approval_status = _text(getattr(product, "approval_status", "draft"))
    if approval_status and approval_status != "draft":
        report["status"] = "blocked_non_draft_product"
        return report

    draft = UniversalProductDraft.from_dict(item.normalized_payload or {})
    content = content_payload(draft)

    changed: List[str] = []

    # Content/SEO: fill only when the Product field is still blank.
    for field_name, value in (
        ("description", content.get("description")),
        ("specifications", content.get("specifications")),
        ("meta_title", content.get("meta_title")),
        ("meta_description", content.get("meta_description")),
        ("meta_keywords", content.get("meta_keywords")),
    ):
        if not _text(getattr(product, field_name, "")) and _text(value):
            setattr(product, field_name, value)
            changed.append(field_name)

    # Physical facts: copy only when the actual numeric Product fields are blank.
    if getattr(product, "weight", None) is None and getattr(draft, "weight", None) is not None:
        unit = product_weight_unit(getattr(draft, "weight_unit", ""))
        if unit:
            product.weight = draft.weight
            product.weight_unit = unit
            changed.extend(["weight", "weight_unit"])
        else:
            report["skipped"].append("weight: unsupported unit")

    product_dims = [
        getattr(product, "dimensions_length", None),
        getattr(product, "dimensions_width", None),
        getattr(product, "dimensions_height", None),
    ]
    draft_dims = [
        getattr(draft, "dimensions_length", None),
        getattr(draft, "dimensions_width", None),
        getattr(draft, "dimensions_height", None),
    ]
    if all(value is None for value in product_dims) and all(value is not None for value in draft_dims):
        unit = product_dimension_unit(getattr(draft, "dimension_unit", ""))
        if unit:
            product.dimensions_length = draft_dims[0]
            product.dimensions_width = draft_dims[1]
            product.dimensions_height = draft_dims[2]
            product.dimension_unit = unit
            changed.extend([
                "dimensions_length",
                "dimensions_width",
                "dimensions_height",
                "dimension_unit",
            ])
        else:
            report["skipped"].append("dimensions: unsupported unit")

    # Optional manufacturer fields can be safely filled when blank and verified.
    if not _text(getattr(product, "country_of_origin", "")) and _text(getattr(draft, "country_of_origin", "")):
        product.country_of_origin = _text(draft.country_of_origin)[:120]
        changed.append("country_of_origin")

    if not _text(getattr(product, "manufacturer_address", "")) and _text(getattr(draft, "manufacturer_address", "")):
        product.manufacturer_address = _text(draft.manufacturer_address)
        changed.append("manufacturer_address")

    draft_certs = [
        _text(value)
        for value in (getattr(draft, "certifications", None) or [])
        if _text(value)
    ]
    current_certs = getattr(product, "certifications", None)
    if draft_certs and not current_certs:
        product.certifications = draft_certs[:20]
        changed.append("certifications")

    # Warranty: fill only if current Product warranty is effectively empty.
    warranty = _meaningful_warranty(draft)
    current_warranty_empty = not (
        (getattr(product, "warranty_years", 0) or 0)
        or _text(getattr(product, "warranty_description", ""))
    )
    if warranty["meaningful"] and current_warranty_empty:
        product.warranty_years = warranty["years"]
        product.warranty_description = warranty["coverage"]
        changed.extend(["warranty_years", "warranty_description"])

    if changed:
        # Use normal Product.save(); do not bypass existing Product behavior.
        product.save()

    # Rich warranty record, only when none exists already.
    if warranty["meaningful"] and warranty["provider"]:
        from products.models import ManufacturerWarranty

        existing = ManufacturerWarranty.objects.filter(product=product).first()
        if existing is None:
            ManufacturerWarranty.objects.create(
                product=product,
                provider=warranty["provider"][:200],
                duration_years=warranty["years"],
                duration_months=warranty["months"],
                coverage_details=warranty["coverage"],
                exclusions=warranty["exclusions"],
                registration_required=warranty["registration_required"],
                registration_url=warranty["registration_url"],
                terms_url=warranty["terms_url"],
                customer_support_phone=warranty["phone"][:50],
                customer_support_email=warranty["email"],
            )
            report["related_records"].append("manufacturer_warranty_created")

    # Shipping facts:
    # - update an existing record only where fields are blank
    # - create a new ShippingInfo only when a real delivery range exists,
    #   so model defaults can never masquerade as verified delivery evidence.
    shipping = _shipping_data(draft)
    from products.models import ShippingInfo

    shipping_obj = ShippingInfo.objects.filter(product=product).first()
    shipping_changed = []

    if shipping_obj is not None:
        if getattr(shipping_obj, "weight_shipping", None) in (None, "") and shipping["weight_shipping_kg"] is not None:
            shipping_obj.weight_shipping = shipping["weight_shipping_kg"]
            shipping_changed.append("weight_shipping")
        if not _text(getattr(shipping_obj, "dimensions_package", "")) and shipping["dimensions_package"]:
            shipping_obj.dimensions_package = shipping["dimensions_package"]
            shipping_changed.append("dimensions_package")
        if not _text(getattr(shipping_obj, "shipping_restrictions", "")) and shipping["shipping_restrictions"]:
            shipping_obj.shipping_restrictions = shipping["shipping_restrictions"]
            shipping_changed.append("shipping_restrictions")
        if shipping["valid_delivery_range"]:
            # Existing values are respected unless they are empty/invalid.
            if not getattr(shipping_obj, "estimated_delivery_days_min", None):
                shipping_obj.estimated_delivery_days_min = shipping["min_days"]
                shipping_changed.append("estimated_delivery_days_min")
            if not getattr(shipping_obj, "estimated_delivery_days_max", None):
                shipping_obj.estimated_delivery_days_max = shipping["max_days"]
                shipping_changed.append("estimated_delivery_days_max")

        if shipping_changed:
            shipping_obj.save()
            report["related_records"].append(
                "shipping_info_updated:" + ",".join(shipping_changed)
            )

    elif shipping["valid_delivery_range"]:
        ShippingInfo.objects.create(
            product=product,
            weight_shipping=shipping["weight_shipping_kg"],
            dimensions_package=shipping["dimensions_package"],
            shipping_restrictions=shipping["shipping_restrictions"],
            hazmat=shipping["hazmat"] if shipping["hazmat_present"] else False,
            free_shipping=shipping["free_shipping"] if shipping["free_shipping_present"] else False,
            estimated_delivery_days_min=shipping["min_days"],
            estimated_delivery_days_max=shipping["max_days"],
        )
        report["related_records"].append("shipping_info_created")

    report["changed_fields"] = changed
    report["status"] = (
        "synced"
        if changed or report["related_records"]
        else "already_current_or_no_new_verified_fields"
    )

    _log(
        item,
        "verified_product_draft_sync",
        "Verified importer facts synced into the existing inactive Product draft.",
        report,
    )
    return report
