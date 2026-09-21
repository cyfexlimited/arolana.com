import os

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from catalog_imports.media_providers import get_provider
from catalog_imports.media_providers.base import MediaProviderError
from catalog_imports.models import ImportMediaCandidate

from .media_generation import MediaGenerationError, _ensure_item_ready
from .media_profiles import (
    POLICY_ACTUAL_ONLY,
    POLICY_CREATIVE,
    candidate_creative_allowed,
    candidate_display_label,
    candidate_generation_policy,
    candidate_metadata,
    candidate_representation_rule,
)
from .media_reference_trace import record_reference_trace
from .media_references import (
    classify_reference_views,
    manufacturer_reference_urls,
    rank_reference_urls,
    reference_support_for_view,
)
from .media_storage import ReviewStorageError, review_storage_alias, save_review_asset
from .media_validation import duplicate_hash_exists, validate_materialized_candidate


class CreativeFallbackError(RuntimeError):
    pass


CREATIVE_FALLBACK_VIEWS = {
    ImportMediaCandidate.VIEW_LEFT,
    ImportMediaCandidate.VIEW_RIGHT,
    ImportMediaCandidate.VIEW_SIDE,
    ImportMediaCandidate.VIEW_BACK,
    ImportMediaCandidate.VIEW_TOP,
    ImportMediaCandidate.VIEW_PACKAGE,
    ImportMediaCandidate.VIEW_CLOSEUP,
}


def _config(name, default):
    value = getattr(settings, name, None)
    if value not in (None, ""):
        return value
    value = os.environ.get(name)
    if value not in (None, ""):
        return value
    try:
        from decouple import config
        return config(name, default=default)
    except Exception:
        return default


def is_creative_fallback_candidate(candidate):
    response = getattr(candidate, "provider_response", None) or {}
    return bool(response.get("_arolana_creative_fallback"))


def creative_fallback_reference_urls(item, *, max_refs=3):
    """Return clean exact-product identity anchors, not target-view evidence."""
    urls = manufacturer_reference_urls(item)
    if not urls:
        return []

    ranked = rank_reference_urls(
        urls,
        ImportMediaCandidate.VIEW_MAIN,
    )

    clean = []
    for url in ranked:
        roles = classify_reference_views(url)
        if (
            ImportMediaCandidate.VIEW_MAIN in roles
            or ImportMediaCandidate.VIEW_FRONT in roles
        ):
            clean.append(url)

    if not clean:
        clean = ranked[:]

    limit = max(1, min(int(max_refs or 3), 5))
    return clean[:limit]


def _verified_web_text_grounding(item):
    """Return trusted manufacturer text facts captured by Phase 5.2.

    This is NOT visual verification. It is used only for category-profile slots
    that are intentionally creative/support media.
    """
    report = getattr(item, "verification_report", None) or {}
    fallback = report.get("manufacturer_web_fallback") or {}
    if not isinstance(fallback, dict):
        return {}

    identity = fallback.get("identity") or {}
    payload = fallback.get("payload") or {}

    if not fallback.get("verified"):
        return {}
    if not isinstance(identity, dict) or not identity.get("passed"):
        return {}
    if not isinstance(payload, dict):
        return {}

    normalized = getattr(item, "normalized_payload", None) or {}
    model = str(
        payload.get("model")
        or payload.get("manufacturer_sku")
        or normalized.get("model")
        or normalized.get("manufacturer_sku")
        or ""
    ).strip()
    normalized_model = str(
        normalized.get("model")
        or normalized.get("manufacturer_sku")
        or ""
    ).strip()

    # If both sides expose a concrete identifier, require an exact normalized
    # match before using these facts for text-grounded creative media.
    def compact(value):
        import re
        return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())

    if model and normalized_model and compact(model) != compact(normalized_model):
        return {}

    return {
        "provider": str(fallback.get("provider") or ""),
        "official_product_url": str(
            fallback.get("official_product_url")
            or payload.get("official_product_url")
            or ""
        ).strip(),
        "name": str(payload.get("name") or normalized.get("name") or "").strip(),
        "brand": str(payload.get("brand") or normalized.get("brand") or "").strip(),
        "manufacturer": str(
            payload.get("manufacturer") or normalized.get("manufacturer") or ""
        ).strip(),
        "model": model or normalized_model,
        "category": str(payload.get("category") or normalized.get("category") or "").strip(),
        "subcategory": str(
            payload.get("subcategory") or normalized.get("subcategory") or ""
        ).strip(),
        "short_description": str(payload.get("short_description") or "").strip(),
        "key_features": list(payload.get("key_features") or [])[:12],
        "specifications": dict(payload.get("specifications") or {}),
        "evidence_urls": list(fallback.get("evidence_urls") or [])[:20],
    }


