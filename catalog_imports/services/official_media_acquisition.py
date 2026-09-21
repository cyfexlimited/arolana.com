"""Universal official-manufacturer media acquisition router.

This module never bypasses anti-bot protections. It combines:
1. direct official page extraction when permitted,
2. exact-product manufacturer page discovery through trusted web evidence,
3. same-trusted-domain direct image candidates returned by the web evidence
   provider,
4. Arolana's existing exact-product reference hygiene / semantic role gates.

All acquired images remain manufacturer evidence/reference media. They are not
attached to Product automatically and still require the existing human review
workflow before Product use.
"""

from __future__ import annotations

import io
import re
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from catalog_imports.extractors.registry import get_extractor
from catalog_imports.models import (
    BrandVerificationProfile,
    ImportEvidence,
    ImportMediaCandidate,
)
from catalog_imports.schema import UniversalProductDraft
from catalog_imports.services.evidence import (
    compare_identity,
    official_domain_matches,
)
from catalog_imports.services.http_fetch import (
    FetchBlocked,
    UnsafeURL,
    fetch_binary,
    fetch_html,
)
from catalog_imports.services.media_references import (
    _looks_like_image_url,
    _product_relevant_url,
    extract_official_image_urls,
    manufacturer_reference_urls,
    reference_support_report,
)
from catalog_imports.services.official_reference_semantics import (
    classify_authoritative_evidence_images,
)
from catalog_imports.services.official_reference_visual_classifier import (
    classify_authoritative_evidence_images_visual,
)
from catalog_imports.services.web_evidence import (
    discover_manufacturer_web_identity,
    discover_official_media_mirrors,
    discover_official_media_sources,
    trusted_manufacturer_domains,
)


def _brand_name(item):
    payload = item.normalized_payload or {}
    return str(
        payload.get("brand")
        or payload.get("manufacturer")
        or getattr(getattr(item.batch, "default_brand", None), "name", "")
        or ""
    ).strip()


def _profile_for(item):
    brand = _brand_name(item)
    if not brand:
        return None
    return (
        BrandVerificationProfile.objects
        .filter(is_active=True, brand_name__iexact=brand)
        .first()
    )


def _compact(value):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _normalized_model(item):
    payload = item.normalized_payload or {}
    return str(
        payload.get("model")
        or payload.get("manufacturer_sku")
        or ""
    ).strip()


def _page_exact_identity(item, draft, page_url, expected_brand):
    """Conservative exact-product page check for an official media page."""
    base = UniversalProductDraft.from_dict(item.normalized_payload or {})
    result = compare_identity(
        base,
        draft,
        input_hint=item.input_value,
        expected_brand=expected_brand,
        official_domain_ok=True,
    )
    if result.get("passed"):
        return result

    expected_model = _compact(_normalized_model(item))
    page_model = _compact(
        getattr(draft, "model", "")
        or getattr(draft, "manufacturer_sku", "")
    )
    page_name = _compact(getattr(draft, "name", ""))
    page_url_compact = _compact(page_url)

    if expected_model and (
        expected_model == page_model
        or expected_model in page_name
        or expected_model in page_url_compact
    ):
        return {
            **result,
            "passed": True,
            "fallback": "exact_model_in_official_page_url_or_identity",
        }
    return result


def _store_manufacturer_media_evidence(
    item,
    *,
    url,
    source_name,
    payload,
    http_status=None,
    notes="",
):
    existing = (
        item.evidence_records
        .filter(
            role=ImportEvidence.ROLE_MANUFACTURER,
            url=url,
            is_authoritative=True,
        )
        .order_by("id")
        .first()
    )
    if existing:
        existing.status = ImportEvidence.STATUS_FETCHED
        existing.source_name = source_name or existing.source_name
        existing.extracted_payload = payload or {}
        existing.http_status = http_status
        existing.error_message = ""
        existing.notes = notes
        existing.save()
        return existing

    return ImportEvidence.objects.create(
        item=item,
        role=ImportEvidence.ROLE_MANUFACTURER,
        url=url,
        source_name=source_name,
        is_authoritative=True,
        status=ImportEvidence.STATUS_FETCHED,
        http_status=http_status,
        extracted_payload=payload or {},
        error_message="",
        notes=notes,
    )


