"""Web-grounded manufacturer evidence fallback.

Purpose
-------
Some legitimate retailer/manufacturer websites return 403 to Arolana's direct,
polite HTTP importer.  We never bypass those controls.

When direct manufacturer fetching is blocked, this module can use a configured
hosted web-search provider to retrieve already-indexed public manufacturer facts.
The first provider implementation uses the existing OPENAI_API_KEY and the
Responses API web_search tool.

Safety
------
- Search is restricted to explicitly trusted manufacturer domains:
  BrandVerificationProfile.official_domain, batch.default_brand.website,
  item.manufacturer_url and secondary manufacturer evidence hosts.
- Retailer price is never requested or accepted here.
- Exact identity is not trusted solely because a model says "confirmed".
  A deterministic identifier/name check must tie the returned official product
  back to the original input URL/name.
- Only URLs from the allowed manufacturer domains are retained as evidence.
- A failed/ambiguous search leaves the item on hold.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Dict, Iterable, List
from urllib.parse import urlparse

from django.conf import settings

from catalog_imports.schema import UniversalProductDraft
from catalog_imports.services.evidence import official_domain_matches, supporting_urls
from catalog_imports.services.http_fetch import _build_ssl_context


DEFAULT_ENDPOINT = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-5.6-luna"


class WebEvidenceUnavailable(RuntimeError):
    pass


class WebEvidenceRejected(ValueError):
    pass


def _setting(name, default=None):
    value = getattr(settings, name, None)
    if value not in (None, ""):
        return value
    return os.environ.get(name, default)


def _host(url: str) -> str:
    return (urlparse(str(url or "")).hostname or "").lower().strip(".")    


def _normalize_domain(value: str) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    if "://" in raw:
        raw = _host(raw)
    raw = raw.strip().strip("/")
    if raw.startswith("www."):
        raw = raw[4:]
    return raw


def _url_allowed(url: str, allowed_domains: Iterable[str]) -> bool:
    host = _host(url)
    if not host:
        return False
    for raw in allowed_domains:
        domain = _normalize_domain(raw)
        if not domain:
            continue
        if host == domain or host.endswith("." + domain):
            return True
        # Exact host filters like pro.sony should also accept themselves after
        # www normalization.
        if host.startswith("www.") and host[4:] == domain:
            return True
    return False


def _brand_website_domain(item) -> str:
    brand = getattr(getattr(item, "batch", None), "default_brand", None)
    website = str(getattr(brand, "website", "") or "").strip()
    return _normalize_domain(website)


def _profile_domain(profile) -> str:
    return _normalize_domain(getattr(profile, "official_domain", "") if profile else "")


def trusted_manufacturer_domains(item, profile=None) -> List[str]:
    """Build a bounded manufacturer-only domain allowlist.

    Direct admin-supplied manufacturer/secondary URLs are valid discovery anchors,
    but returned web evidence must still pass exact-identity checks.
    """
    domains: List[str] = []

    def add(value):
        domain = _normalize_domain(value)
        if domain and domain not in domains:
            domains.append(domain)

    add(_profile_domain(profile))
    add(_brand_website_domain(item))
    add(getattr(item, "manufacturer_url", ""))

    for url in supporting_urls(getattr(item, "secondary_evidence_urls", "")):
        add(url)

    return domains[:20]


def expected_brand_name(item, profile=None) -> str:
    if profile and str(getattr(profile, "brand_name", "") or "").strip():
        return str(profile.brand_name).strip()
    brand = getattr(getattr(item, "batch", None), "default_brand", None)
    if brand and str(getattr(brand, "name", "") or "").strip():
        return str(brand.name).strip()

    normalized = getattr(item, "normalized_payload", None) or {}
    value = str(
        normalized.get("brand")
        or normalized.get("manufacturer")
        or ""
    ).strip()
    if value:
        return value

    # A blocked retailer may have been recovered through the retailer-domain
    # web-search fallback before manufacturer discovery starts.
    try:
        evidence = (
            item.evidence_records
            .filter(role="retailer", status="fetched")
            .order_by("-id")
            .first()
        )
    except Exception:
        evidence = None
    payload = getattr(evidence, "extracted_payload", None) or {}
    return str(
        payload.get("brand")
        or payload.get("manufacturer")
        or ""
    ).strip()


def _compact(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(text or "").lower())


def _tokens(text: str) -> List[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9]+", str(text or "").lower())
        if len(token) >= 2
    ]


def deterministic_identity_check(input_hint: str, payload: Dict, expected_brand: str = "") -> Dict:
    """Tie web-grounded identity back to the original input without guessing."""
    input_compact = _compact(input_hint)
    expected_brand_compact = _compact(expected_brand)
    brand = str(payload.get("brand") or payload.get("manufacturer") or "").strip()
    brand_compact = _compact(brand)

    identifiers = []
    for key in ("model", "manufacturer_sku", "gtin", "ean", "upc"):
        value = str(payload.get(key) or "").strip()
        compact = _compact(value)
        if len(compact) >= 4 and compact not in identifiers:
            identifiers.append(compact)

    identifier_match = any(identifier in input_compact for identifier in identifiers)

    name = str(payload.get("name") or "").strip()
    name_tokens = set(_tokens(name))
    hint_tokens = set(_tokens(input_hint))
    meaningful_name_overlap = len(name_tokens.intersection(hint_tokens)) >= 2

    brand_match = True
    if expected_brand_compact:
        brand_match = bool(
            brand_compact
            and (
                brand_compact == expected_brand_compact
                or brand_compact in expected_brand_compact
                or expected_brand_compact in brand_compact
            )
        )

    provider_confirmed = bool(payload.get("exact_identity_confirmed"))

    # Exact-model rule:
    # If the manufacturer result gives us any concrete product identifier
    # (model/SKU/GTIN/EAN/UPC), that identifier must be present in the original
    # retailer input.  Name-token overlap must NOT rescue a conflicting model.
    #
    # Example:
    #   input:  ...sony_pxw_z200...
    #   result: Sony PXW-Z190
    # Both share "sony" + "pxw", but they are different products.
    #
    # Name overlap is only a fallback when the manufacturer evidence itself
    # supplies no concrete identifier at all.
    if identifiers:
        exact_identity_link = identifier_match
        identity_rule = "explicit_identifier_required"
    else:
        exact_identity_link = meaningful_name_overlap
        identity_rule = "name_overlap_fallback_no_identifier"

    passed = bool(
        provider_confirmed
        and brand_match
        and exact_identity_link
    )

    return {
        "passed": passed,
        "provider_confirmed": provider_confirmed,
        "brand_match": brand_match,
        "identifier_match": identifier_match,
        "meaningful_name_overlap": meaningful_name_overlap,
        "identifiers": identifiers,
        "identity_rule": identity_rule,
    }


def _response_output_text(data: Dict) -> str:
    chunks = []
    for item in data.get("output", []) or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for content in item.get("content", []) or []:
            if isinstance(content, dict) and content.get("type") == "output_text":
                text = str(content.get("text") or "")
                if text:
                    chunks.append(text)
    return "\n".join(chunks).strip()


def _response_sources(data: Dict) -> List[str]:
    urls = []
    for item in data.get("output", []) or []:
        if not isinstance(item, dict) or item.get("type") != "web_search_call":
            continue
        action = item.get("action") or {}
        for source in action.get("sources", []) or []:
            if isinstance(source, dict):
                url = str(source.get("url") or "").strip()
                if url and url not in urls:
                    urls.append(url)
    return urls


def _parse_json_object(text: str) -> Dict:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        first = raw.find("{")
        last = raw.rfind("}")
        if first < 0 or last <= first:
            raise WebEvidenceRejected("Web evidence provider did not return a JSON object.")
        value = json.loads(raw[first:last + 1])
    if not isinstance(value, dict):
        raise WebEvidenceRejected("Web evidence provider returned an invalid payload.")
    return value


def _safe_number(value):
    if value in (None, ""):
        return None
    try:
        number = float(str(value))
    except (TypeError, ValueError):
        return None
    if number < 0:
        return None
    return str(value).strip()


def _safe_weight_unit(value):
    value = str(value or "").strip().lower()
    aliases = {
        "lbs": "lb",
        "pound": "lb",
        "pounds": "lb",
        "kilogram": "kg",
        "kilograms": "kg",
        "gram": "g",
        "grams": "g",
        "ounce": "oz",
        "ounces": "oz",
    }
    value = aliases.get(value, value)
    return value if value in {"g", "kg", "lb", "oz"} else ""


def _safe_dimension_unit(value):
    value = str(value or "").strip().lower()
    aliases = {
        "millimeter": "mm",
        "millimeters": "mm",
        "centimeter": "cm",
        "centimeters": "cm",
        "meter": "m",
        "meters": "m",
        "inch": "in",
        "inches": "in",
    }
    value = aliases.get(value, value)
    return value if value in {"mm", "cm", "m", "in"} else ""


def _safe_warranty(payload):
    value = payload if isinstance(payload, dict) else {}
    return {
        "provider": str(value.get("provider") or "").strip(),
        "duration_years": max(int(value.get("duration_years") or 0), 0)
            if str(value.get("duration_years") or "0").isdigit() else 0,
        "duration_months": max(int(value.get("duration_months") or 0), 0)
            if str(value.get("duration_months") or "0").isdigit() else 0,
        "coverage_details": str(value.get("coverage_details") or "").strip(),
        "exclusions": str(value.get("exclusions") or "").strip(),
        "registration_required": bool(value.get("registration_required", False)),
        "registration_url": str(value.get("registration_url") or "").strip(),
        "terms_url": str(value.get("terms_url") or "").strip(),
        "customer_support_phone": str(value.get("customer_support_phone") or "").strip(),
        "customer_support_email": str(value.get("customer_support_email") or "").strip(),
    }


def _safe_shipping(payload):
    value = payload if isinstance(payload, dict) else {}
    # Manufacturer evidence can support package/handling facts, but it must not
    # invent seller/vendor delivery promises or free-shipping claims.
    return {
        "weight_shipping": _safe_number(value.get("weight_shipping")),
        "weight_shipping_unit": _safe_weight_unit(value.get("weight_shipping_unit")),
        "dimensions_package": str(value.get("dimensions_package") or "").strip()[:100],
        "shipping_restrictions": str(value.get("shipping_restrictions") or "").strip(),
        "hazmat": bool(value.get("hazmat", False)) if "hazmat" in value else None,
    }


def _sanitize_payload(payload: Dict, allowed_domains: List[str], consulted_sources: List[str]) -> Dict:
    clean = {
        "exact_identity_confirmed": bool(payload.get("exact_identity_confirmed")),
        "official_product_url": str(payload.get("official_product_url") or "").strip(),
        "name": str(payload.get("name") or "").strip(),
        "brand": str(payload.get("brand") or "").strip(),
        "manufacturer": str(payload.get("manufacturer") or "").strip(),
        "model": str(payload.get("model") or "").strip(),
        "manufacturer_sku": str(payload.get("manufacturer_sku") or "").strip(),
        "gtin": str(payload.get("gtin") or "").strip(),
        "ean": str(payload.get("ean") or "").strip(),
        "upc": str(payload.get("upc") or "").strip(),
        "category": str(payload.get("category") or "").strip(),
        "subcategory": str(payload.get("subcategory") or "").strip(),
        "short_description": str(payload.get("short_description") or "").strip(),
        "description": str(payload.get("description") or "").strip(),
        "specifications": payload.get("specifications") if isinstance(payload.get("specifications"), dict) else {},
        "key_features": payload.get("key_features") if isinstance(payload.get("key_features"), list) else [],
        "package_contents": payload.get("package_contents") if isinstance(payload.get("package_contents"), list) else [],
        "country_of_origin": str(payload.get("country_of_origin") or "").strip(),
        "manufacturer_address": str(payload.get("manufacturer_address") or "").strip(),
        "certifications": payload.get("certifications") if isinstance(payload.get("certifications"), list) else [],
        "weight": _safe_number(payload.get("weight")),
        "weight_unit": _safe_weight_unit(payload.get("weight_unit")),
        "dimensions_length": _safe_number(payload.get("dimensions_length")),
        "dimensions_width": _safe_number(payload.get("dimensions_width")),
        "dimensions_height": _safe_number(payload.get("dimensions_height")),
        "dimension_unit": _safe_dimension_unit(payload.get("dimension_unit")),
        "warranty": _safe_warranty(payload.get("warranty")),
        "shipping": _safe_shipping(payload.get("shipping")),
        "manuals": payload.get("manuals") if isinstance(payload.get("manuals"), list) else [],
    }

    # Explicitly ignore any commercial pricing accidentally emitted by a model.
    for forbidden in ("price", "source_price", "currency", "source_currency", "msrp"):
        clean.pop(forbidden, None)

    evidence_urls = []
    for url in (payload.get("evidence_urls") or []) + consulted_sources:
        url = str(url or "").strip()
        if url and _url_allowed(url, allowed_domains) and url not in evidence_urls:
            evidence_urls.append(url)
    clean["evidence_urls"] = evidence_urls[:20]

    if clean["official_product_url"] and not _url_allowed(clean["official_product_url"], allowed_domains):
        clean["official_product_url"] = ""

    for field_name in ("registration_url", "terms_url"):
        value = str((clean.get("warranty") or {}).get(field_name) or "").strip()
        if value and not _url_allowed(value, allowed_domains):
            clean["warranty"][field_name] = ""

    # Manuals must also stay on the explicitly trusted manufacturer domains.
    clean["manuals"] = [
        str(url).strip()
        for url in clean["manuals"]
        if isinstance(url, str) and _url_allowed(url, allowed_domains)
    ][:10]

    return clean


def _provider_request(prompt: str, allowed_domains=None) -> Dict:
    api_key = str(_setting("OPENAI_API_KEY", "") or "").strip()
    if not api_key:
        raise WebEvidenceUnavailable("OPENAI_API_KEY is not configured.")

    endpoint = str(
        _setting("CATALOG_IMPORT_WEB_EVIDENCE_ENDPOINT", DEFAULT_ENDPOINT)
        or DEFAULT_ENDPOINT
    ).strip()
    model = str(
        _setting("CATALOG_IMPORT_WEB_EVIDENCE_MODEL", DEFAULT_MODEL)
        or DEFAULT_MODEL
    ).strip()
    timeout = int(_setting("CATALOG_IMPORT_WEB_EVIDENCE_TIMEOUT_SECONDS", "45") or 45)

    web_search_tool = {"type": "web_search"}
    if allowed_domains:
        web_search_tool["filters"] = {
            "allowed_domains": [
                _normalize_domain(value)
                for value in allowed_domains
                if _normalize_domain(value)
            ]
        }

    payload = {
        "model": model,
        "reasoning": {"effort": "low"},
        "tools": [web_search_tool],
        "tool_choice": "auto",
        "include": ["web_search_call.action.sources"],
        "input": prompt,
    }

    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "ArolanaProductImporter/5.2",
        },
        method="POST",
    )
    try:
        ssl_context = _build_ssl_context()
        with urllib.request.urlopen(
            request,
            timeout=timeout,
            context=ssl_context,
        ) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            detail = ""
        raise WebEvidenceUnavailable(
            f"Web evidence provider returned HTTP {exc.code}. {detail}".strip()
        ) from exc
    except Exception as exc:
        message = str(exc)
        if "CERTIFICATE_VERIFY_FAILED" in message or "certificate verify failed" in message.lower():
            raise WebEvidenceUnavailable(
                "Web evidence provider TLS certificate verification failed even with the "
                "configured/certifi CA bundle. Certificate verification remains enabled."
            ) from exc
        raise WebEvidenceUnavailable(f"Web evidence provider failed: {exc}") from exc

    return data




def _retailer_domain(item, source=None) -> str:
    configured = _normalize_domain(getattr(source, "domain", "") if source else "")
    if configured:
        return configured
    return _normalize_domain(
        getattr(item, "source_url", "")
        or getattr(item, "input_value", "")
    )


def _product_path_signatures(item) -> List[str]:
    """Return strong source-listing signatures from admin input.

    This deliberately ignores tiny/generic path tokens.  A long style/product
    id such as 2675013086 can safely tie an indexed search result back to the
    exact selected retailer listing even when the retailer changes an internal
    category segment in the canonical URL.
    """
    values: List[str] = []

    external = _compact(getattr(item, "source_external_id", "") or "")
    if len(external) >= 4:
        values.append(external)

    raw_url = str(
        getattr(item, "source_url", "")
        or getattr(item, "input_value", "")
        or ""
    ).strip()
    parsed = urlparse(raw_url)

    for token in re.findall(r"[A-Za-z0-9_-]+", parsed.path + " " + parsed.query):
        compact = _compact(token)
        if len(compact) >= 6 and compact not in {
            "product", "products", "catalog", "catalogue", "officecatalog",
        }:
            if compact not in values:
                values.append(compact)

    # Prefer a final long numeric/alphanumeric URL id first.
    tail = _compact(parsed.path.rstrip("/").split("/")[-1] if parsed.path else "")
    if len(tail) >= 6:
        values = [tail] + [value for value in values if value != tail]

    return values[:12]


def _retailer_identity_hint(item) -> str:
    parts = [str(getattr(item, "input_value", "") or "").strip()]
    source_external_id = str(getattr(item, "source_external_id", "") or "").strip()
    if source_external_id:
        parts.append(f"Admin source external id: {source_external_id}")

    # Include previously recovered retailer identity so manufacturer discovery
    # can match an SKU that was not present in the original URL.
    try:
        evidence = (
            item.evidence_records
            .filter(role="retailer", status="fetched")
            .order_by("-id")
            .first()
        )
    except Exception:
        evidence = None

    payload = getattr(evidence, "extracted_payload", None) or {}
    for key in (
        "name", "brand", "manufacturer", "model", "manufacturer_sku",
        "source_external_id", "style_number", "gtin", "ean", "upc",
    ):
        value = str(payload.get(key) or "").strip()
        if value:
            parts.append(f"{key}: {value}")

    return "\n".join(part for part in parts if part)


def _sanitize_retailer_payload(payload: Dict, allowed_domains: List[str], consulted_sources: List[str], default_currency: str) -> Dict:
    clean = {
        "exact_source_listing_confirmed": bool(payload.get("exact_source_listing_confirmed")),
        "retailer_product_url": str(payload.get("retailer_product_url") or "").strip(),
        "source_external_id": str(payload.get("source_external_id") or "").strip(),
        "style_number": str(payload.get("style_number") or "").strip(),
        "name": str(payload.get("name") or "").strip(),
        "brand": str(payload.get("brand") or "").strip(),
        "manufacturer": str(payload.get("manufacturer") or "").strip(),
        "model": str(payload.get("model") or "").strip(),
        "manufacturer_sku": str(payload.get("manufacturer_sku") or "").strip(),
        "gtin": str(payload.get("gtin") or "").strip(),
        "ean": str(payload.get("ean") or "").strip(),
        "upc": str(payload.get("upc") or "").strip(),
        "category": str(payload.get("category") or "").strip(),
        "subcategory": str(payload.get("subcategory") or "").strip(),
        "availability": str(payload.get("availability") or "").strip(),
        "source_price": _safe_number(payload.get("source_price")),
        "source_currency": str(payload.get("source_currency") or default_currency or "").strip().upper(),
        "specifications": payload.get("specifications") if isinstance(payload.get("specifications"), dict) else {},
        "key_features": payload.get("key_features") if isinstance(payload.get("key_features"), list) else [],
        "variants": payload.get("variants") if isinstance(payload.get("variants"), list) else [],
    }

    if clean["retailer_product_url"] and not _url_allowed(clean["retailer_product_url"], allowed_domains):
        clean["retailer_product_url"] = ""

    evidence_urls = []
    for url in (payload.get("evidence_urls") or []) + consulted_sources:
        url = str(url or "").strip()
        if url and _url_allowed(url, allowed_domains) and url not in evidence_urls:
            evidence_urls.append(url)
    clean["evidence_urls"] = evidence_urls[:20]

    # Retailer fallback is intentionally factual/minimal. We do not ingest
    # retailer marketing prose into Arolana storefront copy.
    return clean


def retrieve_retailer_web_evidence(item, *, source=None) -> Dict:
    """Recover exact retailer identity + price from indexed public source pages.

    Used only after/when direct retailer HTTP access is unavailable.  This is NOT
    an anti-bot bypass: the provider searches already-indexed public web results
    restricted to the selected retailer domain.

    Price may be accepted only when:
    - exact selected listing is deterministically tied to the input,
    - consulted evidence stays on the selected retailer domain,
    - the returned currency matches the configured source currency.
    """
    enabled = str(_setting("CATALOG_IMPORT_RETAILER_WEB_FALLBACK_ENABLED", "1") or "1").lower()
    if enabled in {"0", "false", "no", "off"}:
        return {"status": "disabled", "verified": False}

    domain = _retailer_domain(item, source=source)
    if not domain:
        return {
            "status": "no_source_domain",
            "verified": False,
            "reason": "Selected retailer/source domain is unavailable.",
        }

    allowed_domains = [domain]
    default_currency = str(getattr(source, "default_currency", "") or "").strip().upper()
    input_url = str(
        getattr(item, "source_url", "")
        or getattr(item, "input_value", "")
        or ""
    ).strip()
    source_external_id = str(getattr(item, "source_external_id", "") or "").strip()
    signatures = _product_path_signatures(item)

    prompt = f"""
