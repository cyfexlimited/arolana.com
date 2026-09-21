"""Official-manufacturer reference discovery and ranking.

Phase 5 reference handling protects exact product identity and view semantics. a manufacturer evidence payload
can contain only lifestyle images even when the official product page contains
clean product renders elsewhere in its HTML.

This service remains manufacturer-neutral. It may discover additional image
URLs only from the already-verified official manufacturer page and only when
the URL remains inside the admin-configured official brand domain.
"""
import json
import re
from functools import lru_cache
from html.parser import HTMLParser
from io import BytesIO
from urllib.parse import parse_qs, unquote, urljoin, urlparse

from django.core.cache import cache

from catalog_imports.models import (
    BrandVerificationProfile,
    ImportEvidence,
    ImportMediaCandidate,
)
from catalog_imports.services.evidence import official_domain_matches
from catalog_imports.services.http_fetch import (
    FetchBlocked,
    UnsafeURL,
    fetch_binary,
    fetch_html,
)


_PRODUCT_HINTS = (
    "product", "device", "hardware", "hero", "gallery", "front", "angle",
    "side", "back", "top", "detail", "closeup", "close-up", "transparent",
    "cutout", "white-background", "isolated", "render", "beauty",
)
_LIFESTYLE_HINTS = (
    "lifestyle", "room", "meeting-room", "conference-room", "workspace",
    "environment", "in-room", "installation", "installed", "setup", "office",
    "collaboration", "use-case", "usecase", "case-study", "people", "team",
)
_PACKAGE_HINTS = (
    "package", "packaging", "box", "contents", "in-the-box", "accessories", "bundle",
)
_SKIP_IMAGE_HINTS = (
    "favicon", "sprite", "loader", "spinner", "avatar", "social-icon",
    "social_icon", "country-flag", "country_flag", "payment-icon",
    "payment_icon", "pixel.gif", "tracking", "analytics",
)

_VIEW_HINTS = {
    ImportMediaCandidate.VIEW_FRONT: ("front", "straight", "face"),
    ImportMediaCandidate.VIEW_LEFT: ("left", "left-angle", "left_angle"),
    ImportMediaCandidate.VIEW_RIGHT: ("right", "right-angle", "right_angle"),
    ImportMediaCandidate.VIEW_SIDE: ("side", "profile"),
    ImportMediaCandidate.VIEW_BACK: ("back", "rear"),
    ImportMediaCandidate.VIEW_TOP: ("top", "detail", "closeup", "close-up"),
    ImportMediaCandidate.VIEW_PORTS: ("port", "ports", "rear", "back", "connector", "detail"),
    ImportMediaCandidate.VIEW_PACKAGE: _PACKAGE_HINTS,
    ImportMediaCandidate.VIEW_LIFESTYLE: _LIFESTYLE_HINTS,
    ImportMediaCandidate.VIEW_MAIN: ("hero", "product", "front", "angle", "beauty"),
}


def _image_urls(payload):
    urls = []
    for item in (payload or {}).get("images", []) or []:
        if isinstance(item, str):
            value = item
        elif isinstance(item, dict):
            value = item.get("reference_url") or item.get("url") or item.get("src") or ""
        else:
            value = ""
        value = str(value or "").strip()
        if value and value not in urls:
            urls.append(value)
    return urls


def _semantic_image_urls(payload):
    """Return reference URLs, preserving persisted Phase 5.3.5 role annotations."""
    result = []
    for item in (payload or {}).get("images", []) or []:
        if isinstance(item, str):
            value = str(item or "").strip()
        elif isinstance(item, dict):
            value = str(
                item.get("reference_url")
                or item.get("url")
                or item.get("src")
                or ""
            ).strip()
        else:
            value = ""

        if value and value not in result:
            result.append(value)
    return result


_SRCSET_DESCRIPTOR_RE = re.compile(
    r"(?P<url>(?:https?:)?//\S+|/\S+|\.\.?/\S+)"
    r"\s+(?:\d+(?:\.\d+)?[wx])(?=\s*,|\s*$)",
    re.IGNORECASE,
)


def _srcset_urls(value):
    """Parse srcset without breaking CDN URLs that contain commas.

    Many image CDNs use comma-separated transformation directives inside the URL
    itself (for example ``w_1800,h_1800,c_limit``). A plain ``split(",")``
    therefore corrupts valid URLs into fragments. We split on the browser-style
    density/width descriptor boundary instead.
    """
    raw = str(value or "").strip()
    if not raw:
        return []

    result = []
    for match in _SRCSET_DESCRIPTOR_RE.finditer(raw):
        candidate = match.group("url").strip()
        if candidate and candidate not in result:
            result.append(candidate)

    if result:
        return result

    # Descriptor-less fallback: only split commas that are followed by whitespace
    # and a new URL-looking token. Commas inside CDN transform paths remain intact.
    for part in re.split(r",\s+(?=(?:https?:)?//|/|\.\.?/)", raw):
        candidate = part.strip().split()[0] if part.strip() else ""
        if candidate and candidate not in result:
            result.append(candidate)
    return result


def _jsonld_image_values(value, result):
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = str(key).lower()
            if lowered in {"image", "images", "contenturl", "thumbnailurl"}:
                _jsonld_image_values(child, result)
            elif isinstance(child, (dict, list)):
                _jsonld_image_values(child, result)
    elif isinstance(value, list):
        for child in value:
            _jsonld_image_values(child, result)
    elif isinstance(value, str):
        text = value.strip()
        if text and text not in result:
            result.append(text)


