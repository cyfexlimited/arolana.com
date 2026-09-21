from dataclasses import dataclass
from typing import Optional

from django.db.models import Q

from catalog_imports.models import ImportCategoryMapping


@dataclass
class DestinationResolution:
    vendor: object = None
    category: object = None
    brand: object = None
    vendor_source: str = ""
    category_source: str = ""
    brand_source: str = ""

    @property
    def missing(self):
        result = []
        if not self.vendor:
            result.append("vendor")
        if not self.category:
            result.append("category")
        # Product.brand is nullable in Arolana, but a verified branded product
        # should not silently lose its brand. Treat a supplied brand as required.
        return result


def _normalized(value):
    return " ".join(str(value or "").strip().lower().split())


def _category_mapping(item, draft):
    category = _normalized(getattr(draft, "category", ""))
    subcategory = _normalized(getattr(draft, "subcategory", ""))
    if not category and not subcategory:
        return None

    qs = ImportCategoryMapping.objects.filter(is_active=True).select_related("target_category", "source")
    if item.source_id:
        qs = qs.filter(Q(source__isnull=True) | Q(source=item.source))
    else:
        qs = qs.filter(source__isnull=True)

    # Avoid relying on database-specific case-insensitive JSON/string operators.
    candidates = []
    for mapping in qs.order_by("-priority", "id"):
        cat_match = _normalized(mapping.source_category_match)
        sub_match = _normalized(mapping.source_subcategory_match)
        if cat_match and cat_match not in category:
            continue
        if sub_match and sub_match not in subcategory:
            continue
        if not cat_match and not sub_match:
            continue
        candidates.append(mapping)
    return candidates[0].target_category if candidates else None


def resolve_destination(item, draft):
    """Resolve destination vendor/category/brand without modifying Product data."""
    from products.models import Brand, Category

    batch = item.batch
    resolved = DestinationResolution()

    resolved.vendor = item.target_vendor or getattr(batch, "target_vendor", None)
    resolved.vendor_source = "item" if item.target_vendor_id else ("batch" if getattr(batch, "target_vendor_id", None) else "")

    resolved.category = item.target_category or getattr(batch, "default_category", None)
    resolved.category_source = "item" if item.target_category_id else ("batch" if getattr(batch, "default_category_id", None) else "")

    if not resolved.category:
        resolved.category = _category_mapping(item, draft)
        if resolved.category:
            resolved.category_source = "mapping"

    if not resolved.category:
        for value in (getattr(draft, "subcategory", ""), getattr(draft, "category", "")):
            value = str(value or "").strip()
            if not value:
                continue
            match = Category.objects.filter(name__iexact=value, is_active=True).first()
            if not match:
                match = Category.objects.filter(slug__iexact=value.replace(" ", "-"), is_active=True).first()
            if match:
                resolved.category = match
                resolved.category_source = "exact_existing_match"
                break

    resolved.brand = item.target_brand or getattr(batch, "default_brand", None)
    resolved.brand_source = "item" if item.target_brand_id else ("batch" if getattr(batch, "default_brand_id", None) else "")

    if not resolved.brand:
        for value in (getattr(draft, "brand", ""), getattr(draft, "manufacturer", "")):
            value = str(value or "").strip()
            if not value:
                continue
            match = Brand.objects.filter(name__iexact=value, is_active=True).first()
            if match:
                resolved.brand = match
                resolved.brand_source = "exact_existing_match"
                break

    return resolved
