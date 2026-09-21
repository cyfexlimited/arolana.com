"""Phase 5.3.5 — Conservative semantic classifier for official references.

Purpose
-------
Arolana can acquire many exact-product official manufacturer images, but the
image may remain unusable for a strict media slot if its URL was not already
annotated as Front/Back/Ports/Package/Side/Top/etc.

This service classifies only AUTHORITATIVE MANUFACTURER evidence already tied to
an exact-product official page. It does not classify retailer images and does not
turn ambiguous assets into factual evidence.

Classification uses auditable text that already accompanies the official asset:
- role_hint from official-media discovery
- alt/caption/title/context text
- official image URL/file name
- official source page URL
- existing Arolana reference annotation

It intentionally does NOT infer hidden geometry from a generic product photo.
"""

from __future__ import annotations

import re
from collections import Counter
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from catalog_imports.models import ImportEvidence, ImportMediaCandidate


CLASSIFIER_VERSION = "5.3.5"

_ROLE_ORDER = (
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
    ImportMediaCandidate.VIEW_MAIN,
)

_ROLE_ALIASES = {
    "main": ImportMediaCandidate.VIEW_MAIN,
    "hero": ImportMediaCandidate.VIEW_MAIN,
    "product": ImportMediaCandidate.VIEW_MAIN,
    "front": ImportMediaCandidate.VIEW_FRONT,
    "left": ImportMediaCandidate.VIEW_LEFT,
    "left_angle": ImportMediaCandidate.VIEW_LEFT,
    "left-angle": ImportMediaCandidate.VIEW_LEFT,
    "right": ImportMediaCandidate.VIEW_RIGHT,
    "right_angle": ImportMediaCandidate.VIEW_RIGHT,
    "right-angle": ImportMediaCandidate.VIEW_RIGHT,
    "side": ImportMediaCandidate.VIEW_SIDE,
    "profile": ImportMediaCandidate.VIEW_SIDE,
    "back": ImportMediaCandidate.VIEW_BACK,
    "rear": ImportMediaCandidate.VIEW_BACK,
    "top": ImportMediaCandidate.VIEW_TOP,
    "top_detail": ImportMediaCandidate.VIEW_TOP,
    "top-detail": ImportMediaCandidate.VIEW_TOP,
    "ports": ImportMediaCandidate.VIEW_PORTS,
    "ports_detail": ImportMediaCandidate.VIEW_PORTS,
    "ports-detail": ImportMediaCandidate.VIEW_PORTS,
    "controls": ImportMediaCandidate.VIEW_PORTS,
    "technical": ImportMediaCandidate.VIEW_PORTS,
    "package": ImportMediaCandidate.VIEW_PACKAGE,
    "package_contents": ImportMediaCandidate.VIEW_PACKAGE,
    "package-contents": ImportMediaCandidate.VIEW_PACKAGE,
    "lifestyle": ImportMediaCandidate.VIEW_LIFESTYLE,
    "scene": ImportMediaCandidate.VIEW_LIFESTYLE,
    "detail": ImportMediaCandidate.VIEW_CLOSEUP,
    "closeup": ImportMediaCandidate.VIEW_CLOSEUP,
    "close-up": ImportMediaCandidate.VIEW_CLOSEUP,
}