class _OfficialImageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.urls = []
        self._in_jsonld = False
        self._jsonld_parts = []

    def _add(self, value):
        value = str(value or "").strip()
        if not value:
            return

        # Some sites place a complete srcset string into lazy-loading attributes.
        # Normalize it here instead of recording the whole string as one URL.
        if re.search(r"\s+\d+(?:\.\d+)?[wx](?:\s*,|\s*$)", value, re.IGNORECASE):
            for candidate in _srcset_urls(value):
                if candidate and candidate not in self.urls:
                    self.urls.append(candidate)
            return

        if value not in self.urls:
            self.urls.append(value)

    def handle_starttag(self, tag, attrs):
        attrs = {str(k).lower(): v for k, v in attrs}
        tag = str(tag).lower()

        if tag == "script":
            script_type = str(attrs.get("type") or "").lower()
            if "ld+json" in script_type:
                self._in_jsonld = True
                self._jsonld_parts = []
            return

        if tag == "img":
            for name in (
                "src", "data-src", "data-lazy-src", "data-original",
                "data-image", "data-image-src", "data-zoom-image",
            ):
                self._add(attrs.get(name))
            for value in _srcset_urls(attrs.get("srcset")):
                self._add(value)
            for value in _srcset_urls(attrs.get("data-srcset")):
                self._add(value)

        elif tag == "source":
            for value in _srcset_urls(attrs.get("srcset")):
                self._add(value)
            for value in _srcset_urls(attrs.get("data-srcset")):
                self._add(value)

        elif tag == "meta":
            key = str(attrs.get("property") or attrs.get("name") or "").lower()
            if key in {
                "og:image", "og:image:url", "og:image:secure_url",
                "twitter:image", "twitter:image:src",
            }:
                self._add(attrs.get("content"))

        elif tag == "link":
            rel = str(attrs.get("rel") or "").lower()
            as_value = str(attrs.get("as") or "").lower()
            if "image_src" in rel or ("preload" in rel and as_value == "image"):
                self._add(attrs.get("href"))
                for value in _srcset_urls(attrs.get("imagesrcset")):
                    self._add(value)

    def handle_endtag(self, tag):
        if str(tag).lower() == "script" and self._in_jsonld:
            raw = "".join(self._jsonld_parts).strip()
            self._in_jsonld = False
            self._jsonld_parts = []
            if raw:
                try:
                    parsed = json.loads(raw)
                except Exception:
                    return
                found = []
                _jsonld_image_values(parsed, found)
                for value in found:
                    self._add(value)

    def handle_data(self, data):
        if self._in_jsonld:
            self._jsonld_parts.append(data)


_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif")
_PAGE_CHROME_HINTS = (
    "/navigation/", "/sustainability/", "/certificate/", "/certificates/",
    "/icons/", "/icon/", "platform-microsoft-logo", "platform-zoom-logo",
    "platform-google-meet-logo", "taa-compliant-logo",
)


def _looks_like_image_url(url):
    text = unquote(str(url or "")).strip().lower()
    if not text.startswith(("http://", "https://")):
        return False
    if any(ch.isspace() for ch in text):
        return False
    if any(hint in text for hint in _SKIP_IMAGE_HINTS):
        return False

    path = (urlparse(text).path or "").lower()
    # Phase 5.0.5 accepted transform fragments such as /w_1206 and /c_limit.
    # A generation reference must resolve to a concrete image asset.
    if not path.endswith(_IMAGE_EXTENSIONS):
        return False
    if path.endswith((".svg", ".ico")):
        return False
    return True


def extract_official_image_urls(html, *, page_url, official_domain, max_urls=120):
    """Extract same-official-domain image candidates from manufacturer HTML."""
    parser = _OfficialImageParser()
    try:
        parser.feed(str(html or ""))
    except Exception:
        pass

    result = []
    for raw in parser.urls:
        absolute = urljoin(page_url, str(raw or "").strip())
        if not _looks_like_image_url(absolute):
            continue
        if not official_domain_matches(absolute, official_domain):
            continue
        if absolute not in result:
            result.append(absolute)
        if len(result) >= max(1, min(int(max_urls or 120), 250)):
            break
    return result


def _brand_name(item):
    payload = item.normalized_payload or {}
    return str(payload.get("brand") or payload.get("manufacturer") or "").strip()


def _verification_profile(item):
    brand = _brand_name(item)
    if not brand:
        return None
    return (
        BrandVerificationProfile.objects
        .filter(is_active=True, brand_name__iexact=brand)
        .exclude(official_domain="")
        .first()
    )


def _official_manufacturer_evidence(item):
    return list(
        item.evidence_records.filter(
            role=ImportEvidence.ROLE_MANUFACTURER,
            status=ImportEvidence.STATUS_FETCHED,
            is_authoritative=True,
        ).order_by("id")
    )


def _discovery_cache_key(evidence_id, url):
    return "catalog-import-official-images-v512:" + str(evidence_id) + ":" + str(abs(hash(url)))


def _discover_page_images(evidence, official_domain):
    cache_key = _discovery_cache_key(evidence.pk, evidence.url)
    cached = cache.get(cache_key)
    if isinstance(cached, list):
        return [str(x) for x in cached if x]

    try:
        result = fetch_html(
            evidence.url,
            timeout=15,
            max_bytes=5 * 1024 * 1024,
            user_agent="ArolanaProductImporter/5.0.12.2 (+https://arolana.com)",
        )
        urls = extract_official_image_urls(
            result.text,
            page_url=result.url or evidence.url,
            official_domain=official_domain,
        )
    except (FetchBlocked, UnsafeURL, Exception):
        urls = []

    try:
        cache.set(cache_key, urls, timeout=60 * 60 * 6)
    except Exception:
        pass
    return urls


_IDENTITY_STOPWORDS = {
    "a", "an", "and", "for", "with", "the", "of", "by", "new",
    "video", "conferencing", "conference", "camera", "cameras", "webcam",
    "solution", "system", "device", "product", "business", "wireless", "wired",
    "black", "white", "graphite", "edition", "bundle", "kit",
}


def _identity_strings(item):
    payload = item.normalized_payload or {}
    values = []

    def add(value):
        value = str(value or "").strip()
        if value and value not in values:
            values.append(value)

    for key in (
        "name", "title", "product_name", "model", "model_number", "mpn",
        "manufacturer_part_number", "sku",
    ):
        add(payload.get(key))

    identifiers = payload.get("identifiers")
    if isinstance(identifiers, dict):
        for value in identifiers.values():
            add(value)

    product = getattr(item, "created_product", None)
    for attr in ("name", "title", "model", "sku", "mpn"):
        add(getattr(product, attr, None) if product is not None else None)

    return values