def _compact_text_grounding(grounding):
    """Build a bounded factual text block for creative prompting."""
    if not grounding:
        return ""

    parts = []
    if grounding.get("name"):
        parts.append(f"Official product name: {grounding['name']}")
    if grounding.get("brand"):
        parts.append(f"Brand: {grounding['brand']}")
    if grounding.get("model"):
        parts.append(f"Exact model: {grounding['model']}")
    if grounding.get("category"):
        parts.append(f"Category: {grounding['category']}")
    if grounding.get("subcategory"):
        parts.append(f"Subtype: {grounding['subcategory']}")
    if grounding.get("short_description"):
        parts.append(f"Manufacturer description: {grounding['short_description'][:700]}")

    features = [
        str(value).strip()
        for value in (grounding.get("key_features") or [])
        if str(value).strip()
    ][:10]
    if features:
        parts.append("Verified features: " + "; ".join(features))

    specs = grounding.get("specifications") or {}
    if isinstance(specs, dict):
        spec_parts = []
        for key, value in list(specs.items())[:12]:
            if isinstance(value, (str, int, float)):
                spec_parts.append(f"{key}: {value}")
            elif isinstance(value, list):
                clean = ", ".join(str(v) for v in value[:8] if str(v).strip())
                if clean:
                    spec_parts.append(f"{key}: {clean}")
        if spec_parts:
            parts.append("Verified specifications: " + "; ".join(spec_parts))

    return "\n".join(parts)[:3500]


def creative_fallback_capability(item, candidate, *, support_info=None):
    if candidate.kind != ImportMediaCandidate.KIND_GENERATION:
        return {
            "available": False,
            "reason": "Reference-only media cannot use creative fallback.",
        }

    metadata = candidate_metadata(candidate)
    policy = candidate_generation_policy(candidate)

    if policy == POLICY_ACTUAL_ONLY:
        return {
            "available": False,
            "reason": (
                "This category slot requires actual seller/verified documentary media. "
                "AI generation is disabled to avoid misrepresenting real-world property/location facts."
            ),
        }

    if candidate.view_role == ImportMediaCandidate.VIEW_PORTS:
        return {
            "available": False,
            "reason": "Technical I/O/controls never uses creative fallback.",
        }

    if not candidate_creative_allowed(candidate):
        return {
            "available": False,
            "reason": "This category-profile slot does not allow creative fallback.",
        }

    if candidate.status not in {
        ImportMediaCandidate.STATUS_PLANNED,
        ImportMediaCandidate.STATUS_FAILED,
        ImportMediaCandidate.STATUS_REJECTED,
    }:
        return {
            "available": False,
            "reason": "Creative fallback is available only for queued, failed, or rejected jobs.",
        }

    support = support_info or reference_support_for_view(item, candidate.view_role)

    # Intentional creative slots are allowed even when the reused legacy view
    # role happens to have exact support. The metadata role is authoritative.
    intentional_creative = policy == POLICY_CREATIVE
    if support.get("supported") and not intentional_creative:
        return {
            "available": False,
            "reason": (
                "A trustworthy exact-view reference exists. Use verified/reference-preserving "
                "generation instead of creative fallback."
            ),
        }

    refs = creative_fallback_reference_urls(
        item,
        max_refs=int(_config("CATALOG_IMPORT_MEDIA_MAX_REFERENCES", 3) or 3),
    )

    text_grounding = {}
    text_grounded_creative = False

    if not refs:
        # Universal Phase 5.2.3 fallback:
        # Only category-profile slots that are INTENTIONALLY creative may be
        # generated without a pixel reference, and only when Phase 5.2 has
        # already verified exact manufacturer identity through trusted domains.
        #
        # Verified/factual slots (hero/front/technical/package/etc.) still fail
        # closed when exact visual evidence is unavailable.
        if intentional_creative:
            text_grounding = _verified_web_text_grounding(item)
            text_grounded_creative = bool(text_grounding)

        if not text_grounded_creative:
            return {
                "available": False,
                "reason": (
                    "No exact-item manufacturer reference image is available. "
                    "This slot cannot be generated safely without visual grounding."
                ),
            }

    label = candidate_display_label(candidate)
    if text_grounded_creative:
        reason = (
            f"{label} is an intentional creative/support slot. Exact manufacturer "
            "identity/specifications are verified, but no exact reference image is "
            "available, so this will be generated as TEXT-GROUNDED CREATIVE media "
            "and must be manually reviewed."
        )
    else:
        reason = (
            f"{label} is an intentional creative/support slot in the selected category profile."
            if intentional_creative
            else (
                "No trustworthy exact-view manufacturer reference was found. "
                "A creative fallback may be generated from exact-item identity references."
            )
        )

    return {
        "available": True,
        "reason": reason,
        "reference_urls": refs,
        "intentional_creative": intentional_creative,
        "text_grounded_creative": text_grounded_creative,
        "text_grounding": text_grounding,
        "representation_rule": candidate_representation_rule(candidate),
    }


