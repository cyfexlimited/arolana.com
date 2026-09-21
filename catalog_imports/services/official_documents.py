"""Official manufacturer document discovery and specification extraction.

This module is deliberately source-neutral. It never hard-codes a retailer or
manufacturer hostname. Trust comes from the BrandVerificationProfile official
manufacturer domain plus product-identity checks.
"""

from __future__ import annotations

import io
import re
from html import unescape
from html.parser import HTMLParser
from typing import Dict, List
from urllib.parse import urljoin, urlparse

from catalog_imports.services.evidence import official_domain_matches
from catalog_imports.services.http_fetch import FetchBlocked, fetch_binary, fetch_html


_DOCUMENT_HINTS = (
    "datasheet",
    "data sheet",
    "spec sheet",
    "specification sheet",
    "product specifications",
    "technical specifications",
    "technical specification",
    "technical specs",
    "tech specs",
    "technical data",
)

# These are generic document labels, not manufacturer-specific selectors.
_SKIP_LABELS = {
    "http", "https", "www", "copyright", "trademark", "contact", "email",
    "website", "address", "phone", "tel", "fax", "page",
}

_TOKEN_RE = re.compile(r"[a-z0-9]+", re.I)
_COLON_PAIR_RE = re.compile(r"^([^:]{2,120}):\s*(.{1,700})$")
_COMMON_VALUE_RE = re.compile(
    r"^(height|width|depth|length|weight|resolution|zoom|frequency response|"
    r"pickup range|operating temperature|storage temperature|humidity|"
    r"operating voltage|rated power|impedance|sensitivity|field of view|"
    r"horizontal field of view|vertical field of view|diagonal field of view)\s+(.{1,300})$",
    re.I,
)


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(str(value or ""))).strip()


class _LinkParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self._href = ""
        self._text = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a":
            return
        attrs = dict(attrs)
        self._href = str(attrs.get("href") or "").strip()
        self._text = []

    def handle_data(self, data):
        if self._href:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._href:
            self.links.append((self._href, _clean_text(" ".join(self._text))))
            self._href = ""
            self._text = []


def discover_official_documents(html: str, base_url: str, official_domain: str, limit: int = 5) -> List[str]:
    """Return likely spec/datasheet links on the configured official domain.

    The function does not trust arbitrary external links found on the page.
    """
    parser = _LinkParser()
    try:
        parser.feed(html or "")
    except Exception:
        return []

    scored = []
    seen = set()
    for href, text in parser.links:
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        url = urljoin(base_url, href)
        if url in seen or not official_domain_matches(url, official_domain):
            continue
        haystack = f"{text} {href}".lower().replace("_", "-")

        # A PDF extension by itself is not enough evidence that a document is a
        # specification source. Many manufacturer pages link to manuals, safety
        # sheets, warranty PDFs, brochures, and support documents. Require at
        # least one explicit specification/datasheet hint before considering the
        # document. This keeps the fallback conservative and prevents a generic
        # manual from being treated as authoritative product-spec evidence.
        matched_hints = [hint for hint in _DOCUMENT_HINTS if hint in haystack]
        if not matched_hints:
            continue

        score = 5 * len(matched_hints)
        if urlparse(url).path.lower().endswith(".pdf"):
            score += 2
        if "manual" in haystack or "support" in haystack:
            score -= 1
        if score <= 0:
            continue
        seen.add(url)
        scored.append((score, url))

    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    return [url for _score, url in scored[: max(1, int(limit or 5))]]


def pdf_text_from_bytes(data: bytes, max_pages: int = 30) -> str:
    if not data:
        return ""
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise FetchBlocked(
            "Official PDF specification extraction requires the pypdf dependency."
        ) from exc

    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as exc:
        raise FetchBlocked(f"Could not parse official manufacturer PDF: {exc}") from exc

    parts = []
    for page in list(reader.pages)[: max(1, int(max_pages or 30))]:
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        if text:
            parts.append(text)
    return "\n".join(parts)


def extract_specifications_from_text(text: str, max_specs: int = 120) -> Dict[str, str]:
    """Conservatively turn document text into label/value specifications.

    A document must yield several concrete label/value rows before it is used as
    authoritative specification evidence. This avoids treating marketing copy as
    a technical specification table.
    """
    lines = []
    for raw in str(text or "").replace("\x00", " ").splitlines():
        line = _clean_text(raw).strip("•·▪–—- \t")
        if line:
            lines.append(line)

    specs: Dict[str, str] = {}
    for line in lines:
        if len(specs) >= max_specs:
            break
        match = _COLON_PAIR_RE.match(line)
        if match:
            name = _clean_text(match.group(1)).strip(" .")
            value = _clean_text(match.group(2)).strip(" .")
        else:
            common = _COMMON_VALUE_RE.match(line)
            if not common:
                continue
            name = _clean_text(common.group(1)).strip(" .")
            value = _clean_text(common.group(2)).strip(" .")

        if not (2 <= len(name) <= 120 and 1 <= len(value) <= 700):
            continue
        lname = name.lower()
        if lname in _SKIP_LABELS or any(lname.startswith(prefix) for prefix in ("http", "www.")):
            continue
        if value.lower().startswith(("http://", "https://", "www.")):
            continue
        # Avoid obvious prose headings accidentally split by punctuation.
        if len(name.split()) > 14:
            continue
        specs.setdefault(name, value)

    return specs


def _identity_tokens(*values: str) -> List[str]:
    stop = {
        "the", "and", "for", "with", "camera", "conference", "conferencing",
        "video", "product", "system", "wireless", "official",
    }
    result = []
    for value in values:
        for token in _TOKEN_RE.findall(str(value or "").lower()):
            if token in stop or (len(token) < 2 and not token.isdigit()):
                continue
            if token not in result:
                result.append(token)
    return result