You are Arolana's retailer/source evidence recovery service.

Search ONLY the selected retailer domain: {domain}

The retailer blocks Arolana's normal direct HTTP importer. Do NOT bypass the
retailer's controls. Use only already-indexed public search evidence.

Exact selected retailer listing:
{input_url}

Admin source external id:
{source_external_id or "(none)"}

Strong URL/listing signatures:
{", ".join(signatures) or "(none)"}

Configured source currency:
{default_currency or "(unknown)"}

Your task:
1. Find the exact selected retailer product listing, not a similar product.
2. Preserve retailer/source price exactly as currently shown by that retailer.
3. Extract factual identity fields needed to discover the official manufacturer.
4. Extract factual category/spec/variant facts only when clearly shown.
5. Do NOT copy retailer marketing prose as Arolana description.
6. Do NOT use manufacturer/marketplace/other retailer prices.
7. If the exact listing cannot be established, set exact_source_listing_confirmed=false.
8. Return JSON only.

JSON schema:
{{
  "exact_source_listing_confirmed": true_or_false,
  "retailer_product_url": "",
  "source_external_id": "",
  "style_number": "",
  "name": "",
  "brand": "",
  "manufacturer": "",
  "model": "",
  "manufacturer_sku": "",
  "gtin": "",
  "ean": "",
  "upc": "",
  "category": "",
  "subcategory": "",
  "availability": "",
  "source_price": null,
  "source_currency": "{default_currency}",
  "specifications": {{}},
  "key_features": [],
  "variants": [],
  "evidence_urls": []
}}
""".strip()

    try:
        raw_response = _provider_request(prompt, allowed_domains=allowed_domains)
        provider_payload = _parse_json_object(_response_output_text(raw_response))
        consulted = _response_sources(raw_response)
        payload = _sanitize_retailer_payload(
            provider_payload,
            allowed_domains,
            consulted,
            default_currency,
        )
    except (WebEvidenceUnavailable, WebEvidenceRejected) as exc:
        return {
            "status": "provider_failed",
            "verified": False,
            "allowed_domains": allowed_domains,
            "error": str(exc),
        }

    candidate_url = payload.get("retailer_product_url") or (
        (payload.get("evidence_urls") or [""])[0]
    )
    candidate_host_ok = bool(candidate_url and _url_allowed(candidate_url, allowed_domains))
    consulted_same_source = any(_url_allowed(url, allowed_domains) for url in consulted)

    haystack = _compact(
        " ".join(
            [
                candidate_url,
                payload.get("source_external_id", ""),
                payload.get("style_number", ""),
                payload.get("manufacturer_sku", ""),
            ]
        )
    )
    signature_match = any(signature in haystack for signature in signatures) if signatures else False

    # If there is no strong URL signature, exact URL equality can still support
    # the source link, but we fail closed rather than trusting name similarity.
    if not signature_match and not signatures:
        signature_match = (
            _compact(candidate_url.rstrip("/"))
            == _compact(input_url.rstrip("/"))
        )

    listing_verified = bool(
        payload.get("exact_source_listing_confirmed")
        and candidate_host_ok
        and consulted_same_source
        and signature_match
        and payload.get("name")
        and payload.get("brand")
    )

    returned_currency = str(payload.get("source_currency") or "").upper()
    currency_ok = bool(
        not default_currency
        or returned_currency == default_currency
    )
    price_verified = bool(
        listing_verified
        and payload.get("source_price") not in (None, "")
        and currency_ok
    )

    if not listing_verified:
        return {
            "status": "needs_confirmation",
            "verified": False,
            "price_verified": False,
            "allowed_domains": allowed_domains,
            "signatures": signatures,
            "signature_match": signature_match,
            "consulted_same_source": consulted_same_source,
            "payload": payload,
            "reason": "Indexed retailer evidence could not be tied deterministically to the exact selected listing.",
        }

    draft_data = {
        "source_name": str(getattr(source, "name", "") or domain),
        "source_url": candidate_url or input_url,
        "source_external_id": (
            payload.get("source_external_id")
            or payload.get("style_number")
            or source_external_id
        ),
        "name": payload.get("name"),
        "brand": payload.get("brand"),
        "manufacturer": payload.get("manufacturer") or payload.get("brand"),
        "model": payload.get("model"),
        "manufacturer_sku": payload.get("manufacturer_sku"),
        "gtin": payload.get("gtin"),
        "ean": payload.get("ean"),
        "upc": payload.get("upc"),
        "category": payload.get("category"),
        "subcategory": payload.get("subcategory"),
        "availability": payload.get("availability"),
        "source_price": payload.get("source_price") if price_verified else None,
        "source_currency": returned_currency or default_currency,
        "specifications": payload.get("specifications") or {},
        "key_features": payload.get("key_features") or [],
        "variants": payload.get("variants") or [],
        "short_description": "",
        "description": "",
    }

    draft = UniversalProductDraft.from_dict(draft_data)

    return {
        "status": "verified",
        "verified": True,
        "price_verified": price_verified,
        "provider": "openai_web_search",
        "allowed_domains": allowed_domains,
        "signatures": signatures,
        "signature_match": signature_match,
        "currency_ok": currency_ok,
        "consulted_same_source": consulted_same_source,
        "payload": payload,
        "draft": draft,
        "evidence_urls": payload.get("evidence_urls") or [],
        "retailer_product_url": candidate_url or input_url,
    }


_RETAILER_HOST_HINTS = {
    "amazon", "ebay", "walmart", "bhphotovideo", "bestbuy", "newegg",
    "aliexpress", "jumia", "konga", "paykobo", "jiji", "etsy",
}


def _source_host(item) -> str:
    return _host(
        getattr(item, "source_url", "")
        or getattr(item, "input_value", "")
    )


def _brand_domain_tokens(brand: str):
    value = str(brand or "").lower()
    tokens = [
        token
        for token in re.findall(r"[a-z0-9]+", value)
        if len(token) >= 2
    ]
    compact = _compact(value)
    if compact and compact not in tokens:
        tokens.append(compact)
    return tokens


def _host_looks_like_brand(host: str, brand: str) -> bool:
    host = _normalize_domain(host)
    if not host or not brand:
        return False

    source_tokens = set(re.findall(r"[a-z0-9]+", host))
    brand_tokens = _brand_domain_tokens(brand)

    for token in brand_tokens:
        if token in source_tokens:
            return True
        if len(token) >= 3 and token in _compact(host):
            return True
    return False


def _looks_like_retailer_host(host: str) -> bool:
    compact = _compact(host)
    return any(hint in compact for hint in _RETAILER_HOST_HINTS)


def discover_manufacturer_web_identity(item, *, profile=None) -> Dict:
    """Discover the canonical official manufacturer page when admin did not supply one.

    Stage 1 is intentionally broader than the normal evidence search because the
    trusted official domain is not known yet. The discovered page is accepted only
    after:
    - exact product identity passes deterministic checks,
    - the discovered host is different from the retailer,
    - the host plausibly belongs to the expected brand (or matches an already
      configured brand/profile domain),
    - the provider's consulted sources include that same host.

    Once accepted, subsequent evidence/media searches are restricted to the newly
    trusted manufacturer domain.
    """
    expected_brand = expected_brand_name(item, profile=profile)
    if not expected_brand:
        normalized = getattr(item, "normalized_payload", None) or {}
        expected_brand = str(
            normalized.get("brand")
            or normalized.get("manufacturer")
            or ""
        ).strip()

    if not expected_brand:
        return {
            "status": "brand_required",
            "verified": False,
            "reason": "A brand is required before Arolana can safely discover an official manufacturer domain.",
        }

    input_hint = _retailer_identity_hint(item)
    retailer_host = _source_host(item)

    prompt = f"""