def _probe_same_domain_direct_image(item, row, trusted_domains):
    url = str((row or {}).get("url") or "").strip()
    if not url:
        return None

    # URL must remain within the already trusted manufacturer domains.
    host = (urlparse(url).hostname or "").lower()
    if not any(
        host == domain or host.endswith("." + domain)
        for domain in trusted_domains
        if domain
    ):
        return None

    if not _looks_like_image_url(url):
        return None
    if not _product_relevant_url(item, url):
        return None

    try:
        fetched = fetch_binary(
            url,
            timeout=15,
            max_bytes=20 * 1024 * 1024,
            user_agent="ArolanaProductImporter/5.3 (+https://arolana.com)",
            allowed_content_types={
                "image/jpeg",
                "image/png",
                "image/webp",
                "image/avif",
                "image/gif",
            },
            accept_header="image/avif,image/webp,image/png,image/jpeg,image/gif,*/*;q=0.1",
        )
    except Exception:
        return None

    content_type = str(getattr(fetched, "content_type", "") or "").lower()
    if not content_type.startswith("image/"):
        return None

    return {
        "reference_url": url,
        "url": url,
        "kind": "official_same_domain_search_asset",
        "role_hint": str((row or {}).get("role_hint") or "unknown"),
        "alt_text": str((row or {}).get("alt_text") or ""),
        "source_page_url": str((row or {}).get("source_page_url") or ""),
        "content_type": content_type,
    }



_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif")
_SKIP_CONTEXT_IMAGE_HINTS = (
    "logo", "favicon", "icon", "sprite", "tracking", "analytics",
    "country-flag", "social", "payment",
)

_CONTEXT_ROLE_PATTERNS = {
    "front": ("front view", "front-view", "front"),
    "left_angle": ("left angle", "left-angle", "left view", "left-view"),
    "right_angle": ("right angle", "right-angle", "right view", "right-view"),
    "side": ("side view", "side-view", "profile view", "profile"),
    "back": ("rear view", "rear-view", "back view", "back-view", "rear", "back"),
    "top_detail": ("top view", "top-view", "overhead", "top detail", "top-detail"),
    "ports_detail": (
        "ports", "port detail", "i/o", "io panel", "connector", "connectors",
        "input output", "input-output", "sdi", "hdmi", "usb", "ethernet",
        "terminal", "terminals", "media slots", "card slots",
    ),
    "package_contents": (
        "package", "packaging", "box contents", "in the box",
        "what's in the box", "included accessories",
    ),
    "lifestyle": (
        "in use", "shooting", "filming", "production", "installed",
        "installation", "studio", "event", "news", "broadcast", "operator",
    ),
    "closeup": ("close up", "close-up", "closeup", "detail view", "detail-view"),
}


def _clean_context(value):
    return re.sub(r"\s+", " ", unescape(str(value or ""))).strip()


class _ContextImageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.images = []
        self._recent = []
        self._heading = ""
        self._heading_tag = ""
        self._heading_parts = []

    def _remember(self, value):
        value = _clean_context(value)
        if value:
            self._recent.append(value)
            self._recent = self._recent[-10:]

    def handle_starttag(self, tag, attrs):
        tag = str(tag).lower()
        attrs = {str(k).lower(): str(v or "") for k, v in attrs}

        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._heading_tag = tag
            self._heading_parts = []

        if tag != "img":
            return

        context = " ".join(
            value for value in (
                self._heading,
                " ".join(self._recent[-6:]),
                attrs.get("alt"),
                attrs.get("title"),
                attrs.get("aria-label"),
                attrs.get("data-caption"),
                attrs.get("data-title"),
            ) if value
        )
        for key in (
            "src", "data-src", "data-lazy-src", "data-original",
            "data-image-src", "data-zoom-image",
        ):
            value = str(attrs.get(key) or "").strip()
            if value:
                self.images.append({"src": value, "context": _clean_context(context)})

    def handle_data(self, data):
        value = _clean_context(data)
        if not value:
            return
        self._remember(value)
        if self._heading_tag:
            self._heading_parts.append(value)

    def handle_endtag(self, tag):
        if self._heading_tag and str(tag).lower() == self._heading_tag:
            self._heading = _clean_context(" ".join(self._heading_parts))
            self._heading_tag = ""
            self._heading_parts = []


