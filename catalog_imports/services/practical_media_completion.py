"""Phase 5.3.7 — Practical media completion.

Goal
----
A product import should not become an endless attempt to fill every theoretical
10-image slot. Once Arolana has enough usable media and a usable Main/Hero image,
the importer can stop chasing missing views. Remaining images are optional and
may be uploaded later through the normal Product admin.

This does not lower review standards for images that are actually used.
"""

from __future__ import annotations

from django.conf import settings

from catalog_imports.models import ImportMediaCandidate


DEFAULT_MINIMUM_USABLE = 8
HARD_MAX_GALLERY = 10

_USABLE_STATUSES = {
    ImportMediaCandidate.STATUS_READY_REVIEW,
    ImportMediaCandidate.STATUS_APPROVED,
    ImportMediaCandidate.STATUS_ATTACHED,
}

_APPROVED_STATUSES = {
    ImportMediaCandidate.STATUS_APPROVED,
    ImportMediaCandidate.STATUS_ATTACHED,
}


def _configured_minimum():
    value = getattr(
        settings,
        "CATALOG_IMPORT_MEDIA_MINIMUM_USABLE",
        DEFAULT_MINIMUM_USABLE,
    )
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = DEFAULT_MINIMUM_USABLE
    return max(1, min(value, HARD_MAX_GALLERY))


def _has_asset(candidate):
    return bool(str(getattr(candidate, "asset_storage_name", "") or "").strip())


def practical_media_completion(item, *, minimum=None):
    """Return a live, schema-free media completion report.

    `usable` means the review asset exists and is Ready for review, Approved,
    or already Attached. Rejected/failed/planned candidates do not count.
    """
    target = min(
        max(int(getattr(getattr(item, "batch", None), "max_images", 10) or 10), 1),
        HARD_MAX_GALLERY,
    )

    if minimum is None:
        minimum = _configured_minimum()
    minimum = min(max(int(minimum), 1), target)

    candidates = list(
        item.media_candidates.filter(
            kind=ImportMediaCandidate.KIND_GENERATION,
        ).order_by("order", "id")
    )

    usable = [
        candidate
        for candidate in candidates
        if candidate.status in _USABLE_STATUSES and _has_asset(candidate)
    ]
    approved = [
        candidate
        for candidate in candidates
        if candidate.status in _APPROVED_STATUSES and _has_asset(candidate)
    ]

    main_candidates = [
        candidate
        for candidate in candidates
        if candidate.view_role == ImportMediaCandidate.VIEW_MAIN
    ]

    main_usable = any(
        candidate.status in _USABLE_STATUSES and _has_asset(candidate)
        for candidate in main_candidates
    )
    main_approved = any(
        candidate.status in _APPROVED_STATUSES and _has_asset(candidate)
        for candidate in main_candidates
    )

    sufficient_for_review = (
        main_usable and len(usable) >= minimum
    )
    sufficient_for_product = (
        main_approved and len(approved) >= minimum
    )

    return {
        "version": "5.3.7",
        "target_count": target,
        "minimum_usable": minimum,
        "usable_count": len(usable),
        "approved_count": len(approved),
        "main_usable": main_usable,
        "main_approved": main_approved,
        "sufficient_for_review": sufficient_for_review,
        "sufficient_for_product": sufficient_for_product,
        "stop_bulk_generation": sufficient_for_review,
        "remaining_to_minimum": max(0, minimum - len(usable)),
        "remaining_optional_slots": max(0, target - len(usable)),
        "rule": (
            "Once the minimum usable-media threshold and a Main/Hero image are "
            "available, remaining gallery slots are optional. They may be added "
            "later in the normal Product admin."
        ),
    }
