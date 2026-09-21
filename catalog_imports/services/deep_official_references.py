"""Deep acquisition of exact-product official manufacturer image references.

This service crawls only a small bounded set of pages/documents linked from an
already-verified manufacturer product page.  It does not search the open web and
does not bypass access controls.

Safety:
- support/document pages must remain on the configured official manufacturer domain;
- supplementary pages/documents must identify the exact same product;
- images may use an external CDN only when the image URL is embedded directly
  by that identity-verified official page and resolves to an actual image;
- only images with explicit view/scene/package semantics are returned;
- returned URLs keep the original official URL and store importer-only metadata
  in the fragment, which is never sent to the manufacturer server;
- PDFs are used conservatively: text is identity-checked and only explicit
  official image URLs present in the PDF text/annotations are considered.
"""

import re
from html import unescape
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

from django.core.cache import cache

from .evidence import official_domain_matches
from .http_fetch import FetchBlocked, UnsafeURL, fetch_binary, fetch_html
from .official_documents import document_identity_matches, pdf_text_from_bytes


_RESOURCE_HINTS = (
    "support", "manual", "user guide", "user-guide", "guide", "setup",
    "getting started", "getting-started", "quick start", "quick-start",
    "installation", "install", "mounting", "mount", "connections",
    "connectivity", "ports", "port", "input output", "input-output",
    "i/o", "resources", "downloads", "download", "product guide",
    "product-guide", "datasheet", "data sheet", "specification",
    "technical", "faq", "help",
)

_SKIP_LINK_HINTS = (
    "privacy", "terms", "cookie", "cart", "checkout", "login", "account",
    "careers", "investor", "press", "news", "facebook", "instagram",
    "youtube", "linkedin", "twitter", "x.com",
)

_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif")

_SKIP_IMAGE_PATH_HINTS = (
    "/navigation/", "/nav/", "/icons/", "/icon/", "/sustainability/",
    "/certificate/", "/certificates/", "/logo/", "/logos/",
    "favicon", "sprite", "social-icon", "country-flag", "payment-icon",
    "_logo.", "-logo.", "/logo.", "logo_black.", "logo_white.",
)

_ROLE_PATTERNS = {
    "front": ("front", "front view", "front-view", "straight on", "straight-on"),
    "left_angle": ("left angle", "left-angle", "left view", "left-view", "three quarter left", "3/4 left"),
    "right_angle": ("right angle", "right-angle", "right view", "right-view", "three quarter right", "3/4 right"),
    "side": ("side view", "side-view", "side profile", "profile view", "profile"),
    "back": ("rear view", "rear-view", "back view", "back-view", "rear", "back"),
    "top_detail": ("top view", "top-view", "overhead", "top detail", "top-detail"),
    "ports_detail": (
        "ports", "port detail", "port-detail", "i/o", "io panel", "i-o panel",
        "input output", "input-output", "connector", "connectors", "button functions",
        "buttons", "controls", "reset button", "bluetooth button", "power button",
        "ethernet port", "hdmi port", "usb port", "rear io", "rear i/o",
    ),
    "package_contents": (
        "package", "packaging", "box contents", "box-contents", "in the box",
        "in-the-box", "what's in the box", "what is in the box", "included accessories",
    ),
    "lifestyle": (
        "meeting room", "meeting-room", "conference room", "conference-room",
        "deployment", "installed", "installation", "workspace", "office",
        "room setup", "room-setup", "room solution", "room-solution",
    ),
    "closeup": ("close up", "close-up", "closeup", "detail view", "detail-view"),
}

_ACCESSORY_ONLY = (
    "cable", "adapter", "controller", "remote", "mount", "bracket", "power supply",
    "power-supply", "dongle", "mic pod", "microphone",
)


def _clean(value):
    return re.sub(r"\s+", " ", unescape(str(value or ""))).strip()


