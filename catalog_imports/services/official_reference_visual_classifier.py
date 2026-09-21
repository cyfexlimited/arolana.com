"""Phase 5.3.6 — Visual classification of official manufacturer references.

Why
---
Text/URL semantics are sometimes insufficient. A manufacturer page can expose
many exact-product images whose filenames/alt text do not say "side", "ports",
"package", etc. This service inspects the ACTUAL PIXELS of authoritative
manufacturer images and classifies their visible view.

Trust boundary
--------------
- Only images already stored in authoritative MANUFACTURER evidence are eligible.
- Retailer/source images are never sent through this classifier.
- Classification selects a view; it does not redraw or invent geometry.
- Geometry-sensitive generation still uses the existing reference-preserving
  renderer.
- High-confidence visual classification is required.
- Ports/package require additional explicit visual booleans.
- Marketing graphics do not unlock hidden-geometry roles.
- Results are cached in evidence to avoid repeated API cost.
- Human review remains mandatory.
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import urllib.error
import urllib.request
from collections import Counter
from typing import Dict, List
from urllib.parse import urlparse, urlunparse

from django.conf import settings

from catalog_imports.models import ImportEvidence, ImportMediaCandidate
from catalog_imports.services.deep_official_references import annotate_reference_url
from catalog_imports.services.http_fetch import _build_ssl_context, fetch_binary
from catalog_imports.services.official_reference_semantics import _existing_annotation


CLASSIFIER_VERSION = "5.3.6"
DEFAULT_ENDPOINT = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-5.6-luna"

ALLOWED_ROLES = {
    ImportMediaCandidate.VIEW_MAIN,
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
    "unknown",
}

GEOMETRY_ROLES = {
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

ROLE_THRESHOLDS = {
    ImportMediaCandidate.VIEW_MAIN: 0.90,
    ImportMediaCandidate.VIEW_FRONT: 0.94,
    ImportMediaCandidate.VIEW_LEFT: 0.95,
    ImportMediaCandidate.VIEW_RIGHT: 0.95,
    ImportMediaCandidate.VIEW_SIDE: 0.95,
    ImportMediaCandidate.VIEW_BACK: 0.94,
    ImportMediaCandidate.VIEW_TOP: 0.95,
    ImportMediaCandidate.VIEW_PORTS: 0.97,
    ImportMediaCandidate.VIEW_PACKAGE: 0.97,
    ImportMediaCandidate.VIEW_LIFESTYLE: 0.92,
    ImportMediaCandidate.VIEW_CLOSEUP: 0.95,
}


class VisualClassifierUnavailable(RuntimeError):
    pass


def _setting(name, default=None):
    value = getattr(settings, name, None)
    if value not in (None, ""):
        return value
    return os.environ.get(name, default)


def _base_url(url):
    parsed = urlparse(str(url or ""))
    return urlunparse(parsed._replace(fragment=""))


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


def _response_output_text(data: Dict) -> str:
    chunks = []
    for item in data.get("output", []) or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for content in item.get("content", []) or []:
            if isinstance(content, dict) and content.get("type") == "output_text":
                value = str(content.get("text") or "")
                if value:
                    chunks.append(value)
    return "\n".join(chunks).strip()


def _parse_json(text):
    value = str(text or "").strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.I)
        value = re.sub(r"\s*```$", "", value)
    start = value.find("{")
    end = value.rfind("}")
    if start >= 0 and end >= start:
        value = value[start:end + 1]
    data = json.loads(value)
    if not isinstance(data, dict):
        raise ValueError("Visual classifier response must be a JSON object.")
    return data


def _fetch_and_prepare_image(url):
    fetched = fetch_binary(
        _base_url(url),
        timeout=20,
        max_bytes=20 * 1024 * 1024,
        user_agent="ArolanaProductImporter/5.3.6 (+https://arolana.com)",
        allowed_content_types={
            "image/jpeg",
            "image/png",
            "image/webp",
            "image/gif",
            "image/avif",
            "application/octet-stream",
        },
        accept_header="image/avif,image/webp,image/png,image/jpeg,image/gif,*/*;q=0.1",
    )

    from PIL import Image

    image = Image.open(io.BytesIO(fetched.data))
    if getattr(image, "n_frames", 1) > 1:
        image.seek(0)
    image = image.convert("RGB")
    image.thumbnail((768, 768))

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=82, optimize=True)
    data = base64.b64encode(buffer.getvalue()).decode("ascii")
    return "data:image/jpeg;base64," + data


def _provider_request(*, item, rows):
    api_key = str(_setting("OPENAI_API_KEY", "") or "").strip()
    if not api_key:
        raise VisualClassifierUnavailable("OPENAI_API_KEY is not configured.")

    endpoint = str(
        _setting("CATALOG_IMPORT_VISUAL_CLASSIFIER_ENDPOINT", DEFAULT_ENDPOINT)
        or DEFAULT_ENDPOINT
    ).strip()
    model = str(
        _setting("CATALOG_IMPORT_VISUAL_CLASSIFIER_MODEL", DEFAULT_MODEL)
        or DEFAULT_MODEL
    ).strip()
    timeout = int(
        _setting("CATALOG_IMPORT_VISUAL_CLASSIFIER_TIMEOUT_SECONDS", "60") or 60
    )

    normalized = getattr(item, "normalized_payload", None) or {}
    brand = str(
        normalized.get("brand")
        or normalized.get("manufacturer")
        or ""
    ).strip()
    model_name = str(
        normalized.get("model")
        or normalized.get("manufacturer_sku")
        or ""
    ).strip()
    product_name = str(normalized.get("name") or "").strip()

    indices = [row["index"] for row in rows]

    prompt = f"""