def _context_roles(context):
    normalized = _clean_context(context).lower().replace("_", " ")
    roles = set()
    for role, patterns in _CONTEXT_ROLE_PATTERNS.items():
        if any(pattern in normalized for pattern in patterns):
            roles.add(role)
    return roles


def _probe_context_image(url):
    try:
        fetched = fetch_binary(
            url,
            timeout=15,
            max_bytes=20 * 1024 * 1024,
            user_agent="ArolanaProductImporter/5.3.1 (+https://arolana.com)",
            allowed_content_types={
                "image/jpeg", "image/png", "image/webp", "image/avif",
                "image/gif", "application/octet-stream",
            },
            accept_header="image/avif,image/webp,image/png,image/jpeg,image/gif,*/*;q=0.1",
        )
    except Exception:
        return None

    content_type = str(getattr(fetched, "content_type", "") or "").lower()
    if content_type and not (
        content_type.startswith("image/")
        or content_type == "application/octet-stream"
    ):
        return None

    raw = bytes(getattr(fetched, "data", b"") or b"")
    if not raw:
        return None

    try:
        from PIL import Image
        image = Image.open(io.BytesIO(raw))
        width, height = image.size
    except Exception:
        return None

    if width < 320 or height < 220 or width * height < 160_000:
        return None
    ratio = max(width / max(height, 1), height / max(width, 1))
    if ratio > 5:
        return None

    return {
        "url": str(getattr(fetched, "url", "") or url).strip(),
        "content_type": content_type or "image/unknown",
        "width": int(width),
        "height": int(height),
    }


def _annotate_reference(url, *, roles, kind, source):
    from catalog_imports.services.deep_official_references import annotate_reference_url
    return annotate_reference_url(url, roles=roles, kind=kind, source=source)


def _extract_contextual_official_images(
    item,
    *,
    html,
    page_url,
    expected_model,
    max_probes=12,
):
    """Admit CDN pixels only because an exact-product official page embedded them."""
    parser = _ContextImageParser()
    try:
        parser.feed(str(html or ""))
    except Exception:
        return []

    model_compact = _compact(expected_model)
    result = []
    seen = set()
    probes = 0

    for row in parser.images:
        raw_src = str(row.get("src") or "").strip()
        if not raw_src:
            continue
        absolute = urljoin(page_url, raw_src)
        parsed = urlparse(absolute)
        if parsed.scheme.lower() not in {"http", "https"}:
            continue

        haystack = (absolute + " " + str(row.get("context") or "")).lower()
        if any(hint in haystack for hint in _SKIP_CONTEXT_IMAGE_HINTS):
            continue

        context = _clean_context(f"{row.get('context','')} {absolute}")
        roles = _context_roles(context)
        exact_model_in_context = bool(
            model_compact and model_compact in _compact(context)
        )

        if not roles and exact_model_in_context:
            roles = {"main"}

        if not roles:
            continue

        if probes >= max(1, min(int(max_probes or 12), 20)):
            break
        probes += 1

        probed = _probe_context_image(absolute)
        if not probed:
            continue

        verified_url = probed["url"]
        key = (verified_url, tuple(sorted(roles)))
        if key in seen:
            continue
        seen.add(key)

        annotated = _annotate_reference(
            verified_url,
            roles=roles,
            kind=(
                "scene" if "lifestyle" in roles
                else "package" if "package_contents" in roles
                else "physical"
            ),
            source="official-regional-page-embedded",
        )
        result.append({
            "reference_url": annotated,
            "url": annotated,
            "source_page_url": page_url,
            "kind": "official_embedded_delegated_cdn",
            "role_hint": ",".join(sorted(roles)),
            "semantic_context": context,
            "width": probed["width"],
            "height": probed["height"],
            "content_type": probed["content_type"],
        })

    return result