class _DeepParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.images = []
        self._current_href = ""
        self._current_link_text = []
        self.text_parts = []
        self._recent_text = []
        self._heading_tag = ""
        self._heading_parts = []
        self.current_heading = ""

    def _remember(self, value):
        value = _clean(value)
        if not value:
            return
        self.text_parts.append(value)
        self._recent_text.append(value)
        self._recent_text = self._recent_text[-10:]

    def handle_starttag(self, tag, attrs):
        attrs = {str(k).lower(): str(v or "") for k, v in attrs}
        tag = str(tag).lower()

        if tag == "a":
            self._current_href = attrs.get("href", "").strip()
            self._current_link_text = []

        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._heading_tag = tag
            self._heading_parts = []

        if tag == "img":
            explicit_context = " ".join(
                value for value in (
                    attrs.get("alt"), attrs.get("title"), attrs.get("aria-label"),
                    attrs.get("data-caption"), attrs.get("data-title"),
                ) if value
            )
            surrounding = " ".join(
                value for value in (
                    self.current_heading,
                    " ".join(self._recent_text[-6:]),
                    explicit_context,
                ) if value
            )
            values = []
            for key in (
                "src", "data-src", "data-lazy-src", "data-original",
                "data-image-src", "data-zoom-image",
            ):
                if attrs.get(key):
                    values.append(attrs[key])

            for key in ("srcset", "data-srcset"):
                raw = attrs.get(key, "")
                for match in re.finditer(
                    r"((?:https?:)?//\S+|/\S+|\.\.?/\S+)"
                    r"\s+(?:\d+(?:\.\d+)?[wx])(?=\s*,|\s*$)",
                    raw,
                    re.I,
                ):
                    values.append(match.group(1))

            for value in values:
                self.images.append({
                    "src": value.strip(),
                    "context": _clean(surrounding),
                    "heading": _clean(self.current_heading),
                })

    def handle_data(self, data):
        value = _clean(data)
        if not value:
            return
        self._remember(value)
        if self._current_href:
            self._current_link_text.append(value)
        if self._heading_tag:
            self._heading_parts.append(value)

    def handle_endtag(self, tag):
        tag = str(tag).lower()
        if tag == "a" and self._current_href:
            self.links.append(
                (self._current_href, _clean(" ".join(self._current_link_text)))
            )
            self._current_href = ""
            self._current_link_text = []

        if self._heading_tag and tag == self._heading_tag:
            self.current_heading = _clean(" ".join(self._heading_parts))
            self._heading_tag = ""
            self._heading_parts = []


def _secondary_seed_urls(item, official_domain):
    """Read admin-provided same-official-domain media evidence seeds."""
    raw = getattr(item, "secondary_evidence_urls", "") or ""
    if isinstance(raw, (list, tuple, set)):
        candidates = list(raw)
    else:
        candidates = re.split(r"[\r\n]+", str(raw))

    result = []
    for value in candidates:
        value = str(value or "").strip()
        if not value or not value.lower().startswith(("http://", "https://")):
            continue
        if not official_domain_matches(value, official_domain):
            continue
        if value not in result:
            result.append(value)
    return result


def _image_url(url, *, embedded=False):
    """Return True for a plausible image URL.

    Normal discovered/PDF URLs still require an image extension.  URLs coming
    directly from an HTML <img> element may be opaque CDN endpoints (for
    example imgix keys without .jpg/.png), so those are allowed only in
    ``embedded`` mode and are content-probed before admission.
    """
    parsed = urlparse(str(url or ""))
    if parsed.scheme.lower() not in {"http", "https"}:
        return False

    path = parsed.path.lower()
    haystack = (path + "?" + parsed.query).lower()

    if any(hint in haystack for hint in _SKIP_IMAGE_PATH_HINTS):
        return False

    if path.endswith(_IMAGE_EXTENSIONS):
        return True

    return bool(embedded and path and path != "/")


def _probe_embedded_image(url):
    """Resolve an embedded CDN URL and require real image content.

    This uses the importer's existing SSRF/TLS/redirect protections and never
    follows a browser page or executes JavaScript.
    """
    try:
        fetched = fetch_binary(
            url,
            timeout=15,
            max_bytes=12 * 1024 * 1024,
            user_agent="ArolanaProductImporter/5.0.12.1 (+https://arolana.com)",
            allowed_content_types={
                "image/png",
                "image/x-png",
                "image/jpeg",
                "image/jpg",
                "image/webp",
                "image/gif",
                "image/avif",
                "application/octet-stream",
            },
        )
    except (FetchBlocked, UnsafeURL, Exception):
        return ""

    return str(getattr(fetched, "url", "") or url).strip()