You are Arolana's official manufacturer-page discovery service.

Find the exact OFFICIAL MANUFACTURER product page for this product.
Do not return retailers, marketplaces, distributors, review sites, social media,
price-comparison sites, or dealer pages.

Original retailer/input:
{input_hint}

Expected brand:
{expected_brand}

Requirements:
1. The page must belong to the manufacturer/brand itself.
2. Confirm the exact model/SKU when possible.
3. Never return price, availability, or seller claims.
4. If the exact official page cannot be established, set exact_identity_confirmed=false.
5. Return JSON only.

JSON schema:
{{
  "exact_identity_confirmed": true_or_false,
  "official_product_url": "",
  "official_domain": "",
  "name": "",
  "brand": "",
  "manufacturer": "",
  "model": "",
  "manufacturer_sku": "",
  "gtin": "",
  "ean": "",
  "upc": "",
  "evidence_urls": []
}}
""".strip()

    try:
        raw_response = _provider_request(prompt, allowed_domains=None)
        provider_payload = _parse_json_object(_response_output_text(raw_response))
        consulted = _response_sources(raw_response)
    except (WebEvidenceUnavailable, WebEvidenceRejected) as exc:
        return {
            "status": "provider_failed",
            "verified": False,
            "error": str(exc),
        }

    candidate_url = str(provider_payload.get("official_product_url") or "").strip()
    candidate_host = _host(candidate_url)
    declared_domain = _normalize_domain(
        provider_payload.get("official_domain") or candidate_host
    )

    clean_payload = {
        "exact_identity_confirmed": bool(provider_payload.get("exact_identity_confirmed")),
        "official_product_url": candidate_url,
        "name": str(provider_payload.get("name") or "").strip(),
        "brand": str(provider_payload.get("brand") or expected_brand).strip(),
        "manufacturer": str(provider_payload.get("manufacturer") or "").strip(),
        "model": str(provider_payload.get("model") or "").strip(),
        "manufacturer_sku": str(provider_payload.get("manufacturer_sku") or "").strip(),
        "gtin": str(provider_payload.get("gtin") or "").strip(),
        "ean": str(provider_payload.get("ean") or "").strip(),
        "upc": str(provider_payload.get("upc") or "").strip(),
    }

    identity = deterministic_identity_check(
        input_hint,
        clean_payload,
        expected_brand=expected_brand,
    )

    configured_domains = trusted_manufacturer_domains(item, profile=profile)
    configured_match = any(
        _url_allowed(candidate_url, [domain])
        for domain in configured_domains
    )
    brand_host_match = _host_looks_like_brand(candidate_host, expected_brand)
    consulted_same_host = any(
        _host(url) == candidate_host
        or _host(url).endswith("." + candidate_host)
        or candidate_host.endswith("." + _host(url))
        for url in consulted
        if _host(url)
    )

    retailer_conflict = bool(
        retailer_host
        and candidate_host
        and (
            candidate_host == retailer_host
            or candidate_host.endswith("." + retailer_host)
            or retailer_host.endswith("." + candidate_host)
        )
    )

    if _looks_like_retailer_host(candidate_host):
        retailer_conflict = True

    verified = bool(
        identity.get("passed")
        and candidate_url
        and candidate_host
        and not retailer_conflict
        and consulted_same_host
        and (configured_match or brand_host_match)
    )

    return {
        "status": "verified" if verified else "needs_confirmation",
        "verified": verified,
        "provider": "openai_web_search",
        "expected_brand": expected_brand,
        "official_product_url": candidate_url if verified else "",
        "official_domain": declared_domain if verified else "",
        "identity": identity,
        "brand_host_match": brand_host_match,
        "configured_domain_match": configured_match,
        "consulted_same_host": consulted_same_host,
        "retailer_conflict": retailer_conflict,
        "consulted_sources": consulted[:20],
        "payload": clean_payload,
    }



def discover_official_media_mirrors(item, *, profile=None) -> Dict:
    """Discover exact-product official regional/mirror pages outside the current allowlist."""
    normalized = getattr(item, "normalized_payload", None) or {}
    expected_brand = (
        str(normalized.get("brand") or normalized.get("manufacturer") or "").strip()
        or expected_brand_name(item, profile=profile)
    )
    model = str(
        normalized.get("model")
        or normalized.get("manufacturer_sku")
        or ""
    ).strip()
    name = str(normalized.get("name") or "").strip()
    input_hint = str(getattr(item, "input_value", "") or "").strip()
    retailer_host = _source_host(item)

    if not expected_brand:
        return {"status": "brand_required", "verified": False, "pages": []}

    already_known_domains = trusted_manufacturer_domains(item, profile=profile)

    prompt = f"""