def _identity_tokens(item):
    brand = _brand_name(item).lower()
    brand_tokens = set(re.findall(r"[a-z0-9]+", brand))
    tokens = []
    for value in _identity_strings(item):
        for token in re.findall(r"[a-z0-9]+", value.lower()):
            if token in brand_tokens or token in _IDENTITY_STOPWORDS:
                continue
            if len(token) == 1 and not token.isdigit():
                continue
            if token not in tokens:
                tokens.append(token)
    return tokens[:10]


def _strong_model_token(token):
    token = str(token or "")
    return (
        len(token) >= 4
        and any(ch.isalpha() for ch in token)
        and any(ch.isdigit() for ch in token)
    )


def _normalized_identity_tokens(value, *, brand_tokens=None):
    brand_tokens = set(brand_tokens or ())
    tokens = []
    for token in re.findall(r"[a-z0-9]+", str(value or "").lower()):
        if token in brand_tokens or token in _IDENTITY_STOPWORDS:
            continue
        if len(token) == 1 and not token.isdigit():
            continue
        tokens.append(token)
    return tokens


def _identity_slug_signatures(item):
    """Build conservative exact-product signatures from verified identity strings.

    Examples:
    - "MeetUp 2 Video Conferencing Camera" -> "meetup-2"
    - "Speak 510 MS" -> "speak-510" / "speak-510-ms"
    - "C920e Business Webcam" -> "c920e"
    - "Rally Bar Huddle" -> "rally-bar-huddle"

    We deliberately avoid weak single family-name signatures when a stronger
    model/version signature exists.
    """
    brand_tokens = set(re.findall(r"[a-z0-9]+", _brand_name(item).lower()))
    signatures = []

    def add(signature):
        signature = str(signature or "").strip("-")
        if signature and signature not in signatures:
            signatures.append(signature)

    for value in _identity_strings(item):
        tokens = _normalized_identity_tokens(value, brand_tokens=brand_tokens)
        if not tokens:
            continue

        # Strong model codes such as C920e, HW520, X371, AD4D.
        for token in tokens:
            if _strong_model_token(token):
                add(token)

        # Family + numeric model/version is a particularly strong signature.
        for index in range(len(tokens) - 1):
            left, right = tokens[index], tokens[index + 1]
            if right.isdigit() and any(ch.isalpha() for ch in left):
                add(f"{left}-{right}")
                if index + 2 < len(tokens):
                    tail = tokens[index + 2]
                    if len(tail) >= 2 and not tail.isdigit():
                        add(f"{left}-{right}-{tail}")

        # For named products without a numeric model, prefer a longer phrase.
        alphaish = [t for t in tokens if any(ch.isalpha() for ch in t)]
        if len(alphaish) >= 3:
            add("-".join(alphaish[:3]))
        elif len(alphaish) == 2:
            add("-".join(alphaish))

    # Longest/most-specific signatures first.
    signatures.sort(key=lambda value: (value.count("-"), len(value)), reverse=True)
    return signatures


def _asset_match_text(url):
    parsed = urlparse(str(url or ""))
    path = unquote(parsed.path or "").lower()
    marker = "/content/dam/"
    if marker in path:
        path = path[path.index(marker):]
    return re.sub(r"[^a-z0-9]+", "-", path).strip("-")


def _signature_in_asset(signature, asset_text):
    signature = re.sub(r"[^a-z0-9]+", "-", str(signature or "").lower()).strip("-")
    asset_text = re.sub(r"[^a-z0-9]+", "-", str(asset_text or "").lower()).strip("-")
    if not signature or not asset_text:
        return False
    return re.search(rf"(?:^|-){re.escape(signature)}(?:-|$)", asset_text) is not None



def _reference_annotation(url):
    """Read Arolana-only semantic metadata stored in the URL fragment.

    The fragment is never sent to the manufacturer server, so the underlying
    official image URL remains unchanged for fetching.  Only the importer adds
    these annotations, after exact-product verification of a supplementary
    official page/document.
    """
    try:
        fragment = urlparse(str(url or "")).fragment
        values = parse_qs(fragment, keep_blank_values=True)
    except Exception:
        return {"verified": False, "roles": set(), "kind": "", "source": ""}

    verified = str((values.get("arolana_verified") or [""])[0]).lower() in {"1", "true", "yes"}
    role_values = []
    for raw in values.get("arolana_view", []):
        role_values.extend(str(raw or "").split(","))
    roles = {value.strip() for value in role_values if value.strip()}
    return {
        "verified": verified,
        "roles": roles,
        "kind": str((values.get("arolana_kind") or [""])[0] or "").strip().lower(),
        "source": str((values.get("arolana_source") or [""])[0] or "").strip().lower(),
    }


def _product_relevant_url(item, url):
    """Conservatively keep images that belong to the exact verified product.

    Same-domain is necessary but not sufficient. Manufacturer pages commonly
    contain navigation artwork, sustainability badges and sibling/predecessor
    products. Phase 5.0.6 also showed why raw numeric substring matching is unsafe:
    version "2" could accidentally match CDN transforms like ``h_220`` or
    filenames such as ``front-01``.

    Strong identity signatures are therefore matched only against the underlying
    asset path, with token boundaries.
    """
    text = unquote(str(url or "")).lower().replace("_", "-")
    if any(hint in text for hint in _PAGE_CHROME_HINTS):
        return False

    annotation = _reference_annotation(url)
    if annotation["verified"] and annotation["roles"]:
        # This image came from an identity-verified same-domain supplementary
        # manufacturer page/document and carries an explicit view classification.
        return True

    asset_text = _asset_match_text(url)
    signatures = _identity_slug_signatures(item)
    if signatures:
        return any(_signature_in_asset(signature, asset_text) for signature in signatures)

    # Conservative fallback for products whose identity cannot produce a strong
    # slug. Match whole tokens against the asset path rather than arbitrary URL
    # substrings or CDN transformation numbers.
    tokens = _identity_tokens(item)
    if not tokens:
        return True

    asset_tokens = set(re.findall(r"[a-z0-9]+", asset_text))
    matched = [token for token in tokens if token in asset_tokens]
    required = 1 if len(tokens) == 1 else 2
    return len(set(matched)) >= min(required, len(tokens))