def _resource_score(href, text):
    haystack = f"{href} {text}".lower().replace("_", "-")
    if any(hint in haystack for hint in _SKIP_LINK_HINTS):
        return 0
    matches = [hint for hint in _RESOURCE_HINTS if hint in haystack]
    if not matches:
        return 0
    score = 5 * len(matches)
    if urlparse(href).path.lower().endswith(".pdf"):
        score += 2
    if "support" in haystack or "manual" in haystack or "setup" in haystack:
        score += 2
    return score


def discover_supplementary_links(html, *, base_url, official_domain, limit=12):
    parser = _DeepParser()
    try:
        parser.feed(html or "")
    except Exception:
        return []

    scored = []
    seen = set()
    for href, text in parser.links:
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        absolute = urljoin(base_url, href)
        if absolute in seen or not official_domain_matches(absolute, official_domain):
            continue
        score = _resource_score(absolute, text)
        if score <= 0:
            continue
        seen.add(absolute)
        scored.append((score, absolute))
    scored.sort(key=lambda row: (-row[0], row[1]))
    return [url for _score, url in scored[: max(1, min(int(limit or 12), 20))]]


def _identity_values(item):
    payload = item.normalized_payload or {}
    name = str(payload.get("name") or payload.get("title") or payload.get("product_name") or "").strip()
    model = str(payload.get("model") or payload.get("model_number") or "").strip()
    sku = str(
        payload.get("sku")
        or payload.get("mpn")
        or payload.get("manufacturer_part_number")
        or ""
    ).strip()
    product = getattr(item, "created_product", None)
    if product is not None:
        name = name or str(getattr(product, "name", "") or "")
        model = model or str(getattr(product, "model", "") or "")
        sku = sku or str(getattr(product, "sku", "") or getattr(product, "mpn", "") or "")
    return name, model, sku


def _semantic_normalize(value):
    """Normalize headings/captions without depending on punctuation style.

    Manufacturer support pages commonly write the same concept as:
    "Input + Output", "Input/Output", "Input & Output" or "Input-Output".
    Matching only literal punctuation caused valid support images to be skipped.
    """
    value = unescape(str(value or "")).lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _role_semantics(context):
    normalized = _semantic_normalize(context)
    roles = set()

    for role, patterns in _ROLE_PATTERNS.items():
        if any(
            _semantic_normalize(pattern) in normalized
            for pattern in patterns
            if _semantic_normalize(pattern)
        ):
            roles.add(role)

    if not roles:
        return set(), ""

    if "lifestyle" in roles:
        if any(
            _semantic_normalize(hint) in normalized
            for hint in _ACCESSORY_ONLY
            if _semantic_normalize(hint)
        ):
            roles.discard("lifestyle")
        else:
            return roles, "scene"

    if "package_contents" in roles:
        return roles, "package"

    physical_roles = roles - {"lifestyle", "package_contents"}
    if physical_roles:
        return roles, "physical"

    return roles, ""


def annotate_reference_url(url, *, roles, kind, source):
    parsed = urlparse(str(url or ""))
    fragment = parse_qs(parsed.fragment, keep_blank_values=True)
    fragment["arolana_verified"] = ["1"]
    fragment["arolana_view"] = [",".join(sorted(set(roles)))]
    fragment["arolana_kind"] = [str(kind or "")]
    fragment["arolana_source"] = [str(source or "")]
    encoded = urlencode([(k, v) for k, values in fragment.items() for v in values])
    return urlunparse((
        parsed.scheme, parsed.netloc, parsed.path, parsed.params, parsed.query, encoded
    ))