def _support_summary(report):
    supported = []
    for role, info in (report or {}).items():
        if isinstance(info, dict) and info.get("supported"):
            supported.append(role)
    return supported



_PAGE_KIND_SCORE = {
    "store": 130,
    "gallery": 125,
    "product": 120,
    "press": 110,
    "corporate_news": 105,
    "setup": 95,
    "support": 90,
    "brochure": 75,
    "pdf": 70,
    "evidence": 40,
    "other": 50,
    "regional": 100,
}


def _media_page_priority(row, *, canonical_hosts=None):
    """Higher scores are attempted first.

    Verified mirror pages and host diversity are intentionally rewarded so a
    long list of blocked canonical URLs cannot starve alternative official
    country/store/press pages.
    """
    canonical_hosts = {
        str(value or "").lower().strip()
        for value in (canonical_hosts or [])
        if str(value or "").strip()
    }
    url = str((row or {}).get("url") or "").strip()
    host = (urlparse(url).hostname or "").lower()
    kind = str((row or {}).get("kind") or "other").strip().lower()

    score = int(_PAGE_KIND_SCORE.get(kind, 50))

    if bool((row or {}).get("mirror_verified")):
        score += 80

    if host and not any(
        host == canonical
        or host.endswith("." + canonical)
        or canonical.endswith("." + host)
        for canonical in canonical_hosts
    ):
        score += 45

    # Brand-owned stores and press centres are often more fetchable than the
    # canonical product CMS while still being official manufacturer pages.
    compact_host = re.sub(r"[^a-z0-9]+", "", host)
    if "store" in compact_host:
        score += 30
    if "press" in compact_host or "news" in compact_host:
        score += 20

    # Product-model URLs are generally better media candidates than generic
    # support/evidence landing pages.
    if _compact((row or {}).get("expected_model")) in _compact(url):
        score += 15

    return score