You are Arolana's conservative OFFICIAL PRODUCT IMAGE VIEW CLASSIFIER.

These images have already passed Arolana's provenance checks as authoritative
manufacturer evidence for the exact product below. Your job is ONLY to classify
what is visibly shown. Never infer hidden sides, ports, package contents, or
accessories that are not clearly visible.

Product:
- Brand: {brand or "(unknown)"}
- Product: {product_name or "(unknown)"}
- Model/SKU: {model_name or "(unknown)"}

The following images are supplied in exact order for indices:
{indices}

For each image return:
- index
- exact_product_visible: boolean
- primary_role: one of:
  main, front, left_angle, right_angle, side, back, top_detail,
  ports_detail, package_contents, lifestyle, closeup, unknown
- confidence: 0.0 to 1.0
- view_is_clear: boolean
- marketing_graphic: boolean
- ports_visible: boolean
- package_visible: boolean
- package_contents_visible: boolean
- reason: short factual visual explanation

Strict rules:
1. "front" means a genuinely frontal product view, not just a photo that includes
   the front somewhere in an angle.
2. left/right/side/back/top require the corresponding physical perspective to be
   clearly visible.
3. ports_detail requires actual connector/port/control geometry visibly readable
   enough to be useful as a factual technical reference.
4. package_contents requires real package/box or included contents visibly shown.
5. closeup requires a real product detail close-up, not a generic crop of a banner.
6. lifestyle means the actual product visibly used/installed in a real scene.
7. If it is a logo, sensor badge, marketing banner, infographic, unrelated
   accessory, or insufficiently clear, use unknown.
8. Do not guess. When uncertain, use unknown or a lower confidence.