def _asset_identity(url):
    """Deduplicate transformed variants of the same underlying manufacturer asset."""
    parsed = urlparse(str(url or ""))
    path = unquote(parsed.path or "")
    marker = "/content/dam/"
    lowered = path.lower()
    if marker in lowered:
        idx = lowered.index(marker)
        return lowered[idx:]
    return (parsed.netloc.lower() + lowered).rstrip("/")


def _append_unique_asset(urls, asset_keys, url):
    value = str(url or "").strip()
    if not value:
        return
    key = _asset_identity(value)
    if key in asset_keys:
        return
    asset_keys.add(key)
    urls.append(value)


def manufacturer_reference_urls(item):
    """Return exact-product official manufacturer images.

    Existing evidence images are retained because they were already captured from
    authoritative evidence. Newly discovered page images must additionally look
    relevant to the exact product identity; same-domain navigation/related-product
    assets are excluded.
    """
    urls = []
    asset_keys = set()
    evidences = _official_manufacturer_evidence(item)

    for evidence in evidences:
        for url in _semantic_image_urls(evidence.extracted_payload):
            annotation = _reference_annotation(url)
            trusted_annotated_reference = bool(
                annotation["verified"] and annotation["roles"]
            )
            if (
                (_looks_like_image_url(url) or trusted_annotated_reference)
                and _product_relevant_url(item, url)
            ):
                _append_unique_asset(urls, asset_keys, url)

    profile = _verification_profile(item)
    official_domain = str(getattr(profile, "official_domain", "") or "").strip()
    if not official_domain:
        return urls

    for evidence in evidences:
        if not evidence.url or not official_domain_matches(evidence.url, official_domain):
            continue
        for url in _discover_page_images(evidence, official_domain):
            if not _product_relevant_url(item, url):
                continue
            _append_unique_asset(urls, asset_keys, url)

    # Phase 5.0.10: crawl a small, bounded set of same-official-domain support,
    # setup, installation, manual and resource pages linked from the verified
    # manufacturer page.  Each supplementary page/document must identify the
    # same product before its image references are admitted.
    try:
        from .deep_official_references import deep_official_reference_urls
        deep_urls = deep_official_reference_urls(
            item=item,
            manufacturer_evidences=evidences,
            official_domain=official_domain,
        )
    except Exception:
        # Deep acquisition is an optional enrichment layer.  A crawl/parser
        # failure must never weaken the ordinary verified reference set.
        deep_urls = []

    for url in deep_urls:
        annotation = _reference_annotation(url)

        # Deep official-support references may point to opaque delegated CDN
        # endpoints without a .jpg/.png suffix.  They are admitted only after
        # the deep-reference service has identity-verified the official page,
        # classified the exact view, and content-probed the embedded URL.
        trusted_deep_reference = bool(
            annotation["verified"] and annotation["roles"]
        )

        if not (_looks_like_image_url(url) or trusted_deep_reference):
            continue
        if not _product_relevant_url(item, url):
            continue
        _append_unique_asset(urls, asset_keys, url)

    return urls


class ReferenceViewHold(ValueError):
    """Raised when official evidence cannot safely support the requested physical view."""


_STRICT_VIEW_ROLES = {
    ImportMediaCandidate.VIEW_FRONT,
    ImportMediaCandidate.VIEW_LEFT,
    ImportMediaCandidate.VIEW_RIGHT,
    ImportMediaCandidate.VIEW_SIDE,
    ImportMediaCandidate.VIEW_BACK,
    ImportMediaCandidate.VIEW_TOP,
    ImportMediaCandidate.VIEW_PORTS,
    ImportMediaCandidate.VIEW_PACKAGE,
    ImportMediaCandidate.VIEW_CLOSEUP,
}

_VIEW_ROLE_LABELS = {
    ImportMediaCandidate.VIEW_MAIN: "main/hero",
    ImportMediaCandidate.VIEW_FRONT: "front",
    ImportMediaCandidate.VIEW_LEFT: "left-angle",
    ImportMediaCandidate.VIEW_RIGHT: "right-angle",
    ImportMediaCandidate.VIEW_SIDE: "side-profile",
    ImportMediaCandidate.VIEW_BACK: "rear/back",
    ImportMediaCandidate.VIEW_TOP: "top/detail",
    ImportMediaCandidate.VIEW_PORTS: "ports/controls",
    ImportMediaCandidate.VIEW_PACKAGE: "package/contents",
    ImportMediaCandidate.VIEW_LIFESTYLE: "lifestyle",
    ImportMediaCandidate.VIEW_CLOSEUP: "close-up/detail",
}