def document_identity_matches(text: str, *, name: str = "", model: str = "", sku: str = "") -> Dict:
    """Require the official document itself to identify the same product."""
    normalized = re.sub(r"[^a-z0-9]+", "", str(text or "").lower())
    exact_identifiers = []
    for value in (sku, model):
        cleaned = re.sub(r"[^a-z0-9]+", "", str(value or "").lower())
        if len(cleaned) >= 4:
            exact_identifiers.append(cleaned)
    exact_match = any(value in normalized for value in exact_identifiers)

    tokens = _identity_tokens(name, model)
    text_tokens = set(_TOKEN_RE.findall(str(text or "").lower()))
    overlap = [token for token in tokens if token in text_tokens]
    coverage = (len(overlap) / len(tokens)) if tokens else 0.0

    # A SKU/model exact match is strongest. For products without an extracted
    # identifier, require at least two meaningful product-name tokens and strong
    # coverage so a generic corporate PDF cannot verify a product by accident.
    fallback = len(overlap) >= 2 and coverage >= 0.60
    return {
        "passed": bool(exact_match or fallback),
        "exact_identifier_match": bool(exact_match),
        "token_overlap": overlap,
        "token_coverage": round(coverage, 4),
    }


def extract_official_document(url: str, *, official_domain: str, timeout: int, user_agent: str) -> Dict:
    """Fetch one same-domain official document and return extracted specs/text."""
    if not official_domain_matches(url, official_domain):
        raise FetchBlocked("Official document URL is outside the configured manufacturer domain.")

    path = urlparse(url).path.lower()
    if path.endswith(".pdf"):
        fetched = fetch_binary(
            url,
            timeout=timeout,
            user_agent=user_agent,
            allowed_content_types={"application/pdf", "application/octet-stream"},
            max_bytes=15 * 1024 * 1024,
        )
        if not official_domain_matches(fetched.url, official_domain):
            raise FetchBlocked("Official document redirected outside the configured manufacturer domain.")
        text = pdf_text_from_bytes(fetched.data)
        return {
            "url": fetched.url,
            "status": fetched.status,
            "content_type": fetched.content_type,
            "text": text,
            "specifications": extract_specifications_from_text(text),
        }

    fetched = fetch_html(url, timeout=timeout, user_agent=user_agent)
    if not official_domain_matches(fetched.url, official_domain):
        raise FetchBlocked("Official document redirected outside the configured manufacturer domain.")
    # For HTML companion pages, strip tags approximately before the generic
    # document-text parser. The main product page is still handled by the normal
    # product extractor; this path is only a fallback for explicit spec docs.
    text = re.sub(r"<[^>]+>", "\n", fetched.text or "")
    return {
        "url": fetched.url,
        "status": fetched.status,
        "content_type": fetched.content_type,
        "text": unescape(text),
        "specifications": extract_specifications_from_text(unescape(text)),
    }


def enrich_manufacturer_from_official_documents(
    draft,
    *,
    manufacturer_html: str,
    manufacturer_url: str,
    official_domain: str,
    timeout: int,
    user_agent: str,
    max_documents: int = 5,
) -> Dict:
    """Try linked official spec documents when the product page lacks specs.

    Returns an auditable report. The caller decides how evidence rows are stored.
    """
    report = {"status": "not_needed", "attempted": [], "verified_document": None}
    if getattr(draft, "specifications", None) or getattr(draft, "specifications_html", None):
        return report
    if not official_domain:
        report["status"] = "official_domain_not_configured"
        return report

    urls = discover_official_documents(
        manufacturer_html,
        manufacturer_url,
        official_domain,
        limit=max_documents,
    )
    if not urls:
        report["status"] = "no_official_spec_document_found"
        return report

    report["status"] = "attempted"
    for url in urls:
        attempt = {"url": url}
        try:
            extracted = extract_official_document(
                url,
                official_domain=official_domain,
                timeout=timeout,
                user_agent=user_agent,
            )
            identity = document_identity_matches(
                extracted.get("text", ""),
                name=getattr(draft, "name", ""),
                model=getattr(draft, "model", ""),
                sku=getattr(draft, "manufacturer_sku", ""),
            )
            specs = dict(extracted.get("specifications") or {})
            attempt.update({
                "status": "fetched",
                "http_status": extracted.get("status"),
                "content_type": extracted.get("content_type"),
                "identity": identity,
                "specification_count": len(specs),
            })
            report["attempted"].append(attempt)

            # Require multiple concrete specs plus identity confirmation before
            # the official document is allowed to flip specification_verified.
            if identity["passed"] and len(specs) >= 3:
                merged = dict(getattr(draft, "specifications", {}) or {})
                for key, value in specs.items():
                    merged.setdefault(key, value)
                draft.specifications = merged
                evidence = dict(getattr(draft, "evidence", {}) or {})
                evidence["official_spec_document"] = {
                    "url": extracted["url"],
                    "content_type": extracted["content_type"],
                    "specification_count": len(specs),
                    "identity": identity,
                }
                draft.evidence = evidence
                report["status"] = "verified"
                report["verified_document"] = {
                    "url": extracted["url"],
                    "status": extracted["status"],
                    "content_type": extracted["content_type"],
                    "specifications": specs,
                    "identity": identity,
                }
                return report
        except Exception as exc:
            attempt.update({"status": "blocked", "error": str(exc)})
            report["attempted"].append(attempt)

    report["status"] = "no_verified_spec_document"
    return report