Return JSON ONLY:
{{
  "results": [
    {{
      "index": 1,
      "exact_product_visible": true,
      "primary_role": "back",
      "confidence": 0.98,
      "view_is_clear": true,
      "marketing_graphic": false,
      "ports_visible": true,
      "package_visible": false,
      "package_contents_visible": false,
      "reason": "Clear rear view with connector panel visible."
    }}
  ]
}}
""".strip()

    content = [{"type": "input_text", "text": prompt}]
    for row in rows:
        content.append({
            "type": "input_image",
            "image_url": row["data_url"],
            "detail": "high",
        })

    payload = {
        "model": model,
        "reasoning": {"effort": "low"},
        "input": [{
            "role": "user",
            "content": content,
        }],
    }

    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "ArolanaProductImporter/5.3.6",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=timeout,
            context=_build_ssl_context(),
        ) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            detail = ""
        raise VisualClassifierUnavailable(
            f"Visual classifier returned HTTP {exc.code}. {detail}".strip()
        ) from exc
    except Exception as exc:
        raise VisualClassifierUnavailable(
            f"Visual classifier request failed: {exc}"
        ) from exc

    return _parse_json(_response_output_text(data)), model


def _safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _accepted_roles(result):
    role = str(result.get("primary_role") or "unknown").strip()
    if role not in ALLOWED_ROLES or role == "unknown":
        return []

    if not bool(result.get("exact_product_visible")):
        return []
    if not bool(result.get("view_is_clear")):
        return []

    confidence = _safe_float(result.get("confidence"))
    threshold = ROLE_THRESHOLDS.get(role, 0.99)
    if confidence < threshold:
        return []

    # Generic marketing graphics are not sufficient evidence for factual
    # geometry. Lifestyle also needs a real scene, not a banner.
    if bool(result.get("marketing_graphic")):
        return []

    if role == ImportMediaCandidate.VIEW_PORTS and not bool(
        result.get("ports_visible")
    ):
        return []

    if role == ImportMediaCandidate.VIEW_PACKAGE and not (
        bool(result.get("package_visible"))
        or bool(result.get("package_contents_visible"))
    ):
        return []

    roles = [role]

    # A clear rear/side/etc. image may also be a valid ports detail only when
    # the model explicitly confirms real ports are visibly useful and the
    # overall confidence is extremely high.
    if (
        role in {
            ImportMediaCandidate.VIEW_BACK,
            ImportMediaCandidate.VIEW_SIDE,
            ImportMediaCandidate.VIEW_LEFT,
            ImportMediaCandidate.VIEW_RIGHT,
            ImportMediaCandidate.VIEW_CLOSEUP,
        }
        and bool(result.get("ports_visible"))
        and confidence >= ROLE_THRESHOLDS[ImportMediaCandidate.VIEW_PORTS]
    ):
        roles.append(ImportMediaCandidate.VIEW_PORTS)

    return roles


def _kind_for_roles(roles):
    if ImportMediaCandidate.VIEW_PACKAGE in roles:
        return "package"
    if ImportMediaCandidate.VIEW_LIFESTYLE in roles:
        return "scene"
    return "physical"


def _already_done(entry):
    if not isinstance(entry, dict):
        return False
    data = entry.get("visual_classifier") or {}
    return str(data.get("version") or "") == CLASSIFIER_VERSION


def classify_authoritative_evidence_images_visual(item):
    enabled = str(
        _setting("CATALOG_IMPORT_VISUAL_CLASSIFIER_ENABLED", "1") or "1"
    ).lower()
    if enabled in {"0", "false", "no", "off"}:
        return {
            "status": "disabled",
            "version": CLASSIFIER_VERSION,
        }

    max_images = int(
        _setting("CATALOG_IMPORT_VISUAL_CLASSIFIER_MAX_IMAGES", "30") or 30
    )
    batch_size = int(
        _setting("CATALOG_IMPORT_VISUAL_CLASSIFIER_BATCH_SIZE", "5") or 5
    )
    max_images = max(1, min(max_images, 60))
    batch_size = max(1, min(batch_size, 8))

    evidences = list(
        item.evidence_records.filter(
            role=ImportEvidence.ROLE_MANUFACTURER,
            is_authoritative=True,
            status=ImportEvidence.STATUS_FETCHED,
        ).order_by("id")
    )

    # One unique URL may appear in several evidence records. Classify it once,
    # then apply the result to every authoritative occurrence.
    occurrences = {}
    total_entries = 0
    for evidence in evidences:
        images = list((evidence.extracted_payload or {}).get("images") or [])
        for position, entry in enumerate(images):
            if not isinstance(entry, dict):
                continue
            total_entries += 1
            url = _entry_url(entry)
            if not url:
                continue
            key = _base_url(url)
            if not key:
                continue
            occurrences.setdefault(key, []).append((evidence, position, entry))

    candidates = []
    cached_count = 0
    for key, rows in occurrences.items():
        if all(_already_done(entry) for _evidence, _position, entry in rows):
            cached_count += 1
            continue

        # Prefer entries without strong non-main semantics. Main-only images are
        # still eligible because visual analysis may reveal side/back/ports.
        first_entry = rows[0][2]
        existing_roles = set(first_entry.get("semantic_roles") or [])
        priority = 0 if not existing_roles else 1
        if existing_roles - {ImportMediaCandidate.VIEW_MAIN}:
            priority = 2

        candidates.append({
            "key": key,
            "rows": rows,
            "priority": priority,
        })

    candidates.sort(key=lambda row: (row["priority"], row["key"]))
    selected = candidates[:max_images]

    prepared = []
    fetch_failures = []
    for sequence, candidate in enumerate(selected, 1):
        try:
            data_url = _fetch_and_prepare_image(candidate["key"])
        except Exception as exc:
            fetch_failures.append({
                "url": candidate["key"],
                "error": str(exc),
            })
            # Cache a fetch failure for this classifier version so repeated
            # refreshes do not hammer the same blocked/broken image.
            for evidence, position, entry in candidate["rows"]:
                entry["visual_classifier"] = {
                    "version": CLASSIFIER_VERSION,
                    "status": "fetch_failed",
                    "error": str(exc)[:500],
                    "accepted_roles": [],
                }
            continue

        prepared.append({
            "index": sequence,
            "candidate": candidate,
            "data_url": data_url,
        })

    provider_model = ""
    provider_failures = []
    classified_unique = 0
    role_counts = Counter()
    accepted_unique = 0

    for start in range(0, len(prepared), batch_size):
        batch = prepared[start:start + batch_size]
        # Re-index within each batch because image inputs are supplied only for
        # this request.
        request_rows = []
        index_map = {}
        for local_index, row in enumerate(batch, 1):
            request_rows.append({
                "index": local_index,
                "data_url": row["data_url"],
            })
            index_map[local_index] = row

        try:
            response, provider_model = _provider_request(
                item=item,
                rows=request_rows,
            )
        except Exception as exc:
            provider_failures.append(str(exc))
            for row in batch:
                for evidence, position, entry in row["candidate"]["rows"]:
                    entry["visual_classifier"] = {
                        "version": CLASSIFIER_VERSION,
                        "status": "provider_failed",
                        "error": str(exc)[:500],
                        "accepted_roles": [],
                    }
            continue

        returned = {
            int(result.get("index")): result
            for result in response.get("results", []) or []
            if isinstance(result, dict)
            and str(result.get("index") or "").isdigit()
        }

        for local_index, row in index_map.items():
            result = returned.get(local_index) or {
                "index": local_index,
                "primary_role": "unknown",
                "confidence": 0,
                "view_is_clear": False,
                "exact_product_visible": False,
                "marketing_graphic": False,
                "reason": "No result returned for image.",
            }

            classified_unique += 1
            accepted = _accepted_roles(result)
            if accepted:
                accepted_unique += 1
                role_counts.update(accepted)

            for evidence, position, entry in row["candidate"]["rows"]:
                current_url = _entry_url(entry)

                # Pixel classification is an independent trust layer. Never
                # promote semantic/filename roles into visual proof. Otherwise
                # a URL semantically tagged "front" could hitchhike on a visual
                # "outsole/closeup" classification and incorrectly unlock a
                # factual Front generation.
                visual_roles = set(accepted)

                if accepted:
                    annotated = annotate_reference_url(
                        current_url,
                        roles=visual_roles,
                        kind=_kind_for_roles(visual_roles),
                        source="official-visual-classifier",
                    )
                    entry["reference_url"] = annotated
                    entry["url"] = annotated
                    entry["visual_roles"] = sorted(visual_roles)
                    entry["visual_kind"] = _kind_for_roles(visual_roles)

                entry["visual_classifier"] = {
                    "version": CLASSIFIER_VERSION,
                    "status": "classified",
                    "provider_model": provider_model,
                    "primary_role": str(
                        result.get("primary_role") or "unknown"
                    ),
                    "confidence": _safe_float(result.get("confidence")),
                    "exact_product_visible": bool(
                        result.get("exact_product_visible")
                    ),
                    "view_is_clear": bool(result.get("view_is_clear")),
                    "marketing_graphic": bool(
                        result.get("marketing_graphic")
                    ),
                    "ports_visible": bool(result.get("ports_visible")),
                    "package_visible": bool(result.get("package_visible")),
                    "package_contents_visible": bool(
                        result.get("package_contents_visible")
                    ),
                    "accepted_roles": list(accepted),
                    "reason": str(result.get("reason") or "")[:1000],
                }

    # Persist modified payloads.
    for evidence in evidences:
        payload = dict(evidence.extracted_payload or {})
        images = list(payload.get("images") or [])
        changed = False

        for key, rows in occurrences.items():
            for row_evidence, position, entry in rows:
                if row_evidence.pk != evidence.pk:
                    continue
                if position < len(images) and images[position] != entry:
                    images[position] = entry
                    changed = True

        if changed:
            payload["images"] = images
            evidence.extracted_payload = payload
            evidence.notes = (
                (evidence.notes or "").strip()
                + "\n"
                + f"Phase {CLASSIFIER_VERSION}: official image pixels visually "
                  "classified for factual media roles."
            ).strip()
            evidence.save()

    remaining = max(0, len(candidates) - len(selected))

    return {
        "status": (
            "partial"
            if remaining
            else "completed"
        ),
        "version": CLASSIFIER_VERSION,
        "provider_model": provider_model,
        "authoritative_evidence_only": True,
        "total_image_entries": total_entries,
        "unique_official_images": len(occurrences),
        "cached_unique_images": cached_count,
        "selected_unique_images": len(selected),
        "visually_classified_unique_images": classified_unique,
        "accepted_unique_images": accepted_unique,
        "role_counts": dict(role_counts),
        "fetch_failures": fetch_failures[:20],
        "provider_failures": provider_failures[:10],
        "remaining_unclassified_unique_images": remaining,
        "limits": {
            "max_images_per_refresh": max_images,
            "batch_size": batch_size,
        },
        "safety": {
            "retailer_images": False,
            "view_only_no_redraw": True,
            "high_confidence_required": True,
            "ports_require_visible_ports": True,
            "package_requires_visible_package": True,
            "marketing_graphics_unlock_geometry": False,
            "human_review_required": True,
        },
    }