# Strong phrases. A match is accepted because the containing evidence is already
# exact-product official manufacturer evidence.
_ROLE_PATTERNS = {
    ImportMediaCandidate.VIEW_FRONT: (
        "front view", "front-view", "frontview", "straight on", "straight-on",
        "head on", "head-on",
    ),
    ImportMediaCandidate.VIEW_LEFT: (
        "left angle", "left-angle", "left view", "left-view",
        "left three quarter", "left three-quarter", "3/4 left", "three quarter left",
    ),
    ImportMediaCandidate.VIEW_RIGHT: (
        "right angle", "right-angle", "right view", "right-view",
        "right three quarter", "right three-quarter", "3/4 right", "three quarter right",
    ),
    ImportMediaCandidate.VIEW_SIDE: (
        "side view", "side-view", "side profile", "side-profile",
        "profile view", "profile-view", "lateral view",
    ),
    ImportMediaCandidate.VIEW_BACK: (
        "rear view", "rear-view", "back view", "back-view",
        "rear panel", "rear-panel",
    ),
    ImportMediaCandidate.VIEW_TOP: (
        "top view", "top-view", "overhead view", "overhead-view",
        "top detail", "top-detail", "view from above",
    ),
    ImportMediaCandidate.VIEW_PORTS: (
        "ports and controls", "ports & controls", "port panel", "port-panel",
        "i/o panel", "i-o panel", "io panel", "input output",
        "input/output", "connectors", "connector panel", "terminal panel",
        "xlr", "12g-sdi", "3g-sdi", "sdi out", "sdi input", "hdmi out",
        "hdmi input", "usb-c", "usb c", "ethernet", "rj45", "rj-45",
        "media slots", "card slots", "control panel", "button panel",
        "audio inputs", "audio input", "timecode", "genlock",
    ),
    ImportMediaCandidate.VIEW_PACKAGE: (
        "what's in the box", "whats in the box", "what is in the box",
        "in the box", "in-the-box", "box contents", "box-contents",
        "package contents", "package-contents", "included accessories",
        "included items", "retail box", "packaging contents",
    ),
    ImportMediaCandidate.VIEW_LIFESTYLE: (
        "in use", "in-use", "camera operator", "filming", "shooting",
        "production set", "broadcast studio", "news studio", "live production",
        "on location", "event production", "installed", "installation",
    ),
    ImportMediaCandidate.VIEW_CLOSEUP: (
        "close up", "close-up", "closeup", "macro view", "macro-view",
        "detail view", "detail-view", "lens detail", "viewfinder detail",
        "handle detail", "control detail", "button detail",
    ),
}

_SCENE_TERMS = (
    "lifestyle", "in use", "in-use", "operator", "filming", "shooting",
    "production", "studio", "event", "location", "installed", "installation",
)
_PACKAGE_TERMS = (
    "box contents", "package contents", "what's in the box", "whats in the box",
    "in the box", "included accessories", "retail box", "packaging",
)
_MARKETING_GRAPHIC_TERMS = (
    "banner", "promo", "promotion", "feature graphic", "infographic",
    "campaign", "poster", "logo", "badge", "sensor logo",
)