_EXPLICIT_VIEW_PATTERNS = {
    ImportMediaCandidate.VIEW_FRONT: (
        "front", "front-view", "frontview", "straight-on", "straighton",
    ),
    ImportMediaCandidate.VIEW_LEFT: (
        "left-angle", "leftangle", "left-view", "leftview",
        "left-3q", "3q-left", "three-quarter-left", "threequarterleft",
    ),
    ImportMediaCandidate.VIEW_RIGHT: (
        "right-angle", "rightangle", "right-view", "rightview",
        "right-3q", "3q-right", "three-quarter-right", "threequarterright",
    ),
    ImportMediaCandidate.VIEW_SIDE: (
        "side-view", "sideview", "side-profile", "sideprofile", "profile-view",
        "profileview", "profile",
    ),
    ImportMediaCandidate.VIEW_BACK: (
        "back-view", "backview", "rear-view", "rearview", "rear", "back",
    ),
    ImportMediaCandidate.VIEW_TOP: (
        "top-view", "topview", "overhead", "top-detail", "topdetail",
        "detail-top", "detailtop",
    ),
    ImportMediaCandidate.VIEW_PORTS: (
        "ports", "port-detail", "portdetail", "io-panel", "i-o-panel",
        "connector", "connectors", "ethernet-port", "hdmi-port", "usb-port",
        "input-output", "inputoutput",
    ),
    ImportMediaCandidate.VIEW_PACKAGE: (
        "package", "packaging", "box", "in-the-box", "inthebox",
        "box-contents", "boxcontents", "package-contents", "packagecontents",
    ),
    ImportMediaCandidate.VIEW_LIFESTYLE: (
        "lifestyle", "meeting-room", "meetingroom", "conference-room",
        "conferenceroom", "room-solution", "roomsolution", "deployment",
        "workspace", "office", "installed", "setup",
    ),
    ImportMediaCandidate.VIEW_CLOSEUP: (
        "close-up", "closeup", "detail", "macro",
    ),
}

_GENERIC_FRONT_PRODUCT_HINTS = (
    "/gallery/", "hero", "og-image", "twitter-image", "product-front",
    "graphite-01", "white-01", "black-01", "beauty",
)


def _reference_semantic_text(url):
    """Return normalized underlying asset text, excluding CDN transform noise."""
    parsed = urlparse(str(url or ""))
    path = unquote(parsed.path or "").lower()
    marker = "/content/dam/"
    if marker in path:
        path = path[path.index(marker):]
    return re.sub(r"[^a-z0-9]+", "-", path).strip("-")



_SCENE_COMPOSITE_HINTS = (
    "lifestyle", "meeting-room", "meetingroom", "conference-room",
    "conferenceroom", "room-solution", "roomsolution", "deployment",
    "workspace", "office", "installed", "installation", "setup",
    "use-case", "usecase", "case-study", "casestudy", "experience",
    "digital-signage", "digitalsignage",
)

_ACCESSORY_ONLY_HINTS = (
    "cable", "active-usb", "activeusb", "usb-cable", "usbcable",
    "controller", "touch-controller", "touchcontroller", "tap",
    "remote", "adapter", "dongle", "mount", "bracket",
    "power-supply", "powersupply", "power-adapter", "poweradapter",
    "mic-pod", "micpod", "microphone", "accessory", "accessories",
)

_PORT_DETAIL_HINTS = (
    "ports", "port-detail", "portdetail", "io-panel", "i-o-panel",
    "connector", "connectors", "ethernet-port", "ethernetport",
    "hdmi-port", "hdmiport", "usb-port", "usbport",
    "input-output", "inputoutput", "rear-io", "reario",
    "connection-panel", "connectionpanel",
)

_LIFESTYLE_STRONG_HINTS = (
    "deployment", "meeting-room", "meetingroom", "conference-room",
    "conferenceroom", "workspace", "office", "installed", "installation",
    "room-solution", "roomsolution", "lifestyle",
)


def _semantic_tokens(value):
    return set(re.findall(r"[a-z0-9]+", str(value or "").lower()))


def _hint_belongs_to_product_identity(item, hint):
    """Do not treat a term as an accessory if it is part of the product's own identity.

    Example: a product actually named "Tap" should not have every URL containing
    "tap" rejected as accessory-only.
    """
    hint_tokens = _semantic_tokens(hint)
    if not hint_tokens:
        return False

    identity = set()
    for value in _identity_strings(item):
        identity.update(_semantic_tokens(value))
    identity.update(_semantic_tokens(_brand_name(item)))
    return hint_tokens.issubset(identity)


def _matching_hints(text, hints):
    normalized = str(text or "").lower().replace("_", "-")
    return [hint for hint in hints if hint in normalized]


_STRICT_VISUAL_REFERENCE_ROLES = {
    ImportMediaCandidate.VIEW_FRONT,
    ImportMediaCandidate.VIEW_LEFT,
    ImportMediaCandidate.VIEW_RIGHT,
    ImportMediaCandidate.VIEW_SIDE,
    ImportMediaCandidate.VIEW_BACK,
    ImportMediaCandidate.VIEW_TOP,
    ImportMediaCandidate.VIEW_PORTS,
    ImportMediaCandidate.VIEW_PACKAGE,
    ImportMediaCandidate.VIEW_LIFESTYLE,
    ImportMediaCandidate.VIEW_CLOSEUP,
}


def _reference_base_url(url):
    """Normalize only Arolana's annotation query parameters away.

    CDN transformation/query parameters are preserved because they can identify
    a distinct underlying manufacturer asset.  The Arolana role/source flags are
    metadata and must not affect identity matching.
    """
    parsed = urlparse(str(url or "").strip())
    query = parse_qs(parsed.query, keep_blank_values=True)
    kept = []
    for key, values in query.items():
        if str(key).startswith("arolana_"):
            continue
        for value in values:
            kept.append((key, value))

    from urllib.parse import urlencode
    return parsed._replace(
        query=urlencode(kept, doseq=True),
        fragment="",
    ).geturl()


def visual_classifier_roles_for_reference(item, url):
    """Return roles proven from actual manufacturer image pixels.

    This intentionally reads the persisted Phase 5.3.6 visual-classifier result,
    rather than trusting filename/alt-text semantic annotations.  A semantic
    label can help discovery, but it cannot prove a factual physical perspective.
    """
    target = _reference_base_url(url)
    roles = set()

    evidence_manager = getattr(item, "evidence_records", None)
    if evidence_manager is None:
        # Non-ORM callers may not expose evidence_records. Missing persisted
        # visual evidence must fail closed; it must never make a factual role
        # appear verified.
        return roles

    evidences = evidence_manager.filter(
        role=ImportEvidence.ROLE_MANUFACTURER,
        is_authoritative=True,
        status=ImportEvidence.STATUS_FETCHED,
    )

    for evidence in evidences:
        for entry in (evidence.extracted_payload or {}).get("images", []) or []:
            if not isinstance(entry, dict):
                continue
            entry_url = str(
                entry.get("reference_url")
                or entry.get("url")
                or entry.get("src")
                or ""
            ).strip()
            if not entry_url or _reference_base_url(entry_url) != target:
                continue

            visual = entry.get("visual_classifier") or {}
            if str(visual.get("status") or "") != "classified":
                continue
            for role in visual.get("accepted_roles") or []:
                value = str(role or "").strip()
                if value:
                    roles.add(value)

    return roles