You are Arolana's OFFICIAL manufacturer regional-media discovery service.

Find manufacturer-owned regional/country/store/press pages for the EXACT product.
The purpose is to locate legitimate official pages that may expose product media
when the canonical manufacturer host blocks Arolana's normal HTTP fetcher.

Product:
- Brand: {expected_brand}
- Name: {name or "(unknown)"}
- Exact model/SKU: {model or "(unknown)"}
- Original retailer/input: {input_hint}

Already-known canonical manufacturer domains:
{", ".join(already_known_domains) or "(none)"}

Prioritize HOST DIVERSITY. Prefer additional manufacturer-owned country/regional
hosts different from the canonical domains above when exact-model pages exist.

Allowed:
- official manufacturer country/regional product pages
- official brand-owned online store product pages
- official manufacturer press-centre / corporate launch pages
- official manufacturer product/gallery/media pages
- official manufacturer support pages

Forbidden:
- third-party retailers, dealers, distributors, marketplaces
- review/blog/social sites
- price-comparison sites
- sibling/predecessor products

Return up to 12 strong exact-model pages, preferably across several official
manufacturer-owned hosts. Return JSON ONLY:
{{
  "exact_identity_confirmed": true_or_false,
  "brand": "{expected_brand}",
  "model": "{model}",
  "pages": [
    {{
      "url": "",
      "kind": "product|store|gallery|corporate_news|press|support|other",
      "exact_model_confirmed": true_or_false
    }}
  ]
}}
""".strip()

    try:
        raw_response = _provider_request(prompt, allowed_domains=None)
        payload = _parse_json_object(_response_output_text(raw_response))
        consulted = _response_sources(raw_response)
    except (WebEvidenceUnavailable, WebEvidenceRejected) as exc:
        return {
            "status": "provider_failed",
            "verified": False,
            "pages": [],
            "error": str(exc),
        }

    identity_payload = {
        "exact_identity_confirmed": bool(payload.get("exact_identity_confirmed")),
        "name": name,
        "brand": str(payload.get("brand") or expected_brand).strip(),
        "manufacturer": str(payload.get("brand") or expected_brand).strip(),
        "model": str(payload.get("model") or model).strip(),
        "manufacturer_sku": str(payload.get("model") or model).strip(),
    }
    identity = deterministic_identity_check(
        input_hint,
        identity_payload,
        expected_brand=expected_brand,
    )

    pages = []
    if identity.get("passed"):
        for row in payload.get("pages") or []:
            if not isinstance(row, dict) or not bool(row.get("exact_model_confirmed")):
                continue

            url = str(row.get("url") or "").strip()
            host = _host(url)
            if not url or not host:
                continue
            if _looks_like_retailer_host(host):
                continue
            if retailer_host and (
                host == retailer_host
                or host.endswith("." + retailer_host)
                or retailer_host.endswith("." + host)
            ):
                continue
            if not _host_looks_like_brand(host, expected_brand):
                continue

            consulted_same_host = any(
                _host(source_url) == host
                or _host(source_url).endswith("." + host)
                or host.endswith("." + _host(source_url))
                for source_url in consulted
                if _host(source_url)
            )
            if not consulted_same_host:
                continue

            entry = {
                "url": url,
                "host": host,
                "kind": str(row.get("kind") or "other").strip().lower()[:40],
                "exact_model_confirmed": True,
                "brand_host_match": True,
                "consulted_same_host": True,
            }
            if entry not in pages:
                pages.append(entry)
            if len(pages) >= 12:
                break

    return {
        "status": "verified" if pages else "no_verified_mirrors",
        "verified": bool(pages),
        "provider": "openai_web_search",
        "expected_brand": expected_brand,
        "identity": identity,
        "pages": pages,
        "consulted_sources": consulted[:30],
    }



def discover_official_media_sources(item, *, profile=None) -> Dict:
    """Find official manufacturer pages/assets that may contain exact product media.

    This stage is restricted to already trusted manufacturer domains. It does not
    accept retailer images and does not treat search descriptions as image pixels.
    """
    allowed_domains = trusted_manufacturer_domains(item, profile=profile)
    if not allowed_domains:
        return {
            "status": "no_trusted_domain",
            "verified": False,
            "media_pages": [],
            "direct_image_urls": [],
        }

    normalized = getattr(item, "normalized_payload", None) or {}
    expected_brand = (
        str(normalized.get("brand") or normalized.get("manufacturer") or "").strip()
        or expected_brand_name(item, profile=profile)
    )
    model = str(
        normalized.get("model")
        or normalized.get("manufacturer_sku")
        or ""
    ).strip()
    name = str(normalized.get("name") or "").strip()
    input_hint = str(getattr(item, "input_value", "") or "").strip()

    prompt = f"""
