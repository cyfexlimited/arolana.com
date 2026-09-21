import json
import re
from decimal import Decimal, InvalidOperation
from html import unescape
from typing import Any, Dict, Iterable, List
from urllib.parse import urlparse

from catalog_imports.schema import UniversalProductDraft

from .base import ProductExtractor
from .registry import register_extractor


JSON_LD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    flags=re.I | re.S,
)
META_RE = re.compile(r'<meta\s+([^>]+)>', flags=re.I | re.S)
ATTR_RE = re.compile(r'([:\w-]+)\s*=\s*(["\'])(.*?)\2', flags=re.I | re.S)
TITLE_RE = re.compile(r'<title[^>]*>(.*?)</title>', flags=re.I | re.S)
TAG_RE = re.compile(r"<[^>]+>", flags=re.S)
TR_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", flags=re.I | re.S)
CELL_RE = re.compile(r"<(?:th|td)[^>]*>(.*?)</(?:th|td)>", flags=re.I | re.S)
DTDD_RE = re.compile(r"<dt[^>]*>(.*?)</dt>\s*<dd[^>]*>(.*?)</dd>", flags=re.I | re.S)


def _walk_json(value: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from _walk_json(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_json(nested)


def _type_contains_product(value: Any) -> bool:
    product_types = value.get("@type") if isinstance(value, dict) else None
    if isinstance(product_types, str):
        return product_types.lower() == "product"
    if isinstance(product_types, list):
        return any(str(item).lower() == "product" for item in product_types)
    return False


def _first_offer(product: Dict[str, Any]) -> Dict[str, Any]:
    offers = product.get("offers") or {}
    if isinstance(offers, list):
        return next((item for item in offers if isinstance(item, dict)), {})
    return offers if isinstance(offers, dict) else {}


def _decimal(value):
    if value in (None, ""):
        return None
    cleaned = re.sub(r"[^0-9.\-]", "", str(value))
    try:
        return Decimal(cleaned) if cleaned else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def _meta_map(html: str) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for raw in META_RE.findall(html or ""):
        attrs = {key.lower(): unescape(value).strip() for key, _quote, value in ATTR_RE.findall(raw)}
        key = attrs.get("property") or attrs.get("name") or attrs.get("itemprop")
        value = attrs.get("content")
        if key and value and key.lower() not in result:
            result[key.lower()] = value
    return result


def _plain(value: Any) -> str:
    text = TAG_RE.sub(" ", str(value or ""))
    return re.sub(r"\s+", " ", unescape(text)).strip()


def _property_value_specs(product: Dict[str, Any]) -> Dict[str, str]:
    specs: Dict[str, str] = {}
    values = product.get("additionalProperty") or []
    if isinstance(values, dict):
        values = [values]
    if isinstance(values, list):
        for item in values:
            if not isinstance(item, dict):
                continue
            name = _plain(item.get("name") or item.get("propertyID") or "")
            value = item.get("value")
            if isinstance(value, dict):
                value = value.get("value") or value.get("name") or ""
            value = _plain(value)
            if name and value and len(name) <= 120 and len(value) <= 500:
                specs.setdefault(name, value)
    return specs


def _html_spec_pairs(html: str) -> Dict[str, str]:
    """Conservative source-neutral extraction of label/value spec rows.

    Only simple 2-cell table rows and dt/dd pairs are accepted. This does not
    use retailer/manufacturer-specific selectors.
    """
    specs: Dict[str, str] = {}
    for row in TR_RE.findall(html or ""):
        cells = [_plain(cell) for cell in CELL_RE.findall(row)]
        cells = [cell for cell in cells if cell]
        if len(cells) != 2:
            continue
        name, value = cells
        if not (1 <= len(name) <= 100 and 1 <= len(value) <= 500):
            continue
        # Skip obvious commerce/navigation rows rather than treating them as specs.
        if name.lower() in {"price", "quantity", "subtotal", "total", "add to cart"}:
            continue
        specs.setdefault(name, value)
        if len(specs) >= 80:
            break
    if len(specs) < 80:
        for raw_name, raw_value in DTDD_RE.findall(html or ""):
            name, value = _plain(raw_name), _plain(raw_value)
            if name and value and len(name) <= 100 and len(value) <= 500:
                specs.setdefault(name, value)
            if len(specs) >= 80:
                break
    return specs


def _quantity(value: Any):
    if isinstance(value, dict):
        amount = value.get("value")
        unit = value.get("unitText") or value.get("unitCode") or ""
        if amount not in (None, ""):
            return f"{amount} {unit}".strip()
    if value not in (None, ""):
        return str(value).strip()
    return ""


def _unique(values: Iterable[str]) -> List[str]:
    seen = set()
    result = []
    for value in values:
        value = str(value or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


@register_extractor
class GenericStructuredProductExtractor(ProductExtractor):
    """Source-neutral Product extractor.

    Priority:
    1. Schema.org Product JSON-LD.
    2. Common OpenGraph/product meta fields.

    It intentionally avoids store-specific CSS selectors. Dedicated adapters
    can enrich the generic result without changing this extractor.
    """

    key = "generic"

    def can_handle(self, url: str = "", source=None) -> bool:
        return bool(url and urlparse(url).scheme in {"http", "https"})

    def extract(self, *, url: str = "", html: str = "", context: Dict[str, Any] | None = None) -> UniversalProductDraft:
        context = context or {}
        candidates = []
        for raw in JSON_LD_RE.findall(html or ""):
            raw = unescape(raw).strip()
            if not raw:
                continue
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                continue
            candidates.extend(item for item in _walk_json(parsed) if _type_contains_product(item))

        if candidates:
            product = candidates[0]
            offer = _first_offer(product)
            brand = product.get("brand") or ""
            if isinstance(brand, dict):
                brand = brand.get("name") or ""
            manufacturer = product.get("manufacturer") or ""
            if isinstance(manufacturer, dict):
                manufacturer = manufacturer.get("name") or ""
            images = product.get("image") or []
            if isinstance(images, str):
                images = [images]
            elif isinstance(images, dict):
                images = [images.get("url")] if images.get("url") else []
            specs = _property_value_specs(product)
            for key, value in _html_spec_pairs(html).items():
                specs.setdefault(key, value)
            category = product.get("category") or ""
            if isinstance(category, dict):
                category = category.get("name") or ""
            return UniversalProductDraft(
                source_url=url,
                name=str(product.get("name") or "").strip(),
                brand=str(brand or "").strip(),
                manufacturer=str(manufacturer or "").strip(),
                model=str(product.get("model") or "").strip(),
                manufacturer_sku=str(product.get("sku") or product.get("mpn") or "").strip(),
                gtin=str(product.get("gtin") or product.get("gtin13") or product.get("gtin14") or "").strip(),
                category=str(category or "").strip(),
                description=str(product.get("description") or "").strip(),
                specifications=specs,
                source_price=_decimal(offer.get("price") or offer.get("lowPrice")),
                source_currency=str(offer.get("priceCurrency") or context.get("default_currency") or "NGN").upper(),
                availability=str(offer.get("availability") or ""),
                images=[{"reference_url": image, "source_kind": "reference"} for image in _unique(images)],
                evidence={"extraction": "json_ld", "json_ld_product": product},
            )

        meta = _meta_map(html)
        title_match = TITLE_RE.search(html or "")
        name = meta.get("og:title") or meta.get("twitter:title") or (unescape(title_match.group(1)).strip() if title_match else "")
        description = meta.get("og:description") or meta.get("description") or meta.get("twitter:description") or ""
        price = _decimal(
            meta.get("product:price:amount")
            or meta.get("og:price:amount")
            or meta.get("price")
        )
        currency = (
            meta.get("product:price:currency")
            or meta.get("og:price:currency")
            or meta.get("pricecurrency")
            or context.get("default_currency")
            or "NGN"
        )
        images = _unique([
            meta.get("og:image", ""),
            meta.get("twitter:image", ""),
            meta.get("image", ""),
        ])
        brand = meta.get("product:brand") or meta.get("brand") or ""
        sku = meta.get("product:retailer_item_id") or meta.get("sku") or meta.get("mpn") or ""

        if not name and price is None and not images:
            raise ValueError("No Schema.org Product or usable product metadata found. A dedicated source adapter/API may be required.")

        return UniversalProductDraft(
            source_url=url,
            name=name,
            brand=brand,
            manufacturer_sku=sku,
            description=description,
            specifications=_html_spec_pairs(html),
            source_price=price,
            source_currency=str(currency).upper(),
            images=[{"reference_url": image, "source_kind": "reference"} for image in images],
            evidence={"extraction": "meta", "meta": meta},
        )