def _select_media_page_queue(
    pages,
    *,
    canonical_hosts=None,
    expected_model="",
    max_pages=18,
    max_per_host=3,
):
    """Return a ranked host-diverse page queue.

    Phase 5.3.1 appended verified mirrors last and then fetched pages[:12].
    On the Sony PXW-Z200 diagnostic this meant sony.co.uk mirror pages were
    discovered but never attempted because pro.sony/sony.com consumed all 12
    slots. This selector prevents that starvation.
    """
    unique = []
    seen = set()
    for raw in pages or []:
        row = dict(raw or {})
        url = str(row.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        row["expected_model"] = expected_model
        unique.append(row)

    ranked = sorted(
        unique,
        key=lambda row: (
            -_media_page_priority(row, canonical_hosts=canonical_hosts),
            str(row.get("url") or ""),
        ),
    )

    selected = []
    host_counts = {}
    for row in ranked:
        host = (urlparse(str(row.get("url") or "")).hostname or "").lower()
        if not host:
            continue
        if host_counts.get(host, 0) >= max(1, int(max_per_host or 3)):
            continue
        selected.append(row)
        host_counts[host] = host_counts.get(host, 0) + 1
        if len(selected) >= max(1, int(max_pages or 18)):
            break

    return selected


def acquire_official_media(item, *, actor=None):
    """Discover/store exact official media references without publishing anything."""
    profile = _profile_for(item)
    discovery_report = {"status": "not_needed"}

    # If no manufacturer URL is known yet, discover it automatically.
    if not str(item.manufacturer_url or "").strip():
        discovery_report = discover_manufacturer_web_identity(
            item,
            profile=profile,
        )
        if discovery_report.get("verified"):
            item.manufacturer_url = str(
                discovery_report.get("official_product_url") or ""
            ).strip()
            item.save(update_fields=["manufacturer_url", "updated_at"])

    trusted_domains = trusted_manufacturer_domains(item, profile=profile)
    if not trusted_domains:
        return {
            "status": "held",
            "reason": "No trusted manufacturer domain is available for media acquisition.",
            "manufacturer_discovery": discovery_report,
            "trusted_domains": [],
            "media_pages": [],
            "page_results": [],
            "direct_image_results": [],
            "reference_urls": [],
            "supported_roles": [],
        }

    media_discovery = discover_official_media_sources(
        item,
        profile=profile,
    )
    mirror_discovery = discover_official_media_mirrors(
        item,
        profile=profile,
    )

    expected_brand = _brand_name(item)
    generic = get_extractor("generic")
    pages = []

    verified_mirror_hosts = {
        str(row.get("host") or "").lower()
        for row in (mirror_discovery.get("pages") or [])
        if str(row.get("host") or "").strip()
    }

    def add_page(url, kind="product", *, mirror_verified=False, source="unknown"):
        url = str(url or "").strip()
        if not url:
            return
        host = (urlparse(url).hostname or "").lower()
        trusted = any(
            host == domain or host.endswith("." + domain)
            for domain in trusted_domains
            if domain
        )
        if mirror_verified:
            trusted = trusted or host in verified_mirror_hosts
        if not trusted:
            return

        # URL-level dedupe. If a later discovery source proves stronger
        # provenance (mirror_verified), upgrade the existing row.
        existing = next(
            (row for row in pages if row.get("url") == url),
            None,
        )
        if existing is not None:
            if mirror_verified and not existing.get("mirror_verified"):
                existing["mirror_verified"] = True
                existing["kind"] = kind or existing.get("kind") or "other"
                existing["source"] = source or existing.get("source") or "unknown"
            return

        pages.append({
            "url": url,
            "kind": kind,
            "mirror_verified": bool(mirror_verified),
            "source": source,
        })

    # Strongest image-oriented sources first.
    for row in mirror_discovery.get("pages") or []:
        add_page(
            row.get("url"),
            row.get("kind") or "regional",
            mirror_verified=True,
            source="verified_mirror_discovery",
        )

    for row in media_discovery.get("media_pages") or []:
        add_page(
            row.get("url"),
            row.get("kind") or "other",
            source="restricted_media_discovery",
        )

    add_page(
        item.manufacturer_url,
        "product",
        source="manufacturer_url",
    )

    verification = item.verification_report or {}
    web_fallback = verification.get("manufacturer_web_fallback") or {}
    add_page(
        web_fallback.get("official_product_url"),
        "product",
        source="manufacturer_web_fallback",
    )

    # Generic evidence pages are useful, but must not crowd verified mirrors
    # out of the bounded fetch queue.
    for url in web_fallback.get("evidence_urls") or []:
        add_page(
            url,
            "evidence",
            source="manufacturer_web_evidence",
        )

    canonical_hosts = {
        str(domain or "").lower().strip()
        for domain in trusted_domains
        if str(domain or "").strip()
    }
    page_queue = _select_media_page_queue(
        pages,
        canonical_hosts=canonical_hosts,
        expected_model=_normalized_model(item),
        max_pages=18,
        max_per_host=3,
    )

    page_results = []
    for page in page_queue:
        url = page["url"]
        host = (urlparse(url).hostname or "").lower()
        try:
            fetched = fetch_html(
                url,
                timeout=15,
                max_bytes=6 * 1024 * 1024,
                user_agent="ArolanaProductImporter/5.3 (+https://arolana.com)",
            )
            draft = generic.extract(
                url=fetched.url,
                html=fetched.text,
                context={"default_currency": ""},
            )
            draft.source_url = fetched.url
            if not draft.brand:
                draft.brand = expected_brand
            identity = _page_exact_identity(
                item,
                draft,
                fetched.url,
                expected_brand,
            )

            if not identity.get("passed"):
                page_results.append({
                    "url": url,
                    "kind": page["kind"],
                    "status": "identity_not_confirmed",
                    "identity": identity,
                    "images_found": 0,
                    "source": page.get("source"),
                    "mirror_verified": bool(page.get("mirror_verified")),
                })
                continue

            images = extract_official_image_urls(
                fetched.text,
                page_url=fetched.url,
                official_domain=host,
                max_urls=120,
            )
            images = [
                image_url
                for image_url in images
                if _product_relevant_url(item, image_url)
            ][:40]

            contextual_images = _extract_contextual_official_images(
                item,
                html=fetched.text,
                page_url=fetched.url,
                expected_model=_normalized_model(item),
                max_probes=12,
            )

            payload = draft.to_dict()
            payload["images"] = [
                {
                    "reference_url": image_url,
                    "url": image_url,
                    "kind": "official_page_image",
                    "source_page_url": fetched.url,
                }
                for image_url in images
            ]
            payload["images"].extend(contextual_images[:30])

            _store_manufacturer_media_evidence(
                item,
                url=fetched.url,
                source_name=(expected_brand + " official media").strip(),
                payload=payload,
                http_status=fetched.status,
                notes=(
                    "Exact-product official manufacturer page acquired by Phase 5.3. "
                    "Images remain reference evidence and require normal media review."
                ),
            )
            page_results.append({
                "url": fetched.url,
                "kind": page["kind"],
                "status": "fetched",
                "identity": identity,
                "images_found": len(images) + len(contextual_images),
                "same_domain_images_found": len(images),
                "delegated_context_images_found": len(contextual_images),
                "mirror_verified": bool(page.get("mirror_verified")),
                "source": page.get("source"),
            })
        except (FetchBlocked, UnsafeURL) as exc:
            page_results.append({
                "url": url,
                "kind": page["kind"],
                "status": "blocked",
                "error": str(exc),
                "images_found": 0,
                "source": page.get("source"),
                "mirror_verified": bool(page.get("mirror_verified")),
            })
        except Exception as exc:
            page_results.append({
                "url": url,
                "kind": page["kind"],
                "status": "failed",
                "error": str(exc),
                "images_found": 0,
                "source": page.get("source"),
                "mirror_verified": bool(page.get("mirror_verified")),
            })

    # Web-search direct image URLs are accepted only when they remain on the
    # trusted manufacturer domain AND pass exact-product URL hygiene AND binary
    # content probing.
    direct_assets = []
    for row in media_discovery.get("direct_image_urls") or []:
        asset = _probe_same_domain_direct_image(
            item,
            row,
            trusted_domains,
        )
        if asset:
            direct_assets.append(asset)

    if direct_assets:
        media_page_url = (
            str(media_discovery.get("official_product_url") or "").strip()
            or str(item.manufacturer_url or "").strip()
        )
        if media_page_url:
            _store_manufacturer_media_evidence(
                item,
                url=media_page_url,
                source_name=(expected_brand + " official search media").strip(),
                payload={
                    **(item.normalized_payload or {}),
                    "images": direct_assets[:40],
                },
                notes=(
                    "Same-trusted-domain direct image assets discovered through "
                    "manufacturer-restricted web search, then binary-probed and "
                    "filtered for exact-product relevance. Review required."
                ),
            )

    semantic_classification = classify_authoritative_evidence_images(item)
    visual_classification = classify_authoritative_evidence_images_visual(item)

    refs = manufacturer_reference_urls(item)
    support = reference_support_report(item)

    report = {
        "status": "acquired" if refs else "no_exact_images_acquired",
        "manufacturer_discovery": discovery_report,
        "media_discovery": media_discovery,
        "mirror_discovery": mirror_discovery,
        "trusted_domains": trusted_domains,
        "media_pages": pages,
        "selected_page_queue": page_queue,
        "page_results": page_results,
        "direct_image_results": direct_assets,
        "semantic_classification": semantic_classification,
        "visual_classification": visual_classification,
        "reference_urls": refs[:50],
        "reference_count": len(refs),
        "supported_roles": _support_summary(support),
        "support": support,
        "safety": {
            "anti_bot_bypass": False,
            "retailer_images_used": False,
            "same_trusted_domain_direct_assets_only": True,
            "human_review_required": True,
        },
    }
    return report
