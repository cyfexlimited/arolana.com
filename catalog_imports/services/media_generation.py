import os

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from catalog_imports.media_providers import get_provider
from catalog_imports.media_providers.base import MediaProviderError
from catalog_imports.models import ImportMediaCandidate

from .media_prompts import MediaPromptHold, build_generation_prompt
from .media_reference_preserving import (
    ReferencePreservingError,
    is_reference_preserving_view,
    render_reference_preserving_asset,
)
from .media_references import ReferenceViewHold, select_generation_reference_urls
from .media_reference_trace import record_reference_trace
from .media_storage import ReviewStorageError, review_storage_alias, save_review_asset
from .media_validation import duplicate_hash_exists, validate_materialized_candidate


class MediaGenerationError(RuntimeError):
    pass


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


def _ensure_item_ready(item):
    if not item.created_product_id:
        raise MediaGenerationError("Prepare the inactive Arolana Product draft before generating media.")
    if not item.identity_verified:
        raise MediaGenerationError("Exact product identity must be verified before generating media.")
    if not item.specifications_verified:
        raise MediaGenerationError("Verified product specifications are required before generating media.")
    product = item.created_product
    if getattr(product, "is_active", False):
        raise MediaGenerationError("Media generation is limited to inactive importer-created Product drafts.")


def materialize_candidate(candidate, *, provider_key=None):
    item = candidate.item
    _ensure_item_ready(item)
    if candidate.kind != ImportMediaCandidate.KIND_GENERATION:
        raise MediaGenerationError("Reference-only media cannot be generated or materialized as product media.")
    if candidate.status not in {
        ImportMediaCandidate.STATUS_PLANNED,
        ImportMediaCandidate.STATUS_FAILED,
        ImportMediaCandidate.STATUS_REJECTED,
    }:
        raise MediaGenerationError(
            f"Candidate cannot be generated from status '{candidate.status}'."
        )

    # Phase 5.0.14:
    # Exact reference-preserving technical views do not need a generative text
    # prompt. The verified image itself is the factual source of truth. This
    # prevents a Package/contents job from being blocked merely because the
    # normalized text payload lacks a package_contents list when an official
    # package image has already been verified.
    reference_preserving = is_reference_preserving_view(candidate.view_role)

    if reference_preserving:
        prompt = (
            "REFERENCE-PRESERVING TECHNICAL MATERIALIZATION. "
            "Use only exact verified official reference pixels."
        )
    else:
        try:
            prompt = build_generation_prompt(item, candidate)
        except MediaPromptHold as exc:
            candidate.status = ImportMediaCandidate.STATUS_FAILED
            candidate.last_error = str(exc)
            candidate.generation_attempts = int(candidate.generation_attempts or 0) + 1
            candidate.save(update_fields=["status", "last_error", "generation_attempts", "updated_at"])
            raise MediaGenerationError(str(exc)) from exc

    # Validate review storage before making a billable provider request.
    try:
        review_storage_alias()
    except ReviewStorageError as exc:
        raise MediaGenerationError(str(exc)) from exc

    # Re-select and validate view-specific references before creating the provider
    # object or making any billable request. Hidden/detail views are blocked when
    # official evidence does not actually show the requested geometry.
    max_refs = int(_config("CATALOG_IMPORT_MEDIA_MAX_REFERENCES", 3) or 3)
    try:
        refreshed_refs = select_generation_reference_urls(
            item,
            candidate.view_role,
            max_refs=max_refs,
        )
    except ReferenceViewHold as exc:
        candidate.status = ImportMediaCandidate.STATUS_FAILED
        candidate.last_error = str(exc)
        candidate.save(update_fields=["status", "last_error", "updated_at"])
        raise MediaGenerationError(str(exc)) from exc

    candidate.reference_urls = refreshed_refs
    if not list(candidate.reference_urls or []):
        candidate.status = ImportMediaCandidate.STATUS_FAILED
        candidate.last_error = (
            "No official manufacturer reference image safely supports this requested view."
        )
        candidate.save(update_fields=["status", "last_error", "updated_at"])
        raise MediaGenerationError(candidate.last_error)

    # Geometry-sensitive technical views must never be free-form redrawn.
    # For those views we materialize the exact verified official reference
    # pixels into a clean marketplace canvas locally. No image-generation
    # provider is created or billed.
    if reference_preserving:
        provider = None
        resolved_provider_key = "reference-preserving"
        generation_prompt = (
            "REFERENCE-PRESERVING TECHNICAL MATERIALIZATION. "
            "Use only the exact verified official manufacturer reference pixels. "
            "No generative redraw, no reconstruction, no invented geometry, no "
            "port/button/accessory rearrangement. Only deterministic resizing, "
            "white-canvas placement, and multi-reference layout are permitted."
        )
    else:
        provider = get_provider(provider_key)
        resolved_provider_key = getattr(provider, "key", provider_key or "")
        generation_prompt = prompt

    candidate.status = ImportMediaCandidate.STATUS_GENERATING
    candidate.generation_attempts = int(candidate.generation_attempts or 0) + 1
    candidate.provider_key = resolved_provider_key
    candidate.generation_prompt = generation_prompt
    candidate.last_error = ""

    # Freeze the exact references before either the local technical
    # materialization or the external provider request. The review screen remains
    # auditable even if reference ranking changes later.
    reference_urls_used = record_reference_trace(
        candidate,
        urls=list(candidate.reference_urls or []),
        provider_key=candidate.provider_key,
    )
    candidate.save(update_fields=[
        "status", "generation_attempts", "provider_key", "generation_prompt",
        "reference_urls", "metadata", "last_error", "updated_at"
    ])

    size = str(_config("CATALOG_IMPORT_MEDIA_PROVIDER_SIZE", "1024x1024") or "1024x1024")
    quality = str(_config("CATALOG_IMPORT_MEDIA_QUALITY", "medium") or "medium")

    try:
        if reference_preserving:
            result = render_reference_preserving_asset(
                reference_urls=reference_urls_used,
                view_role=candidate.view_role,
                size=size,
            )
        else:
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
                "reference_preserving" if reference_preserving else "generative"
            )
            provider_metadata["_arolana_ai_redraw"] = not reference_preserving
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
            errors.append("Generated image is byte-identical to another candidate for this item.")
        if errors:
            candidate.status = ImportMediaCandidate.STATUS_FAILED
            candidate.last_error = " ".join(errors)
            candidate.save(update_fields=["status", "last_error", "updated_at"])
            raise MediaGenerationError(candidate.last_error)
        return candidate
    except (
        MediaProviderError,
        ReferencePreservingError,
        ReviewStorageError,
        MediaGenerationError,
    ) as exc:
        candidate.refresh_from_db()
        candidate.status = ImportMediaCandidate.STATUS_FAILED
        candidate.last_error = str(exc)
        candidate.save(update_fields=["status", "last_error", "updated_at"])
        raise MediaGenerationError(str(exc)) from exc
    except Exception as exc:
        candidate.refresh_from_db()
        candidate.status = ImportMediaCandidate.STATUS_FAILED
        candidate.last_error = f"Unexpected media generation failure: {exc}"
        candidate.save(update_fields=["status", "last_error", "updated_at"])
        raise MediaGenerationError(candidate.last_error) from exc


def generation_queue(item, *, include_failed=False):
    statuses = [ImportMediaCandidate.STATUS_PLANNED]
    if include_failed:
        statuses.append(ImportMediaCandidate.STATUS_FAILED)
    return item.media_candidates.filter(
        kind=ImportMediaCandidate.KIND_GENERATION,
        status__in=statuses,
    ).order_by("order", "id")
