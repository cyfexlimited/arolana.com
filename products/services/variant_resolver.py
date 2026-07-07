from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class ResolvedCatalogItem:
    product: object
    variant: object = None
    offer: object = None
    name: str = ""
    description: str = ""
    specifications: str = ""
    price: Decimal = Decimal("0.00")
    stock_quantity: int = 0
    image = None
    gallery: list = field(default_factory=list)
    warranty_years: int = 0
    warranty_description: str = ""
    sku: str = ""
    condition: str = ""
    vendor = None


def _first_filled(*values):
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return ""


def _variant_gallery(variant):
    if not variant:
        return []
    try:
        return list(variant.images.filter(is_active=True).order_by("sort_order", "order"))
    except Exception:
        return []


def resolve_catalog_item(product, variant=None, offer=None):
    """
    Resolve customer-facing product data from Product + optional ProductVariant + optional VendorProductOffer.

    This keeps the legacy Product/ProductVariant behavior alive while allowing full variants
    and vendor offers to override only the fields they own.
    """
    if offer is not None:
        product = offer.product
        variant = offer.variant

    variant_is_full = bool(variant and getattr(variant, "variant_mode", "") == "full")
    name = getattr(product, "name", "")
    if variant and variant_is_full:
        name = _first_filled(getattr(variant, "name", ""), name)
    elif variant:
        value = getattr(variant, "value", "")
        if value and value.lower() not in name.lower():
            name = f"{name} - {value}"

    image = _first_filled(
        getattr(variant, "image", None) if variant else None,
        getattr(product, "main_image", None),
    )
    if offer is not None:
        price = offer.final_price
        stock_quantity = offer.available_stock
        condition = offer.condition
        vendor = offer.vendor
    elif variant is not None:
        price = variant.final_price
        stock_quantity = getattr(variant, "stock_quantity", 0)
        condition = getattr(product, "condition", "")
        vendor = getattr(product, "vendor_profile", None)
    else:
        price = getattr(product, "price", Decimal("0.00"))
        stock_quantity = getattr(product, "available_stock", getattr(product, "stock_quantity", 0))
        condition = getattr(product, "condition", "")
        vendor = getattr(product, "vendor_profile", None)

    return ResolvedCatalogItem(
        product=product,
        variant=variant,
        offer=offer,
        name=name,
        description=_first_filled(getattr(variant, "description", "") if variant_is_full else "", getattr(product, "description", "")),
        specifications=_first_filled(getattr(variant, "specifications", "") if variant_is_full else "", getattr(product, "specifications", "")),
        price=price,
        stock_quantity=stock_quantity,
        image=image,
        gallery=_variant_gallery(variant),
        warranty_years=_first_filled(getattr(variant, "warranty_years", None) if variant_is_full else None, getattr(product, "warranty_years", 0)) or 0,
        warranty_description=_first_filled(getattr(variant, "warranty_description", "") if variant_is_full else "", getattr(product, "warranty_description", "")),
        sku=_first_filled(getattr(offer, "seller_sku", "") if offer else "", getattr(variant, "sku", "") if variant else "", getattr(product, "sku", "")),
        condition=condition,
        vendor=vendor,
    )


def structured_specifications(product, variant=None):
    specs = []
    if variant is not None:
        try:
            specs.extend(variant.structured_specs.filter(is_active=True).order_by("display_order", "group", "name"))
        except Exception:
            pass
    return specs

