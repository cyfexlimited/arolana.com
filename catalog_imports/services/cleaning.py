import copy
import re
from typing import Iterable

from catalog_imports.schema import UniversalProductDraft


def _clean_text(value: str, patterns: Iterable[str]) -> str:
    text = str(value or "")
    if not text:
        return ""
    # Remove complete sentence/line fragments containing source identity rather
    # than trying to disguise copied seller-specific promotional copy.
    chunks = re.split(r"(?<=[.!?])\s+|[\r\n]+", text)
    kept = []
    for chunk in chunks:
        if any(re.search(pattern, chunk, flags=re.I) for pattern in patterns if pattern):
            continue
        chunk = re.sub(r"\s+", " ", chunk).strip()
        if chunk:
            kept.append(chunk)
    return " ".join(kept).strip()


def clean_source_identity(draft: UniversalProductDraft, patterns: Iterable[str]) -> UniversalProductDraft:
    cleaned = copy.deepcopy(draft)
    patterns = list(patterns or [])
    cleaned.short_description = _clean_text(cleaned.short_description, patterns)
    cleaned.description = _clean_text(cleaned.description, patterns)
    cleaned.specifications_html = _clean_text(cleaned.specifications_html, patterns)
    cleaned.meta_title = _clean_text(cleaned.meta_title, patterns)
    cleaned.meta_description = _clean_text(cleaned.meta_description, patterns)
    cleaned.meta_keywords = _clean_text(cleaned.meta_keywords, patterns)
    # Reference images are internal evidence in Phase 2 and are not customer-facing.
    return cleaned