def strict_role_match_for_reference(item, url, view_role):
    """True only when actual image pixels visually prove the requested role."""
    if view_role == ImportMediaCandidate.VIEW_MAIN:
        return True
    if view_role not in _STRICT_VISUAL_REFERENCE_ROLES:
        return True
    return view_role in visual_classifier_roles_for_reference(item, url)


def semantic_reference_decision(item, url, view_role):
    """Return (eligible, reason) for the *meaning* of an official image asset.

    A filename containing a keyword is not automatically proof of the requested
    view. Marketing images such as "...experience-ethernet-port.png" may show a
    room/monitor rather than the physical port. Likewise a room-solution image
    can actually be a standalone cable or controller.

    This gate is intentionally conservative because an unsupported result costs
    nothing, while a false-positive reference can cause the image model to invent
    product geometry.
    """
    text = _reference_semantic_text(url)

    if view_role in _STRICT_VISUAL_REFERENCE_ROLES:
        visual_roles = visual_classifier_roles_for_reference(item, url)
        if view_role in visual_roles:
            return True, ""
        return (
            False,
            "The exact-product image exists, but its pixels were not visually "
            "classified as the requested role. Identity-only or filename-only "
            "evidence cannot verify factual geometry."
        )

    roles = classify_reference_views(url)

    if view_role not in roles:
        return False, "The asset identity does not explicitly support this requested view."

    annotation = _reference_annotation(url)
    scene_hits = _matching_hints(text, _SCENE_COMPOSITE_HINTS)
    accessory_hits = [
        hint for hint in _matching_hints(text, _ACCESSORY_ONLY_HINTS)
        if not _hint_belongs_to_product_identity(item, hint)
    ]

    if view_role == ImportMediaCandidate.VIEW_LIFESTYLE:
        if annotation["verified"] and annotation["kind"] == "scene" and view_role in annotation["roles"]:
            return True, ""
        strong_scene = _matching_hints(text, _LIFESTYLE_STRONG_HINTS)
        if not strong_scene:
            return False, "Lifestyle reference lacks a strong room/deployment/installation signal."
        if accessory_hits:
            return (
                False,
                "Lifestyle reference appears accessory/component-specific "
                f"({', '.join(accessory_hits[:3])}) rather than a product-in-room scene."
            )
        # Feature-callout images often say "ethernet-port" or similar while
        # actually depicting a UI/monitor composition. They are not lifestyle
        # grounding unless the URL has a real deployment/room signal without a
        # component-only qualifier.
        if _matching_hints(text, _PORT_DETAIL_HINTS) and "deployment" not in text:
            return False, "Lifestyle reference is a feature/port callout, not a clean room/deployment scene."
        return True, ""

    if view_role == ImportMediaCandidate.VIEW_PORTS:
        if annotation["verified"] and annotation["kind"] == "physical" and view_role in annotation["roles"]:
            return True, ""
        port_hits = _matching_hints(text, _PORT_DETAIL_HINTS)
        if not port_hits:
            return False, "Ports/controls reference lacks an explicit physical port/I-O signal."
        if scene_hits:
            return (
                False,
                "Ports/controls reference is a marketing scene/experience composite "
                f"({', '.join(scene_hits[:3])}), not a physical port close-up."
            )
        if accessory_hits:
            return (
                False,
                "Ports/controls reference appears to show an accessory/component "
                f"({', '.join(accessory_hits[:3])}) rather than the product I/O panel."
            )
        return True, ""

    if view_role in {
        ImportMediaCandidate.VIEW_LEFT,
        ImportMediaCandidate.VIEW_RIGHT,
        ImportMediaCandidate.VIEW_SIDE,
        ImportMediaCandidate.VIEW_BACK,
        ImportMediaCandidate.VIEW_TOP,
        ImportMediaCandidate.VIEW_CLOSEUP,
    }:
        if annotation["verified"] and annotation["kind"] == "physical" and view_role in annotation["roles"]:
            return True, ""
        if scene_hits:
            return (
                False,
                "Physical-view reference is embedded in a room/experience composite "
                "and is not reliable proof of hidden product geometry."
            )
        if accessory_hits:
            return (
                False,
                "Physical-view reference appears accessory/component-specific "
                "instead of showing the exact product body."
            )
        return True, ""

    if view_role == ImportMediaCandidate.VIEW_PACKAGE:
        if annotation["verified"] and annotation["kind"] == "package" and view_role in annotation["roles"]:
            return True, ""
        if scene_hits:
            return False, "Package/contents reference is a scene/composite rather than actual packaging."
        return True, ""

    return True, ""


def semantic_reference_audit(item, view_role):
    """Return eligible and rejected official references with explicit reasons."""
    urls = manufacturer_reference_urls(item)
    ranked = rank_reference_urls(urls, view_role) if urls else []
    eligible = []
    rejected = []
    for url in ranked:
        allowed, reason = semantic_reference_decision(item, url, view_role)
        if allowed:
            eligible.append(url)
        else:
            rejected.append({"url": url, "reason": reason})
    return {
        "view_role": view_role,
        "eligible_urls": eligible,
        "rejected": rejected,
    }


