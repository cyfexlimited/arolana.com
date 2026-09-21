import re
from dataclasses import replace
from difflib import SequenceMatcher
from typing import Dict, Iterable, List, Optional
from urllib.parse import urlparse

from catalog_imports.schema import UniversalProductDraft


_WORD_RE = re.compile(r"[a-z0-9]+", re.I)
_GENERIC_TOKENS = {
    "www", "com", "html", "product", "products", "buy", "shop", "online",
    "camera", "cameras", "video", "conferencing", "conference", "system",
}


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _tokens(value: str) -> List[str]:
    values = []
    for token in _WORD_RE.findall(str(value or "").lower()):
        if (len(token) < 2 and not token.isdigit()) or token in _GENERIC_TOKENS:
            continue
        if token not in values:
            values.append(token)
    return values


def official_domain_matches(url: str, official_domain: str) -> bool:
    host = (urlparse(url or "").hostname or "").lower().rstrip(".")
    domain = str(official_domain or "").lower().strip().lstrip(".").rstrip(".")
    if not host or not domain:
        return False
    return host == domain or host.endswith("." + domain)


def identifier_values(draft: UniversalProductDraft) -> Dict[str, str]:
    result = {}
    for field_name in ("manufacturer_sku", "model", "gtin", "ean", "upc"):
        value = str(getattr(draft, field_name, "") or "").strip()
        if value:
            result[field_name] = _norm(value)
    return result


def compare_identity(
    retailer: Optional[UniversalProductDraft],
    manufacturer: UniversalProductDraft,
    *,
    input_hint: str = "",
    expected_brand: str = "",
    official_domain_ok: bool = False,
) -> Dict:
    retailer = retailer or UniversalProductDraft()
    errors: List[str] = []
    warnings: List[str] = []

    retailer_brand = _norm(retailer.brand or retailer.manufacturer or expected_brand)
    manufacturer_brand = _norm(manufacturer.brand or manufacturer.manufacturer)
    expected_brand_norm = _norm(expected_brand)

    brand_match = True
    if expected_brand_norm and manufacturer_brand:
        brand_match = expected_brand_norm in manufacturer_brand or manufacturer_brand in expected_brand_norm
    elif retailer_brand and manufacturer_brand:
        brand_match = retailer_brand in manufacturer_brand or manufacturer_brand in retailer_brand
    if not brand_match:
        errors.append("Manufacturer evidence brand does not match the expected product brand.")

    left_ids = set(identifier_values(retailer).values())
    right_ids = set(identifier_values(manufacturer).values())
    exact_identifier_match = bool(left_ids and right_ids and left_ids.intersection(right_ids))
    identifier_conflict = bool(left_ids and right_ids and not exact_identifier_match)
    if identifier_conflict:
        errors.append("Retailer and manufacturer identifiers conflict.")

    left_name = str(retailer.name or input_hint or "").strip()
    right_name = str(manufacturer.name or "").strip()
    name_similarity = SequenceMatcher(None, _norm(left_name), _norm(right_name)).ratio() if left_name and right_name else 0.0

    parsed_hint = urlparse(str(input_hint or ""))
    hint_basis = parsed_hint.path if parsed_hint.scheme and parsed_hint.netloc else str(input_hint or "")
    hint_tokens = set(_tokens(hint_basis))
    official_tokens = set(_tokens(" ".join([
        manufacturer.name,
        manufacturer.model,
        manufacturer.manufacturer_sku,
        manufacturer.brand,
    ])))
    hint_overlap = sorted(hint_tokens.intersection(official_tokens))
    hint_coverage = (len(hint_overlap) / len(hint_tokens)) if hint_tokens else 0.0

    # Exact manufacturer identifiers are the strongest proof. If the retailer
    # could not be fetched, a matching official domain + brand + meaningful URL
    # token overlap is acceptable for a human-review draft, never auto-publish.
    strong_match = exact_identifier_match and brand_match and not errors
    fallback_match = (
        not left_ids
        and official_domain_ok
        and brand_match
        and (name_similarity >= 0.80 or (len(hint_overlap) >= 2 and hint_coverage >= 0.75))
        and not errors
    )
    passed = strong_match or fallback_match

    if not passed and not errors:
        warnings.append(
            "Manufacturer page was fetched, but exact identity still needs human confirmation."
        )

    return {
        "passed": passed,
        "brand_match": brand_match,
        "exact_identifier_match": exact_identifier_match,
        "identifier_conflict": identifier_conflict,
        "name_similarity": round(name_similarity, 4),
        "input_token_overlap": hint_overlap,
        "input_token_coverage": round(hint_coverage, 4),
        "official_domain_ok": bool(official_domain_ok),
        "errors": errors,
        "warnings": warnings,
    }


def merge_authoritative_draft(
    retailer: Optional[UniversalProductDraft],
    manufacturer: UniversalProductDraft,
) -> UniversalProductDraft:
    """Merge official manufacturer facts without ever importing its price.

    Retailer/source provenance and retailer price remain the commercial source.
    Official manufacturer evidence may replace/fill identity, specs, physical,
    warranty, manuals and product-reference media.
    """
    base = UniversalProductDraft.from_dict((retailer or UniversalProductDraft()).to_dict())

    scalar_fields = (
        "name", "brand", "manufacturer", "model", "manufacturer_sku", "gtin", "ean", "upc",
        "category", "subcategory", "short_description", "description", "specifications_html",
        "country_of_origin", "manufacturer_address", "weight", "weight_unit",
        "dimensions_length", "dimensions_width", "dimensions_height", "dimension_unit",
    )
    for field_name in scalar_fields:
        value = getattr(manufacturer, field_name, None)
        if value not in (None, "", [], {}):
            setattr(base, field_name, value)

    for field_name in ("specifications", "warranty", "shipping"):
        value = getattr(manufacturer, field_name, None)
        if value:
            setattr(base, field_name, value)

    for field_name in (
        "key_features", "package_contents", "certifications", "variants", "accessories",
        "images", "videos", "manuals", "tags",
    ):
        value = getattr(manufacturer, field_name, None)
        if value:
            setattr(base, field_name, list(value))

    # Never replace the selected retailer/source commercial price or provenance.
    if retailer:
        base.source_name = retailer.source_name
        base.source_url = retailer.source_url
        base.source_external_id = retailer.source_external_id
        base.source_price = retailer.source_price
        base.source_currency = retailer.source_currency
        base.availability = retailer.availability

    evidence = dict(base.evidence or {})
    evidence["manufacturer"] = {
        "source_url": manufacturer.source_url,
        "brand": manufacturer.brand,
        "manufacturer": manufacturer.manufacturer,
        "model": manufacturer.model,
        "manufacturer_sku": manufacturer.manufacturer_sku,
    }
    base.evidence = evidence
    return base


def supporting_urls(text: str) -> List[str]:
    result = []
    for raw in str(text or "").splitlines():
        url = raw.strip()
        if not url or not url.lower().startswith(("http://", "https://")):
            continue
        if url not in result:
            result.append(url)
    return result[:10]


def readiness_decision(
    *,
    quality_passed: bool,
    contamination_passed: bool,
    price_verified: bool,
    manufacturer_required: bool,
    identity_verified: bool,
) -> Dict:
    reasons = []
    if not quality_passed:
        reasons.append("quality_checks_failed")
    if not contamination_passed:
        reasons.append("source_contamination")
    if not price_verified:
        reasons.append("source_price_unverified")
    if manufacturer_required and not identity_verified:
        reasons.append("manufacturer_verification_required")
    return {"ready": not reasons, "reasons": reasons}
