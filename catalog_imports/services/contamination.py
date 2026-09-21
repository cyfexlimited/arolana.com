import re
from typing import Dict, Iterable, List

from catalog_imports.schema import UniversalProductDraft


def _flatten_public_text(draft: UniversalProductDraft) -> Dict[str, str]:
    return {
        "name": draft.name,
        "short_description": draft.short_description,
        "description": draft.description,
        "specifications_html": draft.specifications_html,
        "meta_title": draft.meta_title,
        "meta_description": draft.meta_description,
        "meta_keywords": draft.meta_keywords,
        "shipping": str(draft.shipping),
        "warranty": str(draft.warranty),
        "images": str(draft.images),
        "videos": str(draft.videos),
    }


def scan_source_identity(
    draft: UniversalProductDraft,
    extra_patterns: Iterable[str] = (),
) -> Dict:
    """Block source-store identity from customer-facing fields.

    The current source domain is always blocked. The source display name is
    blocked unless it is also the actual product brand/manufacturer (important
    for legitimate Amazon-branded or manufacturer-direct products). Additional
    source-specific seller/contact/watermark patterns can be supplied by the
    source adapter. Internal evidence fields are never scanned.
    """
    patterns: List[str] = [p for p in extra_patterns if p]

    source_name = (draft.source_name or "").strip()
    legitimate_identity = {
        (draft.brand or "").strip().lower(),
        (draft.manufacturer or "").strip().lower(),
    }
    if source_name and source_name.lower() not in legitimate_identity:
        patterns.append(rf"\b{re.escape(source_name)}\b")

    if draft.source_url:
        match = re.match(r"https?://(?:www\.)?([^/]+)", draft.source_url.strip(), flags=re.I)
        if match:
            patterns.append(re.escape(match.group(1)))

    findings: List[Dict[str, str]] = []
    public_fields = _flatten_public_text(draft)
    for field_name, value in public_fields.items():
        text = str(value or "")
        for pattern in patterns:
            if pattern and re.search(pattern, text, flags=re.I):
                findings.append({"field": field_name, "pattern": pattern})

    return {
        "passed": not findings,
        "findings": findings,
        "checked_fields": list(public_fields.keys()),
    }
