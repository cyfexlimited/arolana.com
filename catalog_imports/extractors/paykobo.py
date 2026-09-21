import re
from typing import Any, Dict

from catalog_imports.schema import UniversalProductDraft

from .base import ProductExtractor
from .generic import GenericStructuredProductExtractor
from .registry import register_extractor


KNOWN_BRANDS = (
    "Logitech", "Jabra", "Poly", "Plantronics", "Cisco", "Yealink", "Optoma",
    "Epson", "BenQ", "Samsung", "LG", "HP", "Dell", "Lenovo", "Microsoft",
)


@register_extractor
class PaykoboExtractor(ProductExtractor):
    """Paykobo adapter layered on top of the universal structured extractor.

    This adapter does not bypass access controls. If Paykobo refuses an HTTP
    request, the fetch layer reports the block and the item remains unpublished.
    """

    key = "paykobo"

    def can_handle(self, url: str = "", source=None) -> bool:
        return "paykobo.com" in (url or "").lower()

    def extract(self, *, url: str = "", html: str = "", context: Dict[str, Any] | None = None) -> UniversalProductDraft:
        draft = GenericStructuredProductExtractor().extract(url=url, html=html, context=context or {})
        draft.source_name = "Paykobo"

        if not draft.brand:
            lowered = (draft.name or "").lower()
            for brand in KNOWN_BRANDS:
                if lowered.startswith(brand.lower() + " ") or lowered == brand.lower():
                    draft.brand = brand
                    break
        if not draft.manufacturer and draft.brand:
            draft.manufacturer = draft.brand

        if not draft.manufacturer_sku:
            # Common manufacturer-number form used by Logitech, e.g. 960-001336.
            sku_match = re.search(r"\b\d{3,4}-\d{5,8}\b", draft.name or "")
            if sku_match:
                draft.manufacturer_sku = sku_match.group(0)

        draft.evidence["adapter"] = "paykobo"
        return draft

    @staticmethod
    def contamination_patterns():
        return [
            r"\bpaykobo(?:\.com)?\b",
            r"\bssm nigeria\b",
            r"\boshifila\b",
            r"\banifowoshe\b",
            r"\bpayment on delivery\b",
            r"\bpick\s*up today\b",
        ]
