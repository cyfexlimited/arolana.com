from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional

from django.db import transaction
from django.utils import timezone

from catalog_imports.models import ImportAuditEvent, ImportItem
from catalog_imports.schema import UniversalProductDraft
from catalog_imports.services.content import content_payload
from catalog_imports.services.destination import resolve_destination
from catalog_imports.services.media_plan import prepare_media_plan
from catalog_imports.services.product_data_completion import (
    build_product_data_completion_report,
    weight_to_kg,
)


class DraftPreparationError(Exception):
    pass


def _log(item, event_type, message="", payload=None):
    ImportAuditEvent.objects.create(
        item=item,
        event_type=event_type,
        message=str(message or "")[:500],
        payload=payload or {},
    )


def _decimal(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _int(value, default=None):
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _warranty_values(draft):
    data = dict(getattr(draft, "warranty", {}) or {})
    provider = str(data.get("provider") or data.get("manufacturer") or draft.manufacturer or draft.brand or "").strip()
    years = _int(data.get("duration_years", data.get("years")), 0) or 0
    months = _int(data.get("duration_months", data.get("months")), 0) or 0
    coverage = str(data.get("coverage_details") or data.get("coverage") or data.get("description") or "").strip()
    exclusions = str(data.get("exclusions") or "").strip()
    registration_required = bool(data.get("registration_required", False))
    registration_url = str(data.get("registration_url") or "").strip()
    terms_url = str(data.get("terms_url") or "").strip()
    phone = str(data.get("customer_support_phone") or data.get("support_phone") or "").strip()
    email = str(data.get("customer_support_email") or data.get("support_email") or "").strip()
    meaningful = bool(coverage or years or months or registration_url or terms_url)
    return {
        "meaningful": meaningful,
        "provider": provider,
        "years": max(years, 0),
        "months": min(max(months, 0), 11),
        "coverage": coverage,
        "exclusions": exclusions,
        "registration_required": registration_required,
        "registration_url": registration_url,
        "terms_url": terms_url,
        "phone": phone,
        "email": email,
    }


def _shipping_values(draft):
    data = dict(getattr(draft, "shipping", {}) or {})
    min_days = _int(data.get("estimated_delivery_days_min", data.get("delivery_days_min")))
    max_days = _int(data.get("estimated_delivery_days_max", data.get("delivery_days_max")))
    raw_weight_shipping = _decimal(data.get("weight_shipping") or data.get("shipping_weight"))
    raw_weight_unit = str(data.get("weight_shipping_unit") or "kg").strip().lower()
    weight_shipping = (
        weight_to_kg(raw_weight_shipping, raw_weight_unit or "kg")
        if raw_weight_shipping is not None else None
    )
    if weight_shipping is None and raw_weight_shipping is not None and not data.get("weight_shipping_unit"):
        weight_shipping = raw_weight_shipping
    dimensions_package = str(data.get("dimensions_package") or data.get("package_dimensions") or "").strip()[:100]
    shipping_restrictions = str(data.get("shipping_restrictions") or data.get("restrictions") or "").strip()
    has_package_facts = bool(
        weight_shipping is not None
        or dimensions_package
        or shipping_restrictions
        or "hazmat" in data
    )
    return {
        "weight_shipping": weight_shipping,
        "dimensions_package": dimensions_package,
        "shipping_restrictions": shipping_restrictions,
        "hazmat": bool(data.get("hazmat", False)),
        "free_shipping": bool(data.get("free_shipping", False)),
        "min_days": min_days,
        "max_days": max_days,
        "has_package_facts": has_package_facts,
        # ShippingInfo's existing defaults must never be mistaken for verified
        # delivery facts. We create it only when a real delivery range exists.
        "can_create": bool(min_days and max_days and min_days > 0 and max_days >= min_days),
    }


def find_existing_product(draft, brand=None):
    from products.models import Product

    qs = Product.objects.all()
    if brand:
        qs = qs.filter(brand=brand)

    manufacturer_sku = str(draft.manufacturer_sku or "").strip()
    if manufacturer_sku:
        match = qs.filter(manufacturer_sku__iexact=manufacturer_sku).first()
        if match:
            return match, "manufacturer_sku"

    name = str(draft.name or "").strip()
    if name:
        match = qs.filter(name__iexact=name).first()
        if match:
            return match, "exact_name"

    return None, ""


def _build_report(item, **extra):
    base = {
        "phase": "arolana_draft_preparation",
        "ready_item": item.status in {ImportItem.STATUS_READY, ImportItem.STATUS_DRAFT_CREATED},
        "identity_verified": item.identity_verified,
        "specifications_verified": item.specifications_verified,
        "price_verified": item.price_verified,
        "calculated_price": str(item.calculated_price) if item.calculated_price is not None else None,
        "nothing_published": True,
    }
    base.update(extra)
    return base


def prepare_arolana_draft(item: ImportItem, actor=None):
    """Lock the import item before preparing its Product draft.

    The lock and the existing preparation logic share one transaction so a
    repeated/concurrent admin request observes the Product created by the
    first request instead of creating another one.
    """
    with transaction.atomic():
        locked_item = ImportItem.objects.select_for_update().get(pk=item.pk)
        if locked_item.created_product_id:
            return locked_item.created_product
        return _prepare_arolana_draft_locked(locked_item, actor=actor)


def _prepare_arolana_draft_locked(item: ImportItem, actor=None):
    """Create a normal Arolana Product in inactive/draft state.

    This function intentionally uses the existing Product.save() path. It does
    not update existing products and never approves/publishes a Product.
    """
    item.refresh_from_db()
    if item.created_product_id:
        return item.created_product

    if item.status != ImportItem.STATUS_READY:
        report = _build_report(item, status="blocked", reason="item_not_ready")
        item.draft_preparation_report = report
        item.save(update_fields=["draft_preparation_report", "updated_at"])
        raise DraftPreparationError("This import item must be Ready for review before a Product draft can be prepared.")

    if not (item.identity_verified and item.specifications_verified and item.price_verified):
        report = _build_report(item, status="blocked", reason="verification_incomplete")
        item.draft_preparation_report = report
        item.save(update_fields=["draft_preparation_report", "updated_at"])
        raise DraftPreparationError("Identity, specifications and source price must all be verified first.")

    contamination = item.contamination_report or {}
    if contamination and contamination.get("passed") is False:
        report = _build_report(item, status="blocked", reason="source_contamination_failed")
        item.draft_preparation_report = report
        item.save(update_fields=["draft_preparation_report", "updated_at"])
        raise DraftPreparationError("Source-identity contamination checks must pass before draft creation.")

    if item.calculated_price is None:
        raise DraftPreparationError("A calculated Arolana price is required before draft creation.")

    draft = UniversalProductDraft.from_dict(item.normalized_payload or {})
    if not draft.name:
        raise DraftPreparationError("The verified product draft has no product name.")
    if not (draft.specifications or draft.specifications_html):
        report = _build_report(
            item,
            status="blocked",
            reason="verified_specifications_missing",
        )
        item.draft_preparation_report = report
        item.save(update_fields=["draft_preparation_report", "updated_at"])
        raise DraftPreparationError(
            "Exact verified specification data is still missing. Re-analyse with the official manufacturer page or add stronger evidence before creating the Product draft."
        )

    destination = resolve_destination(item, draft)
    if destination.vendor and not item.target_vendor_id:
        item.target_vendor = destination.vendor
    if destination.category and not item.target_category_id:
        item.target_category = destination.category
    if destination.brand and not item.target_brand_id:
        item.target_brand = destination.brand

    missing = destination.missing
    if missing:
        report = _build_report(
            item,
            status="destination_required",
            missing_destination_fields=missing,
            destination={
                "vendor_source": destination.vendor_source,
                "category_source": destination.category_source,
                "brand_source": destination.brand_source,
            },
        )
        item.draft_preparation_report = report
        item.save()
        raise DraftPreparationError(
            "Select the destination " + " and ".join(missing) + " before preparing the Arolana draft."
        )

    duplicate, duplicate_basis = find_existing_product(draft, destination.brand)
    if duplicate:
        item.existing_product_match = duplicate
        item.duplicate_report = {
            "status": "existing_product_match",
            "basis": duplicate_basis,
            "product_id": duplicate.pk,
            "product_name": duplicate.name,
            "product_sku": duplicate.sku,
            "action": "No duplicate Product was created. Review/update workflow is required for the existing listing.",
        }
        item.draft_preparation_report = _build_report(
            item,
            status="duplicate_hold",
            reason="existing_product_match",
            duplicate=item.duplicate_report,
        )
        item.status = ImportItem.STATUS_BLOCKED
        item.hold_reason = "existing_product_match"
        item.save()
        _log(item, "draft_duplicate_hold", f"Existing Product #{duplicate.pk} matched; duplicate creation blocked.", item.duplicate_report)
        prepare_media_plan(item)
        raise DraftPreparationError(
            f"An existing Arolana product already matches this item: {duplicate.name}. No duplicate was created."
        )

    from products.models import ManufacturerWarranty, Product, ShippingInfo

    content = content_payload(draft)
    product_data_completion = build_product_data_completion_report(
        draft,
        identity_verified=item.identity_verified,
        specifications_verified=item.specifications_verified,
        price_verified=item.price_verified,
        calculated_price=item.calculated_price,
    )
    condition = draft.condition if draft.condition in {value for value, _label in Product.PRODUCT_CONDITION_CHOICES} else Product.CONDITION_BRAND_NEW
    warranty = _warranty_values(draft)
    shipping = _shipping_values(draft)

    with transaction.atomic():
        product = Product(
            sku="",
            manufacturer_sku=str(draft.manufacturer_sku or draft.model or "")[:100],
            name=str(draft.name)[:200],
            slug="",
            condition=condition,
            description=content["description"],
            specifications=content["specifications"],
            category=destination.category,
            brand=destination.brand,
            vendor=destination.vendor,
            price=item.calculated_price,
            cost_per_item=item.source_price,
            stock_quantity=0,
            reserved_quantity=0,
            low_stock_threshold=5,
            allow_backorder=False,
            minimum_order_quantity=1,
            moq_unit="unit",
            sample_available=False,
            lead_time_days=None,
            country_of_origin=str(draft.country_of_origin or "")[:120],
            manufacturer_address=str(draft.manufacturer_address or ""),
            certifications=list(draft.certifications or []),
            weight=draft.weight,
            weight_unit=(
                "lbs" if str(draft.weight_unit or "").strip().lower() == "lb"
                else (draft.weight_unit or "kg")
            ),
            dimensions_length=draft.dimensions_length,
            dimensions_width=draft.dimensions_width,
            dimensions_height=draft.dimensions_height,
            dimension_unit=draft.dimension_unit or "cm",
            warranty_years=warranty["years"] if warranty["meaningful"] else 0,
            warranty_description=warranty["coverage"] if warranty["meaningful"] else "",
            extended_warranty_available=False,
            meta_title=content["meta_title"],
            meta_description=content["meta_description"],
            meta_keywords=content["meta_keywords"],
            is_featured=False,
            is_new=False,
            is_bestseller=False,
            is_active=False,
            approval_status="draft",
            approval_notes=(
                "Prepared by Arolana Universal Product Importer. Human review is required before approval."
            ),
        )
        # Crucially, use the existing Product.save() method so Arolana's own
        # validation, SKU generation, slug generation and image protection stay
        # authoritative.
        product.save()

        tags = [str(value).strip() for value in (draft.tags or []) if str(value).strip()]
        for extra in (draft.brand, draft.model):
            extra = str(extra or "").strip()
            if extra and extra.casefold() not in {x.casefold() for x in tags}:
                tags.append(extra)
        if tags:
            product.tags.add(*tags[:20])

        manufacturer_warranty_created = False
        if warranty["meaningful"] and warranty["provider"]:
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
            manufacturer_warranty_created = True

        shipping_created = False
        if shipping["can_create"]:
            ShippingInfo.objects.create(
                product=product,
                weight_shipping=shipping["weight_shipping"],
                dimensions_package=shipping["dimensions_package"],
                shipping_restrictions=shipping["shipping_restrictions"],
                hazmat=shipping["hazmat"],
                free_shipping=shipping["free_shipping"],
                estimated_delivery_days_min=shipping["min_days"],
                estimated_delivery_days_max=shipping["max_days"],
            )
            shipping_created = True

        item.created_product = product
        item.draft_prepared_at = timezone.now()
        item.status = ImportItem.STATUS_DRAFT_CREATED
        item.hold_reason = ""
        item.draft_preparation_report = _build_report(
            item,
            status="draft_created",
            product_id=product.pk,
            product_sku=product.sku,
            product_approval_status=product.approval_status,
            product_is_active=product.is_active,
            destination={
                "vendor_id": destination.vendor.pk,
                "category_id": destination.category.pk,
                "brand_id": destination.brand.pk if destination.brand else None,
                "vendor_source": destination.vendor_source,
                "category_source": destination.category_source,
                "brand_source": destination.brand_source,
            },
            related_records={
                "manufacturer_warranty_created": manufacturer_warranty_created,
                "shipping_info_created": shipping_created,
                "shipping_package_facts_available": shipping["has_package_facts"],
                "shipping_info_not_created_without_verified_delivery_range": bool(
                    shipping["has_package_facts"] and not shipping_created
                ),
            },
            product_data_completion=product_data_completion,
            generated_content={
                "description_chars": len(content["description"]),
                "specifications_chars": len(content["specifications"]),
                "meta_title": content["meta_title"],
                "meta_description": content["meta_description"],
            },
        )
        item.save()

    media_report = prepare_media_plan(item)
    report = dict(item.draft_preparation_report or {})
    report["media_plan"] = media_report
    item.draft_preparation_report = report
    item.save(update_fields=["draft_preparation_report", "updated_at"])
    _log(item, "arolana_draft_created", f"Inactive Product draft #{product.pk} created; nothing published.", report)
    return product