You are Arolana's OFFICIAL manufacturer-media discovery service.

Search ONLY the allowed manufacturer domains.
Find official pages for the EXACT product below that are useful for obtaining
real manufacturer-owned product photography or technical product imagery.

Product:
- Brand: {expected_brand or "(unknown)"}
- Name: {name or "(unknown)"}
- Exact model/SKU: {model or "(unknown)"}
- Original input: {input_hint}

Prioritize:
- canonical product page
- official product gallery/media page
- official press/product asset page
- official support/setup page containing exact product images
- official specification/brochure page

Do NOT return:
- retailer/dealer pages
- reviews/blogs/social media
- unrelated family/sibling products
- price pages
- stock-photo sites

If you can see a DIRECT image asset URL on the allowed manufacturer domain,
you may return it. Never invent an image URL.

Return JSON only:
{{
  "exact_identity_confirmed": true_or_false,
  "official_product_url": "",
  "media_pages": [
    {{
      "url": "",
      "kind": "product|gallery|support|press|brochure|setup|other",
      "role_hints": ["main","front","ports","package","lifestyle","detail"],
      "exact_model_confirmed": true_or_false
    }}
  ],
  "direct_image_urls": [
    {{
      "url": "",
      "source_page_url": "",
      "role_hint": "main|front|ports|package|lifestyle|detail|unknown",
      "alt_text": ""
    }}
  ]
}}
""".strip()

    try:
        raw_response = _provider_request(prompt, allowed_domains=allowed_domains)
        payload = _parse_json_object(_response_output_text(raw_response))
        consulted = _response_sources(raw_response)
    except (WebEvidenceUnavailable, WebEvidenceRejected) as exc:
        return {
            "status": "provider_failed",
            "verified": False,
            "allowed_domains": allowed_domains,
            "media_pages": [],
            "direct_image_urls": [],
            "error": str(exc),
        }

    official_product_url = str(payload.get("official_product_url") or "").strip()
    if official_product_url and not _url_allowed(official_product_url, allowed_domains):
        official_product_url = ""

    media_pages = []
    for row in payload.get("media_pages") or []:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or "").strip()
        if not url or not _url_allowed(url, allowed_domains):
            continue
        if not bool(row.get("exact_model_confirmed")):
            continue
        entry = {
            "url": url,
            "kind": str(row.get("kind") or "other").strip().lower()[:30],
            "role_hints": [
                str(value).strip().lower()
                for value in (row.get("role_hints") or [])
                if str(value).strip()
            ][:10],
            "exact_model_confirmed": True,
        }
        if entry not in media_pages:
            media_pages.append(entry)
        if len(media_pages) >= 12:
            break

    direct_images = []
    for row in payload.get("direct_image_urls") or []:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or "").strip()
        source_page_url = str(row.get("source_page_url") or "").strip()
        # Phase 5.3 automatically accepts only assets that remain on an already
        # trusted manufacturer domain. Delegated CDNs continue to require the
        # existing provenance crawler / human review path.
        if not url or not _url_allowed(url, allowed_domains):
            continue
        if source_page_url and not _url_allowed(source_page_url, allowed_domains):
            continue
        entry = {
            "url": url,
            "source_page_url": source_page_url,
            "role_hint": str(row.get("role_hint") or "unknown").strip().lower()[:40],
            "alt_text": str(row.get("alt_text") or "").strip()[:500],
        }
        if entry not in direct_images:
            direct_images.append(entry)
        if len(direct_images) >= 20:
            break

    exact_confirmed = bool(payload.get("exact_identity_confirmed"))
    return {
        "status": "verified" if exact_confirmed else "needs_confirmation",
        "verified": exact_confirmed,
        "provider": "openai_web_search",
        "allowed_domains": allowed_domains,
        "official_product_url": official_product_url,
        "media_pages": media_pages,
        "direct_image_urls": direct_images,
        "consulted_sources": [
            url for url in consulted if _url_allowed(url, allowed_domains)
        ][:30],
    }


def retrieve_manufacturer_web_evidence(item, *, profile=None) -> Dict:
    """Return a verified manufacturer draft or an auditable failure report."""
    enabled = str(_setting("CATALOG_IMPORT_WEB_EVIDENCE_ENABLED", "1") or "1").lower()
    if enabled in {"0", "false", "no", "off"}:
        return {"status": "disabled", "verified": False}

    allowed_domains = trusted_manufacturer_domains(item, profile=profile)
    if not allowed_domains:
        return {
            "status": "no_trusted_domain",
            "verified": False,
            "reason": (
                "No trusted manufacturer domain is configured. Add a manufacturer URL, "
                "a brand website, or a BrandVerificationProfile first."
            ),
        }

    expected_brand = expected_brand_name(item, profile=profile)
    input_hint = _retailer_identity_hint(item)
    supplied_url = str(getattr(item, "manufacturer_url", "") or "").strip()

    prompt = f"""