def _identity(item):
    payload = item.normalized_payload or {}
    brand = str(payload.get("brand") or payload.get("manufacturer") or "").strip()
    name = str(payload.get("name") or payload.get("title") or "").strip()
    model = str(
        payload.get("model")
        or payload.get("model_number")
        or payload.get("manufacturer_sku")
        or ""
    ).strip()

    identity = name or "the verified product"
    if brand and brand.lower() not in identity.lower():
        identity = f"{brand} {identity}"
    if model and model.lower() not in identity.lower():
        identity = f"{identity} ({model})"
    return identity


def build_creative_fallback_prompt(item, candidate, *, text_grounding=None):
    identity = _identity(item)
    metadata = candidate_metadata(candidate)
    label = candidate_display_label(candidate)
    representation_rule = candidate_representation_rule(candidate)
    profile_prompt = str(metadata.get("creative_prompt") or "").strip()
    text_grounding = text_grounding or {}
    grounding_text = _compact_text_grounding(text_grounding)

    if profile_prompt:
        view_text = profile_prompt
    elif candidate.view_role == ImportMediaCandidate.VIEW_PACKAGE:
        view_text = (
            "Create a neutral creative packaging presentation of the verified item beside "
            "a plain unbranded CLOSED box. Do not show the inside of the box. Do not show or "
            "imply specific included accessories, cables, adapters, remotes, mounts, manuals, "
            "or bundle contents. No packaging text, labels, specifications, barcodes, or claims."
        )
    else:
        view_text = (
            f"Create a visually useful creative marketplace image for the slot '{label}'. "
            "Use the supplied exact-item references only as identity anchors. Preserve directly visible "
            "identity cues. Do not treat unsupported hidden geometry or unseen details as factual."
        )

    real_world_guard = ""
    if representation_rule == "concept_only":
        real_world_guard = (
            " IMPORTANT: this is a CONCEPT VISUALIZATION, not documentary evidence. "
            "Do not represent the output as an actual photograph of a real property, land parcel, "
            "location, road, boundary, room, amenity, measurement, title document, map, or neighborhood fact."
        )

    grounding_clause = ""
    if grounding_text:
        grounding_clause = (
            "\n\nVERIFIED MANUFACTURER TEXT GROUNDING (NOT visual proof):\n"
            + grounding_text
            + "\nNo exact manufacturer image is being supplied for this generation. "
              "Use these facts to improve category/product plausibility, but do not claim "
              "that generated appearance, hidden geometry, controls, materials, stitching, "
              "packaging, property features, or other visual details are manufacturer-verified."
        )

    return (
        f"CREATIVE MEDIA — UNVERIFIED REPRESENTATION. Exact item identity: {identity}. "
        f"Category-profile slot: {label}. {view_text}{real_world_guard}{grounding_clause} "
        "Create a clean professional marketplace image. No retailer identity, seller watermark, price, "
        "promotional banner, website UI, or text overlay. Preserve manufacturer/brand identity only when "
        "supported by verified evidence. Do not invent factual product features, included contents, "
        "materials, technical specifications, dimensions, garment/shoe/watch/eyewear construction details, "
        "or real-estate/location facts. This image remains review-only and must not be presented as verified evidence."
    )