def classify_reference_views(url):
    """Classify a manufacturer image by view signals present in its asset identity.

    Classification is intentionally conservative. Generic product/gallery images
    are not treated as proof of hidden left/right/back/top geometry.
    """
    text = _reference_semantic_text(url)
    annotation = _reference_annotation(url)
    roles = set(annotation["roles"])

    for role, patterns in _EXPLICIT_VIEW_PATTERNS.items():
        if any(pattern in text for pattern in patterns):
            roles.add(role)

    # Clean product gallery/hero images can safely support front/main identity,
    # but they are NOT sufficient evidence for hidden geometry.
    if any(hint.strip("/").replace("/", "-") in text for hint in _GENERIC_FRONT_PRODUCT_HINTS):
        roles.add(ImportMediaCandidate.VIEW_MAIN)

    # Exact product asset with no scene hints remains usable for Main identity.
    if not any(hint.replace("_", "-") in text for hint in _LIFESTYLE_HINTS):
        if "/gallery/" in unquote(urlparse(str(url or "")).path or "").lower():
            roles.add(ImportMediaCandidate.VIEW_MAIN)

    return roles


def reference_support_for_view(item, view_role):
    """Return auditable support information for one requested generation view."""
    urls = manufacturer_reference_urls(item)
    ranked = rank_reference_urls(urls, view_role) if urls else []

    explicit = []
    semantic_rejections = []
    for url in ranked:
        allowed, reason = semantic_reference_decision(item, url, view_role)
        if allowed:
            explicit.append(url)
        else:
            # Keep an audit record for strict visual roles even when filename/
            # semantic classification never claimed the requested perspective.
            roles = classify_reference_views(url)
            if (
                view_role in _STRICT_VISUAL_REFERENCE_ROLES
                or view_role in roles
            ):
                semantic_rejections.append({"url": url, "reason": reason})

    # Main/hero may use any exact clean product reference.
    if view_role == ImportMediaCandidate.VIEW_MAIN:
        eligible = [
            url for url in ranked
            if ImportMediaCandidate.VIEW_MAIN in classify_reference_views(url)
            or ImportMediaCandidate.VIEW_FRONT in classify_reference_views(url)
        ]
        if not eligible:
            eligible = ranked[:]
        return {
            "supported": bool(eligible),
            "eligible_urls": eligible,
            "all_ranked_urls": ranked,
            "reason": "" if eligible else "No exact official manufacturer product image is available.",
        }

    # Verified lifestyle generation requires an actual visually classified
    # product-in-scene reference. Identity-only references remain available to
    # the separately labelled creative-fallback path.
    if view_role == ImportMediaCandidate.VIEW_LIFESTYLE:
        reason = ""
        if not explicit:
            if semantic_rejections:
                reason = (
                    "Official exact-product images exist, but none were visually "
                    "classified as a real lifestyle/installation scene. Verified "
                    "generation is blocked; use the creative fallback path instead."
                )
            else:
                reason = "No visually role-matched official lifestyle/installation reference was discovered."
        return {
            "supported": bool(explicit),
            "eligible_urls": explicit,
            "all_ranked_urls": ranked,
            "semantic_rejections": semantic_rejections,
            "reason": reason,
        }

    # Hidden/detail physical views are strict: never infer geometry from a front image.
    if view_role in _STRICT_VIEW_ROLES:
        label = _VIEW_ROLE_LABELS.get(view_role, str(view_role))
        if explicit:
            reason = ""
        elif semantic_rejections:
            reason = (
                f"Official manufacturer assets matched {label} keywords, but none passed strict "
                "semantic filtering for a real physical product view. Generation is blocked "
                "before the image provider request."
            )
        else:
            reason = (
                f"No visually role-matched official manufacturer {label} reference was discovered. "
                "Exact-product identity alone is insufficient to verify this factual perspective. "
                "Generation is blocked to prevent invented physical geometry."
            )
        return {
            "supported": bool(explicit),
            "eligible_urls": explicit,
            "all_ranked_urls": ranked,
            "semantic_rejections": semantic_rejections,
            "reason": reason,
        }

    return {
        "supported": bool(ranked),
        "eligible_urls": ranked,
        "all_ranked_urls": ranked,
        "reason": "" if ranked else "No official manufacturer reference image is available.",
    }


def select_generation_reference_urls(item, view_role, *, max_refs=3):
    """Select only references that safely support the requested generation view.

    Raises ReferenceViewHold before any provider request if hidden/detail geometry
    would otherwise have to be invented.
    """
    report = reference_support_for_view(item, view_role)
    if not report["supported"]:
        raise ReferenceViewHold(report["reason"])

    limit = max(1, min(int(max_refs or 3), 5))
    eligible = list(report["eligible_urls"] or [])
    return eligible[:limit]


def reference_support_report(item):
    """Return a compact per-view support report for diagnostics/admin tooling."""
    report = {}
    for role, _label in ImportMediaCandidate.VIEW_CHOICES:
        info = reference_support_for_view(item, role)
        report[role] = {
            "supported": bool(info["supported"]),
            "eligible_urls": list(info["eligible_urls"] or []),
            "semantic_rejections": list(info.get("semantic_rejections") or []),
            "reason": str(info["reason"] or ""),
        }
    return report


def _text_score(url, view_role):
    text = (urlparse(str(url)).path + "?" + urlparse(str(url)).query).lower().replace("_", "-")
    score = 0.0

    if view_role == ImportMediaCandidate.VIEW_LIFESTYLE:
        score += sum(6 for hint in _LIFESTYLE_HINTS if hint in text)
        score -= sum(2 for hint in ("transparent", "cutout", "isolated") if hint in text)
    else:
        score += sum(3 for hint in _PRODUCT_HINTS if hint in text)
        score -= sum(5 for hint in _LIFESTYLE_HINTS if hint in text)

    for hint in _VIEW_HINTS.get(view_role, ()):
        if hint in text:
            score += 7

    if view_role == ImportMediaCandidate.VIEW_PACKAGE:
        score += sum(7 for hint in _PACKAGE_HINTS if hint in text)

    if view_role == ImportMediaCandidate.VIEW_LIFESTYLE:
        score += sum(9 for hint in ("deployment", "meeting-room", "conference-room", "workspace") if hint in text)
        score -= sum(12 for hint in ("active-usb", "cable", "controller", "tap", "adapter", "ethernet-port") if hint in text)

    if view_role == ImportMediaCandidate.VIEW_PORTS:
        score += sum(10 for hint in ("ports", "port-detail", "io-panel", "input-output", "rear-io", "connector") if hint in text)
        score -= sum(15 for hint in ("experience", "deployment", "room-solution", "office", "workspace") if hint in text)

    if "/gallery/" in text:
        score += 14
    if "transparent" in text:
        score += 6
    return score


