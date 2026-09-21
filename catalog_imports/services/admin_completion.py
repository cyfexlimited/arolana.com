"""Phase 6.1 — Final admin completion dashboard.

This service does not publish, approve, or modify Product data.
It only reads the current importer + Product draft state and tells an admin
what is already complete and what still needs a normal Product-admin edit.
"""

from __future__ import annotations

from typing import Any, Dict, List

from catalog_imports.services.practical_media_completion import practical_media_completion


def _text(value: Any) -> str:
    return str(value or "").strip()


def _relation_or_none(obj, name):
    try:
        return getattr(obj, name)
    except Exception:
        return None


def _bool_list(value) -> bool:
    if isinstance(value, (list, tuple, set)):
        return bool([x for x in value if _text(x)])
    return bool(value)


def build_admin_completion_report(item) -> Dict:
    verification = dict(getattr(item, "verification_report", None) or {})
    data_report = dict(verification.get("product_data_completion") or {})
    product = getattr(item, "created_product", None)

    importer_core_ready = bool(
        data_report.get("status") == "ready"
        and not (data_report.get("missing_critical") or [])
        and getattr(item, "identity_verified", False)
        and getattr(item, "specifications_verified", False)
        and getattr(item, "price_verified", False)
        and getattr(item, "calculated_price", None) is not None
    )

    result = {
        "version": "6.1",
        "status": "prepare_draft_first",
        "label": "Prepare Product draft first",
        "importer_core_ready": importer_core_ready,
        "product_exists": bool(product),
        "product_id": getattr(product, "pk", None) if product else None,
        "product_sku": _text(getattr(product, "sku", "")) if product else "",
        "product_is_active": bool(getattr(product, "is_active", False)) if product else False,
        "product_approval_status": _text(getattr(product, "approval_status", "")) if product else "",
        "automatic_complete": [],
        "manual_remaining": [],
        "optional_remaining": [],
        "media": {},
        "safe_to_open_product_admin": bool(product),
        "nothing_auto_published": True,
    }

    if not product:
        if importer_core_ready:
            result["label"] = "Verified — prepare the Arolana draft"
        return result

    # What the importer has already completed.
    if getattr(item, "identity_verified", False):
        result["automatic_complete"].append("Exact product identity verified")
    if getattr(item, "specifications_verified", False):
        result["automatic_complete"].append("Manufacturer specifications verified")
    if getattr(item, "price_verified", False):
        result["automatic_complete"].append("Retail/source price verified")
    if getattr(item, "calculated_price", None) is not None:
        result["automatic_complete"].append("Arolana selling price calculated")

    if _text(getattr(product, "description", "")):
        result["automatic_complete"].append("Arolana description prepared")
    if _text(getattr(product, "specifications", "")):
        result["automatic_complete"].append("Specifications prepared")
    if _text(getattr(product, "meta_title", "")) and _text(getattr(product, "meta_description", "")):
        result["automatic_complete"].append("SEO title and description prepared")
    if getattr(product, "weight", None) is not None:
        result["automatic_complete"].append("Product/net weight available")
    if all(
        getattr(product, field, None) is not None
        for field in ("dimensions_length", "dimensions_width", "dimensions_height")
    ):
        result["automatic_complete"].append("Product dimensions available")

    # Shipping is intentionally evaluated from the LIVE Product draft because
    # the admin may complete it after import.
    shipping = _relation_or_none(product, "shipping_info")
    if shipping is None:
        result["manual_remaining"].extend([
            {
                "key": "shipping_weight",
                "label": "Shipping / package weight",
                "reason": "Enter the packed shipping weight in Product admin.",
            },
            {
                "key": "package_dimensions",
                "label": "Package dimensions",
                "reason": "Enter the packed L×W×H dimensions in Product admin.",
            },
            {
                "key": "delivery_range",
                "label": "Estimated delivery days",
                "reason": "Set the seller/vendor delivery minimum and maximum.",
            },
        ])
    else:
        if getattr(shipping, "weight_shipping", None) in (None, ""):
            result["manual_remaining"].append({
                "key": "shipping_weight",
                "label": "Shipping / package weight",
                "reason": "Enter the packed shipping weight.",
            })
        else:
            result["automatic_complete"].append("Shipping / package weight completed")

        if not _text(getattr(shipping, "dimensions_package", "")):
            result["manual_remaining"].append({
                "key": "package_dimensions",
                "label": "Package dimensions",
                "reason": "Enter the packed L×W×H dimensions.",
            })
        else:
            result["automatic_complete"].append("Package dimensions completed")

        min_days = getattr(shipping, "estimated_delivery_days_min", None)
        max_days = getattr(shipping, "estimated_delivery_days_max", None)
        if not min_days or not max_days:
            result["manual_remaining"].append({
                "key": "delivery_range",
                "label": "Estimated delivery days",
                "reason": "Set the seller/vendor delivery minimum and maximum.",
            })
        else:
            result["automatic_complete"].append(
                f"Delivery range completed ({min_days}–{max_days} days)"
            )

    # Warranty can be completed either with the richer ManufacturerWarranty
    # record or the existing Product warranty fields.
    manufacturer_warranty = _relation_or_none(product, "manufacturer_warranty")
    warranty_complete = False
    if manufacturer_warranty is not None:
        warranty_complete = bool(
            _text(getattr(manufacturer_warranty, "provider", ""))
            or getattr(manufacturer_warranty, "duration_years", 0)
            or getattr(manufacturer_warranty, "duration_months", 0)
            or _text(getattr(manufacturer_warranty, "coverage_details", ""))
        )
    if not warranty_complete:
        warranty_complete = bool(
            (getattr(product, "warranty_years", 0) or 0) > 0
            or _text(getattr(product, "warranty_description", ""))
        )

    if warranty_complete:
        result["automatic_complete"].append("Warranty information completed")
    else:
        result["manual_remaining"].append({
            "key": "warranty",
            "label": "Warranty",
            "reason": "Enter confirmed manufacturer/vendor warranty information if available.",
        })

    # These are useful but intentionally non-blocking.
    if not _text(getattr(product, "country_of_origin", "")):
        result["optional_remaining"].append("Country of origin")
    if not _text(getattr(product, "manufacturer_address", "")):
        result["optional_remaining"].append("Manufacturer address")
    if not _bool_list(getattr(product, "certifications", None)):
        result["optional_remaining"].append("Certifications")

    # Count both normal Product-admin images and importer review-stage images.
    gallery_count = 0
    try:
        gallery_count = int(product.images.count())
    except Exception:
        gallery_count = 0

    has_main_product_image = bool(getattr(product, "main_image", None))
    product_media_count = gallery_count + (1 if has_main_product_image else 0)

    importer_media = practical_media_completion(item)
    importer_usable = int(importer_media.get("usable_count") or 0)
    importer_minimum = int(importer_media.get("minimum_usable") or 8)
    importer_main = bool(importer_media.get("main_usable"))

    combined_sufficient = bool(
        product_media_count >= importer_minimum
        or importer_media.get("sufficient_for_review")
    )

    result["media"] = {
        "product_admin_image_count": product_media_count,
        "importer_usable_count": importer_usable,
        "minimum_recommended": importer_minimum,
        "importer_main_usable": importer_main,
        "sufficient": combined_sufficient,
        "note": (
            "Remaining images may always be added through the normal Product admin."
        ),
    }

    if combined_sufficient:
        result["automatic_complete"].append(
            f"Media sufficient for admin completion (recommended minimum {importer_minimum})"
        )
    else:
        result["manual_remaining"].append({
            "key": "media",
            "label": "Product images",
            "reason": (
                f"Review/attach or manually upload enough useful images. "
                f"Recommended minimum: {importer_minimum}."
            ),
        })

    if importer_core_ready:
        if result["manual_remaining"]:
            result["status"] = "ready_for_admin_completion"
            result["label"] = "Ready for Admin Completion"
        else:
            result["status"] = "ready_for_approval_review"
            result["label"] = "Ready for Approval Review"
    else:
        result["status"] = "verification_attention"
        result["label"] = "Verification needs attention"

    return result