def _normalize(value):
    text = str(value or "").lower()
    text = text.replace("_", " ").replace("/", " ").replace("\\", " ")
    text = re.sub(r"[-–—]+", "-", text)
    text = re.sub(r"[^a-z0-9+&./' -]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _entry_url(entry):
    if isinstance(entry, str):
        return str(entry or "").strip()
    if isinstance(entry, dict):
        return str(
            entry.get("reference_url")
            or entry.get("url")
            or entry.get("src")
            or ""
        ).strip()
    return ""


def _existing_annotation(url):
    try:
        fragment = parse_qs(
            urlparse(str(url or "")).fragment,
            keep_blank_values=True,
        )
    except Exception:
        return {
            "verified": False,
            "roles": set(),
            "kind": "",
            "source": "",
        }

    verified = str(
        (fragment.get("arolana_verified") or [""])[0]
    ).lower() in {"1", "true", "yes"}

    roles = set()
    for raw in fragment.get("arolana_view", []):
        roles.update(
            value.strip()
            for value in str(raw or "").split(",")
            if value.strip()
        )

    return {
        "verified": verified,
        "roles": roles,
        "kind": str((fragment.get("arolana_kind") or [""])[0] or "").strip(),
        "source": str((fragment.get("arolana_source") or [""])[0] or "").strip(),
    }


def _annotate_url(url, *, roles, kind, source):
    """Add/merge Arolana metadata in the URL fragment.

    URL fragments are never sent to the manufacturer/CDN server.
    """
    parsed = urlparse(str(url or ""))
    values = parse_qs(parsed.fragment, keep_blank_values=True)

    current = set()
    for raw in values.get("arolana_view", []):
        current.update(
            value.strip()
            for value in str(raw or "").split(",")
            if value.strip()
        )
    current.update(str(role or "").strip() for role in roles if str(role or "").strip())

    values["arolana_verified"] = ["1"]
    values["arolana_view"] = [",".join(
        role for role in _ROLE_ORDER if role in current
    )]
    values["arolana_kind"] = [str(kind or "physical")]
    values["arolana_source"] = [str(source or "official-semantic-classifier")]

    fragment = urlencode(
        [(key, value) for key, rows in values.items() for value in rows]
    )
    return urlunparse(parsed._replace(fragment=fragment))


def _role_hint_roles(entry):
    if not isinstance(entry, dict):
        return set()

    raw_values = []
    for key in ("role_hint", "role", "view_role", "semantic_role"):
        value = entry.get(key)
        if isinstance(value, (list, tuple, set)):
            raw_values.extend(value)
        elif value:
            raw_values.extend(
                re.split(r"[,;/|]+", str(value))
            )

    roles = set()
    for raw in raw_values:
        normalized = _normalize(raw).replace(" ", "_")
        if normalized in _ROLE_ALIASES:
            roles.add(_ROLE_ALIASES[normalized])
        normalized_dash = normalized.replace("_", "-")
        if normalized_dash in _ROLE_ALIASES:
            roles.add(_ROLE_ALIASES[normalized_dash])
    return roles


def _semantic_text(entry):
    url = _entry_url(entry)
    values = [url]

    if isinstance(entry, dict):
        for key in (
            "role_hint",
            "alt_text",
            "alt",
            "title",
            "caption",
            "semantic_context",
            "context",
            "source_page_url",
            "kind",
        ):
            value = entry.get(key)
            if isinstance(value, (list, tuple, set)):
                values.extend(str(row or "") for row in value)
            elif value:
                values.append(str(value))

    return _normalize(" ".join(values))


def classify_image_entry(entry):
    """Return a conservative semantic classification for one official image.

    The caller is responsible for ensuring the entry came from authoritative
    exact-product manufacturer evidence.
    """
    url = _entry_url(entry)
    existing = _existing_annotation(url)
    text = _semantic_text(entry)
    roles = set(existing["roles"])
    reasons = []

    hint_roles = _role_hint_roles(entry)
    roles.update(hint_roles)
    if hint_roles:
        reasons.append("explicit role_hint")

    for role, patterns in _ROLE_PATTERNS.items():
        matches = [pattern for pattern in patterns if pattern in text]
        if matches:
            roles.add(role)
            reasons.append(
                f"{role}: " + ", ".join(matches[:3])
            )

    # Conservative conflict handling.
    if (
        ImportMediaCandidate.VIEW_LEFT in roles
        and ImportMediaCandidate.VIEW_RIGHT in roles
        and not (
            ImportMediaCandidate.VIEW_LEFT in hint_roles
            or ImportMediaCandidate.VIEW_RIGHT in hint_roles
        )
    ):
        roles.discard(ImportMediaCandidate.VIEW_LEFT)
        roles.discard(ImportMediaCandidate.VIEW_RIGHT)

    if (
        ImportMediaCandidate.VIEW_FRONT in roles
        and ImportMediaCandidate.VIEW_BACK in roles
        and not (
            ImportMediaCandidate.VIEW_FRONT in hint_roles
            or ImportMediaCandidate.VIEW_BACK in hint_roles
        )
    ):
        roles.discard(ImportMediaCandidate.VIEW_FRONT)
        roles.discard(ImportMediaCandidate.VIEW_BACK)

    # Generic marketing graphics must not become proof of physical geometry
    # unless the role was already explicitly supplied by a trusted upstream
    # classifier/provenance record.
    marketing_graphic = any(term in text for term in _MARKETING_GRAPHIC_TERMS)
    if marketing_graphic and not hint_roles and not existing["roles"]:
        roles.difference_update({
            ImportMediaCandidate.VIEW_FRONT,
            ImportMediaCandidate.VIEW_LEFT,
            ImportMediaCandidate.VIEW_RIGHT,
            ImportMediaCandidate.VIEW_SIDE,
            ImportMediaCandidate.VIEW_BACK,
            ImportMediaCandidate.VIEW_TOP,
            ImportMediaCandidate.VIEW_PORTS,
            ImportMediaCandidate.VIEW_PACKAGE,
            ImportMediaCandidate.VIEW_CLOSEUP,
        })

    # Scene/package images should not silently become generic physical geometry.
    if any(term in text for term in _SCENE_TERMS):
        roles.add(ImportMediaCandidate.VIEW_LIFESTYLE)
    if any(term in text for term in _PACKAGE_TERMS):
        roles.add(ImportMediaCandidate.VIEW_PACKAGE)

    # A generic official product image can support main identity, but not hidden
    # geometry. We only add main when no scene/package-only signal dominates.
    if not roles and url:
        clean_product_hint = any(
            token in text
            for token in (
                "product image", "product-image", "gallery",
                "hero", "beauty", "product photo", "product-photo",
            )
        )
        if clean_product_hint:
            roles.add(ImportMediaCandidate.VIEW_MAIN)
            reasons.append("generic official product/gallery image")

    if not roles:
        return {
            "classified": False,
            "roles": [],
            "kind": "",
            "reason": "No strong semantic role signal.",
            "source_text": text[:1000],
        }

    if ImportMediaCandidate.VIEW_PACKAGE in roles:
        kind = "package"
    elif ImportMediaCandidate.VIEW_LIFESTYLE in roles:
        kind = "scene"
    else:
        kind = "physical"

    return {
        "classified": True,
        "roles": [
            role for role in _ROLE_ORDER if role in roles
        ],
        "kind": kind,
        "reason": "; ".join(reasons)[:1000],
        "source_text": text[:1000],
    }


def classify_payload_images(payload):
    """Annotate image entries inside one exact-product manufacturer payload."""
    payload = dict(payload or {})
    images = list(payload.get("images") or [])
    output = []

    role_counts = Counter()
    classified = 0
    changed = 0

    for raw in images:
        if isinstance(raw, str):
            entry = {
                "reference_url": raw,
                "url": raw,
            }
        elif isinstance(raw, dict):
            entry = dict(raw)
        else:
            output.append(raw)
            continue

        url = _entry_url(entry)
        result = classify_image_entry(entry)

        entry["semantic_classifier"] = {
            "version": CLASSIFIER_VERSION,
            "classified": bool(result["classified"]),
            "roles": list(result["roles"]),
            "kind": result["kind"],
            "reason": result["reason"],
        }

        if result["classified"] and url:
            classified += 1
            for role in result["roles"]:
                role_counts[role] += 1

            annotated = _annotate_url(
                url,
                roles=result["roles"],
                kind=result["kind"],
                source="official-semantic-classifier",
            )
            if annotated != url:
                changed += 1
            entry["reference_url"] = annotated
            entry["url"] = annotated
            entry["semantic_roles"] = list(result["roles"])
            entry["semantic_kind"] = result["kind"]

        output.append(entry)

    payload["images"] = output
    return payload, {
        "version": CLASSIFIER_VERSION,
        "images_seen": len(images),
        "images_classified": classified,
        "images_annotated_or_updated": changed,
        "role_counts": dict(role_counts),
    }


def classify_authoritative_evidence_images(item):
    """Persist semantic annotations across authoritative manufacturer evidence."""
    evidences = (
        item.evidence_records
        .filter(
            role=ImportEvidence.ROLE_MANUFACTURER,
            is_authoritative=True,
            status=ImportEvidence.STATUS_FETCHED,
        )
        .order_by("id")
    )

    aggregate = Counter()
    evidence_rows = []
    total_seen = 0
    total_classified = 0
    total_changed = 0

    for evidence in evidences:
        payload, summary = classify_payload_images(
            evidence.extracted_payload or {}
        )
        total_seen += int(summary["images_seen"])
        total_classified += int(summary["images_classified"])
        total_changed += int(summary["images_annotated_or_updated"])
        aggregate.update(summary["role_counts"])

        if payload != (evidence.extracted_payload or {}):
            evidence.extracted_payload = payload
            evidence.notes = (
                (evidence.notes or "").strip()
                + "\n"
                + f"Phase {CLASSIFIER_VERSION}: official image semantics classified "
                  f"({summary['images_classified']}/{summary['images_seen']} images)."
            ).strip()
            evidence.save()

        evidence_rows.append({
            "evidence_id": evidence.pk,
            "url": evidence.url,
            **summary,
        })

    return {
        "version": CLASSIFIER_VERSION,
        "evidence_records": len(evidence_rows),
        "images_seen": total_seen,
        "images_classified": total_classified,
        "images_annotated_or_updated": total_changed,
        "role_counts": dict(aggregate),
        "records": evidence_rows,
        "safety": {
            "authoritative_manufacturer_evidence_only": True,
            "generic_hidden_geometry_inference": False,
            "retailer_images_classified": False,
        },
    }