def _extract_html_images(html, *, page_url, official_domain, source):
    """Extract contextual images embedded by an official support page.

    The page itself is identity-checked by the caller.  The actual image may
    live on a manufacturer CDN or a delegated third-party CDN.  External/opaque
    images are accepted only when they came from an <img> tag, have useful
    view semantics, and resolve through ``fetch_binary`` as actual image data.
    """
    parser = _DeepParser()
    try:
        parser.feed(html or "")
    except Exception:
        return [], ""

    result = []
    external_probes = 0

    for row in parser.images:
        absolute = urljoin(page_url, row["src"])

        if not _image_url(absolute, embedded=True):
            continue

        context = _clean(
            f"{row.get('heading','')} {row.get('context','')} {absolute}"
        )
        roles, kind = _role_semantics(context)
        if not roles:
            continue

        same_official_domain = official_domain_matches(
            absolute,
            official_domain,
        )
        path = urlparse(absolute).path.lower()
        has_normal_extension = path.endswith(_IMAGE_EXTENSIONS)

        # A normal same-domain image already has manufacturer-domain provenance.
        # External CDN or opaque image endpoints must be content-probed.
        if same_official_domain and has_normal_extension:
            verified_url = absolute
        else:
            if external_probes >= 8:
                continue
            external_probes += 1
            verified_url = _probe_embedded_image(absolute)
            if not verified_url:
                continue

        if not _image_url(verified_url, embedded=True):
            continue

        result.append(
            annotate_reference_url(
                verified_url,
                roles=roles,
                kind=kind,
                source=source,
            )
        )

    return result, _clean(" ".join(parser.text_parts))


_URL_RE = re.compile(r"https?://[^\\s<>()\\[\\]\"']+", re.I)


def _pdf_image_urls(data, *, official_domain, source, identity):
    text = pdf_text_from_bytes(data, max_pages=40)
    match = document_identity_matches(
        text,
        name=identity[0],
        model=identity[1],
        sku=identity[2],
    )
    if not match.get("passed"):
        return [], text, match

    result = []
    for found in _URL_RE.finditer(text):
        raw = found.group(0).rstrip(".,;:")
        if not _image_url(raw, embedded=False) or not official_domain_matches(raw, official_domain):
            continue
        start = max(0, found.start() - 180)
        end = min(len(text), found.end() + 180)
        context = text[start:end]
        roles, kind = _role_semantics(context)
        if not roles:
            continue
        result.append(annotate_reference_url(
            raw, roles=roles, kind=kind, source=source
        ))
    return result, text, match


def _cache_key(item_id, evidence_id):
    return f"catalog-import-deep-official-v512:{item_id}:{evidence_id}"