def materialize_creative_fallback(candidate, *, provider_key=None):
    item = candidate.item
    _ensure_item_ready(item)

    capability = creative_fallback_capability(item, candidate)
    if not capability.get("available"):
        raise CreativeFallbackError(capability.get("reason") or "Creative fallback is not available.")

    try:
        review_storage_alias()
    except ReviewStorageError as exc:
        raise CreativeFallbackError(str(exc)) from exc

    refs = list(capability.get("reference_urls") or [])
    text_grounded_creative = bool(capability.get("text_grounded_creative"))
    text_grounding = dict(capability.get("text_grounding") or {})

    if not refs and not text_grounded_creative:
        raise CreativeFallbackError(
            "Creative fallback requires an exact-product manufacturer reference "
            "unless this is an explicitly allowed text-grounded creative slot."
        )

    prompt = build_creative_fallback_prompt(
        item,
        candidate,
        text_grounding=text_grounding,
    )
    provider = get_provider(provider_key)
    base_provider_key = getattr(provider, "key", provider_key or "")
    resolved_provider_key = f"{base_provider_key}-creative-fallback"

    candidate.reference_urls = refs

    metadata = dict(candidate.metadata or {})
    if text_grounded_creative:
        metadata["creative_text_grounding_trace"] = {
            "mode": "verified_manufacturer_text_no_visual_reference",
            "provider": str(text_grounding.get("provider") or ""),
            "official_product_url": str(text_grounding.get("official_product_url") or ""),
            "name": str(text_grounding.get("name") or ""),
            "brand": str(text_grounding.get("brand") or ""),
            "model": str(text_grounding.get("model") or ""),
            "evidence_urls": list(text_grounding.get("evidence_urls") or [])[:20],
        }
    candidate.metadata = metadata

    candidate.status = ImportMediaCandidate.STATUS_GENERATING
    candidate.generation_attempts = int(candidate.generation_attempts or 0) + 1
    candidate.provider_key = resolved_provider_key
    candidate.generation_prompt = prompt
    candidate.last_error = ""

    reference_urls_used = record_reference_trace(
        candidate,
        urls=refs,
        provider_key=resolved_provider_key,
    )
    candidate.save(update_fields=[
        "reference_urls",
        "status",
        "generation_attempts",
        "provider_key",
        "generation_prompt",
        "metadata",
        "last_error",
        "updated_at",
    ])

    size = str(_config("CATALOG_IMPORT_MEDIA_PROVIDER_SIZE", "1024x1024") or "1024x1024")
    quality = str(_config("CATALOG_IMPORT_MEDIA_QUALITY", "medium") or "medium")

    try:
        result = provider.generate(
            prompt=prompt,
            reference_urls=reference_urls_used,
            size=size,
            quality=quality,
        )
        stored = save_review_asset(candidate, result.content)

        with transaction.atomic():
            candidate.refresh_from_db()
            candidate.asset_storage_alias = stored.storage_alias
            candidate.asset_storage_name = stored.storage_name
            candidate.asset_original_name = stored.original_name
            candidate.mime_type = stored.mime_type
            candidate.width = stored.width
            candidate.height = stored.height
            candidate.file_size = stored.file_size
            candidate.sha256 = stored.sha256
            candidate.provider_asset_id = str(result.provider_asset_id or "")[:255]

            provider_metadata = dict(result.metadata or {})
            provider_metadata["_arolana_reference_urls_used"] = list(reference_urls_used)
            provider_metadata["_arolana_generation_attempt"] = int(candidate.generation_attempts or 0)
            provider_metadata["_arolana_view_role"] = str(candidate.view_role or "")
            provider_metadata["_arolana_render_mode"] = (
                "creative_text_grounded"
                if text_grounded_creative
                else "creative_fallback"
            )
            provider_metadata["_arolana_creative_fallback"] = True
            provider_metadata["_arolana_text_grounded_creative"] = bool(text_grounded_creative)
            provider_metadata["_arolana_visual_reference_count"] = len(reference_urls_used)
            provider_metadata["_arolana_accuracy_class"] = (
                "creative_unverified_text_grounded"
                if text_grounded_creative
                else "creative_unverified"
            )
            provider_metadata["_arolana_requested_view_verified"] = False
            provider_metadata["_arolana_ai_redraw"] = True
            provider_metadata["_arolana_factual_geometry_claim"] = False
            provider_metadata["_arolana_review_warning"] = (
                "This category-profile creative image is unverified representation. "
                + (
                    "It was generated from verified manufacturer TEXT facts without an exact visual reference. "
                    if text_grounded_creative
                    else ""
                )
                + "Manually inspect or edit before Product use."
            )
            slot_meta = candidate_metadata(candidate)
            provider_metadata["_arolana_media_profile"] = slot_meta.get("media_profile", "")
            provider_metadata["_arolana_media_role"] = slot_meta.get("universal_role", "")
            provider_metadata["_arolana_media_type"] = slot_meta.get("media_type", "")
            provider_metadata["_arolana_trust_policy"] = slot_meta.get("trust_policy", "")
            provider_metadata["_arolana_display_label"] = candidate_display_label(candidate)
            provider_metadata["_arolana_representation_rule"] = candidate_representation_rule(candidate)
            candidate.provider_response = provider_metadata

            candidate.generated_at = timezone.now()
            candidate.exact_identity_verified = False
            candidate.source_identity_check_passed = False
            candidate.watermark_status = ImportMediaCandidate.WATERMARK_UNKNOWN
            candidate.rights_status = ImportMediaCandidate.RIGHTS_UNKNOWN
            candidate.selected_for_product = False
            candidate.reviewed_at = None
            candidate.approved_by = None
            candidate.approved_at = None
            candidate.rejected_by = None
            candidate.rejected_at = None
            candidate.rejection_reason = ""
            candidate.attached_product_image = None
            candidate.attached_at = None
            candidate.status = ImportMediaCandidate.STATUS_READY_REVIEW
            candidate.last_error = ""
            candidate.save()

        errors = validate_materialized_candidate(candidate)
        if duplicate_hash_exists(candidate):
            errors.append("Creative fallback is byte-identical to another candidate for this item.")
        if errors:
            candidate.status = ImportMediaCandidate.STATUS_FAILED
            candidate.last_error = " ".join(errors)
            candidate.save(update_fields=["status", "last_error", "updated_at"])
            raise CreativeFallbackError(candidate.last_error)

        return candidate

    except (MediaProviderError, ReviewStorageError, CreativeFallbackError) as exc:
        candidate.refresh_from_db()
        candidate.status = ImportMediaCandidate.STATUS_FAILED
        candidate.last_error = str(exc)
        candidate.save(update_fields=["status", "last_error", "updated_at"])
        raise CreativeFallbackError(str(exc)) from exc
    except Exception as exc:
        candidate.refresh_from_db()
        candidate.status = ImportMediaCandidate.STATUS_FAILED
        candidate.last_error = f"Unexpected creative fallback failure: {exc}"
        candidate.save(update_fields=["status", "last_error", "updated_at"])
        raise CreativeFallbackError(candidate.last_error) from exc