def _border_pixels(image):
    width, height = image.size
    if width < 2 or height < 2:
        return []
    step_x = max(1, width // 48)
    step_y = max(1, height // 48)
    pixels = []
    for x in range(0, width, step_x):
        pixels.append(image.getpixel((x, 0)))
        pixels.append(image.getpixel((x, height - 1)))
    for y in range(0, height, step_y):
        pixels.append(image.getpixel((0, y)))
        pixels.append(image.getpixel((width - 1, y)))
    return pixels


def _visual_score_from_bytes(data):
    try:
        from PIL import Image, ImageOps, ImageStat
        image = Image.open(BytesIO(data))
        image = ImageOps.exif_transpose(image)
        if getattr(image, "is_animated", False):
            image.seek(0)
        image.thumbnail((360, 360))
        rgba = image.convert("RGBA")

        score = 0.0
        alpha = rgba.getchannel("A")
        alpha_extrema = alpha.getextrema()
        if alpha_extrema and alpha_extrema[0] < 245:
            histogram = alpha.histogram()
            transparent = sum(histogram[:245])
            total = max(1, rgba.width * rgba.height)
            ratio = transparent / total
            if ratio >= 0.02:
                score += 12
            elif ratio > 0:
                score += 5

        rgb = rgba.convert("RGB")
        border = _border_pixels(rgb)
        if border:
            means = [sum(px) / 3.0 for px in border]
            bright_ratio = sum(1 for value in means if value >= 238) / len(means)
            channel_spread = []
            for channel in range(3):
                vals = [px[channel] for px in border]
                mean = sum(vals) / len(vals)
                channel_spread.append(sum(abs(v - mean) for v in vals) / len(vals))
            spread = sum(channel_spread) / 3.0
            if bright_ratio >= 0.82 and spread <= 16:
                score += 9
            elif bright_ratio >= 0.65 and spread <= 28:
                score += 4

        stat = ImageStat.Stat(rgb.resize((64, 64)))
        overall_std = sum(stat.stddev) / 3.0
        if overall_std < 45:
            score += 2
        elif overall_std > 72:
            score -= 2
        return score
    except Exception:
        return 0.0


@lru_cache(maxsize=240)
def _visual_score(url):
    cache_key = "catalog-import-refscore:" + str(abs(hash(url)))
    cached = cache.get(cache_key)
    if cached is not None:
        try:
            return float(cached)
        except (TypeError, ValueError):
            pass
    try:
        result = fetch_binary(
            url,
            timeout=15,
            max_bytes=8 * 1024 * 1024,
            allowed_content_types={
                "image/png", "image/x-png", "image/jpeg", "image/jpg",
                "image/webp", "image/gif", "application/octet-stream",
            },
            user_agent="ArolanaProductImporter/5.0.12.2 (+https://arolana.com)",
            accept_header="image/png,image/jpeg,image/webp,image/gif;q=0.9,*/*;q=0.1",
        )
        value = _visual_score_from_bytes(result.data)
    except (FetchBlocked, UnsafeURL, Exception):
        value = 0.0
    try:
        cache.set(cache_key, value, timeout=60 * 60 * 6)
    except Exception:
        pass
    return value


def rank_reference_urls(urls, view_role, *, visual_score_func=None, visual_probe_limit=12):
    """Rank references without network-probing every image on the page.

    Phase 5.0.5 could spend many minutes visually fetching dozens of irrelevant
    page assets. Text/view relevance is now applied first. Only the strongest
    candidates are visually inspected when using the real network-backed scorer.

    Tests/callers that explicitly provide ``visual_score_func`` still score every
    supplied URL so deterministic ranking behavior is preserved.
    """
    unique = []
    for url in urls or []:
        value = str(url or "").strip()
        if not value:
            continue

        annotation = _reference_annotation(value)
        trusted_deep_reference = bool(
            annotation["verified"] and annotation["roles"]
        )

        # Conventional manufacturer images still need a recognizable image URL.
        # Deep official-support references may be opaque CDN endpoints, but only
        # after the deep acquisition layer has identity-verified the official
        # page, content-probed the embedded asset, and attached an auditable view
        # annotation.
        if not (_looks_like_image_url(value) or trusted_deep_reference):
            continue

        if value not in unique:
            unique.append(value)

    base = []
    for index, url in enumerate(unique):
        base.append((_text_score(url, view_role), -index, url))
    base.sort(reverse=True)

    if visual_score_func is not None:
        probe_urls = {url for _score, _neg_index, url in base}
        scorer = visual_score_func
    else:
        limit = max(0, min(int(visual_probe_limit or 0), 24))
        probe_urls = {url for _score, _neg_index, url in base[:limit]}
        scorer = _visual_score

    ranked = []
    for base_score, neg_index, url in base:
        visual = float(scorer(url) or 0.0) if url in probe_urls else 0.0
        if view_role == ImportMediaCandidate.VIEW_LIFESTYLE:
            final = base_score + (visual * 0.25)
        else:
            final = base_score + visual
        ranked.append((final, base_score, neg_index, url))

    ranked.sort(reverse=True)
    return [url for _final, _base, _neg_index, url in ranked]

def select_reference_urls(item, view_role, *, max_refs=3):
    urls = manufacturer_reference_urls(item)
    if not urls:
        return []
    ranked = rank_reference_urls(urls, view_role)
    limit = max(1, min(int(max_refs or 3), 5))
    return ranked[:limit]