def _dedupe_annotated_urls(values):
    deduped = []
    seen = set()
    for value in values or []:
        parsed = urlparse(value)
        key = (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.query,
            parsed.fragment,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(value)
    return deduped


def _fetch_verified_resource_references(
    *,
    resource_url,
    official_domain,
    identity,
    source_hint,
):
    """Fetch one official support/document seed and return verified media refs."""
    try:
        if urlparse(resource_url).path.lower().endswith(".pdf"):
            fetched = fetch_binary(
                resource_url,
                timeout=20,
                max_bytes=15 * 1024 * 1024,
                user_agent="ArolanaProductImporter/5.0.12.1 (+https://arolana.com)",
                allowed_content_types={
                    "application/pdf",
                    "application/octet-stream",
                },
            )
            if not official_domain_matches(fetched.url, official_domain):
                return []

            refs, _text, identity_result = _pdf_image_urls(
                fetched.data,
                official_domain=official_domain,
                source=(
                    "official-pdf-seed"
                    if "seed" in source_hint
                    else "official-pdf"
                ),
                identity=identity,
            )
            return refs if identity_result.get("passed") else []

        fetched = fetch_html(
            resource_url,
            timeout=15,
            max_bytes=5 * 1024 * 1024,
            user_agent="ArolanaProductImporter/5.0.12.1 (+https://arolana.com)",
        )
        if not official_domain_matches(fetched.url, official_domain):
            return []

        refs, page_text = _extract_html_images(
            fetched.text,
            page_url=fetched.url or resource_url,
            official_domain=official_domain,
            source=source_hint,
        )
        identity_result = document_identity_matches(
            page_text,
            name=identity[0],
            model=identity[1],
            sku=identity[2],
        )
        return refs if identity_result.get("passed") else []
    except (FetchBlocked, UnsafeURL, Exception):
        return []


def deep_official_reference_urls(
    *,
    item,
    manufacturer_evidences,
    official_domain,
    max_resources=10,
):
    """Return view-specific images from verified official support resources.

    Sources:
    1. bounded resource links discovered from manufacturer evidence pages;
    2. ImportItem.secondary_evidence_urls supplied by an admin, provided each
       URL stays on the configured official manufacturer domain.

    Secondary media seeds never replace retailer pricing or manufacturer specs.
    """
    identity = _identity_values(item)
    all_urls = []
    seen = set()
    direct_seeds = _secondary_seed_urls(item, official_domain)

    for evidence in manufacturer_evidences or []:
        if not evidence.url:
            continue
        if not official_domain_matches(evidence.url, official_domain):
            continue

        key = _cache_key(
            getattr(item, "pk", 0),
            getattr(evidence, "pk", 0),
        )
        cached = cache.get(key)
        if isinstance(cached, list):
            discovered = cached
        else:
            discovered = []
            try:
                product_page = fetch_html(
                    evidence.url,
                    timeout=15,
                    max_bytes=5 * 1024 * 1024,
                    user_agent=(
                        "ArolanaProductImporter/5.0.12.1 "
                        "(+https://arolana.com)"
                    ),
                )
            except (FetchBlocked, UnsafeURL):
                product_page = None

            links = []
            if product_page is not None:
                links = discover_supplementary_links(
                    product_page.text,
                    base_url=product_page.url or evidence.url,
                    official_domain=official_domain,
                    limit=max_resources,
                )

            for resource_url in links:
                discovered.extend(
                    _fetch_verified_resource_references(
                        resource_url=resource_url,
                        official_domain=official_domain,
                        identity=identity,
                        source_hint="official-support-discovered",
                    )
                )

            discovered = _dedupe_annotated_urls(discovered)
            try:
                cache.set(key, discovered, timeout=60 * 60 * 6)
            except Exception:
                pass

        for value in discovered:
            if value not in seen:
                seen.add(value)
                all_urls.append(value)

    # Process direct support/document seeds separately so the importer can use
    # product-specific support hubs even when the marketing page only links to a
    # generic support homepage.
    seed_key = (
        "catalog-import-deep-official-seeds-v512:"
        f"{getattr(item, 'pk', 0)}:"
        f"{abs(hash(tuple(direct_seeds)))}"
    )
    cached_seeds = cache.get(seed_key)
    if isinstance(cached_seeds, list):
        seed_refs = cached_seeds
    else:
        seed_refs = []
        for resource_url in direct_seeds[:20]:
            seed_refs.extend(
                _fetch_verified_resource_references(
                    resource_url=resource_url,
                    official_domain=official_domain,
                    identity=identity,
                    source_hint="official-support-seed",
                )
            )
        seed_refs = _dedupe_annotated_urls(seed_refs)
        try:
            cache.set(seed_key, seed_refs, timeout=60 * 60 * 6)
        except Exception:
            pass

    for value in seed_refs:
        if value not in seen:
            seen.add(value)
            all_urls.append(value)

    return all_urls

def deep_official_reference_report(*, item, manufacturer_evidences, official_domain):
    urls = deep_official_reference_urls(
        item=item,
        manufacturer_evidences=manufacturer_evidences,
        official_domain=official_domain,
    )
    rows = []
    for url in urls:
        parsed = urlparse(url)
        meta = parse_qs(parsed.fragment)
        rows.append({
            "url": url,
            "source_url": urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, parsed.query, "")),
            "roles": (meta.get("arolana_view") or [""])[0].split(",") if meta.get("arolana_view") else [],
            "kind": (meta.get("arolana_kind") or [""])[0],
            "source": (meta.get("arolana_source") or [""])[0],
        })
    return rows