You are Arolana's manufacturer-evidence verifier.

Search ONLY the allowed official manufacturer domains supplied by the tool.
The retailer page may be inaccessible. Do NOT use retailer facts or retailer pricing.

Original product input:
{input_hint}

Admin-supplied manufacturer URL (may be blocked to direct HTTP):
{supplied_url or "(none)"}

Expected brand:
{expected_brand or "(unknown)"}

Your task:
1. Find the exact official manufacturer product corresponding to the original input.
2. Confirm exact identity only when an official source explicitly identifies the exact model/SKU.
3. Extract only factual manufacturer-supported identity/specification data.
4. Also extract physical facts only when explicitly supported: net product weight,
   product dimensions, package/shipping weight, package dimensions, country of
   origin, certifications, and manufacturer warranty.
5. NEVER invent delivery days, free shipping, retailer availability, seller shipping
   promises, price, MSRP, seller text, or commercial markup.
6. For shipping.weight_shipping, return the numeric value and its original unit.
   For shipping.dimensions_package, preserve the manufacturer-stated L×W×H text.
7. If exact identity is uncertain, set exact_identity_confirmed=false.
8. Return JSON ONLY, no markdown.

JSON schema:
{{
  "exact_identity_confirmed": true_or_false,
  "official_product_url": "official URL or empty",
  "name": "",
  "brand": "",
  "manufacturer": "",
  "model": "",
  "manufacturer_sku": "",
  "gtin": "",
  "ean": "",
  "upc": "",
  "category": "",
  "subcategory": "",
  "short_description": "",
  "description": "",
  "specifications": {{}},
  "key_features": [],
  "package_contents": [],
  "country_of_origin": "",
  "manufacturer_address": "",
  "certifications": [],
  "weight": null,
  "weight_unit": "g|kg|lb|oz or empty",
  "dimensions_length": null,
  "dimensions_width": null,
  "dimensions_height": null,
  "dimension_unit": "mm|cm|m|in or empty",
  "warranty": {{
    "provider": "",
    "duration_years": 0,
    "duration_months": 0,
    "coverage_details": "",
    "exclusions": "",
    "registration_required": false,
    "registration_url": "",
    "terms_url": "",
    "customer_support_phone": "",
    "customer_support_email": ""
  }},
  "shipping": {{
    "weight_shipping": null,
    "weight_shipping_unit": "g|kg|lb|oz or empty",
    "dimensions_package": "",
    "shipping_restrictions": "",
    "hazmat": false
  }},
  "manuals": [],
  "evidence_urls": []
}}
""".strip()

    try:
        raw_response = _provider_request(prompt, allowed_domains)
        text = _response_output_text(raw_response)
        provider_payload = _parse_json_object(text)
        consulted = _response_sources(raw_response)
        payload = _sanitize_payload(provider_payload, allowed_domains, consulted)
    except (WebEvidenceUnavailable, WebEvidenceRejected) as exc:
        return {
            "status": "provider_failed",
            "verified": False,
            "allowed_domains": allowed_domains,
            "error": str(exc),
        }

    identity = deterministic_identity_check(
        input_hint,
        payload,
        expected_brand=expected_brand,
    )

    if not payload.get("evidence_urls"):
        identity["passed"] = False

    if not identity["passed"]:
        return {
            "status": "needs_confirmation",
            "verified": False,
            "allowed_domains": allowed_domains,
            "identity": identity,
            "payload": payload,
            "reason": "Web-grounded manufacturer evidence did not pass deterministic exact-identity checks.",
        }

    draft_data = {
        key: payload.get(key)
        for key in (
            "name", "brand", "manufacturer", "model", "manufacturer_sku",
            "gtin", "ean", "upc", "category", "subcategory",
            "short_description", "description", "specifications",
            "key_features", "package_contents",
            "country_of_origin", "manufacturer_address", "certifications",
            "weight", "weight_unit",
            "dimensions_length", "dimensions_width", "dimensions_height", "dimension_unit",
            "warranty", "shipping",
            "manuals",
        )
    }
    draft_data["source_url"] = payload.get("official_product_url") or (
        payload.get("evidence_urls") or [supplied_url]
    )[0]
    draft_data["source_name"] = expected_brand or payload.get("brand") or payload.get("manufacturer")
    draft_data["source_price"] = None
    draft_data["source_currency"] = ""

    draft = UniversalProductDraft.from_dict(draft_data)

    return {
        "status": "verified",
        "verified": True,
        "provider": "openai_web_search",
        "allowed_domains": allowed_domains,
        "identity": identity,
        "payload": payload,
        "draft": draft,
        "evidence_urls": payload.get("evidence_urls") or [],
        "official_product_url": payload.get("official_product_url") or draft.source_url,
    }
