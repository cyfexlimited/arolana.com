from django.utils import timezone

from catalog_imports.models import ImportMediaCandidate

from .media_profiles import (
    GENERIC,
    MediaSlot,
    candidate_display_label,
    get_media_profile,
    slot_metadata,
)
from .media_references import manufacturer_reference_urls, select_reference_urls
from .dynamic_verified_slots import (
    DYNAMIC_PLANNER_VERSION,
    dynamic_slot_metadata,
    is_dynamic_verified_slot,
    select_dynamic_verified_slots,
)


# Backward-compatible export retained for Phase 4/5 callers and tests.
# Phase 5.1 no longer *uses* this fixed list to plan new items; it exists only
# as a stable legacy API while category-aware profiles drive prepare_media_plan().
VIEW_PLAN = tuple(slot.legacy_view_role for slot in GENERIC.slots)


def _coerce_media_slot(slot):
    if isinstance(slot, MediaSlot):
        return slot
    for candidate in GENERIC.slots:
        if candidate.legacy_view_role == slot:
            return candidate
    # Defensive fallback for a legacy/unknown role.
    return GENERIC.slots[0]


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

    identity = name or brand or "verified item"
    if brand and brand.lower() not in identity.lower():
        identity = f"{brand} {identity}"
    if model and model.lower() not in identity.lower():
        identity = f"{identity} ({model})"
    return identity


def generation_prompt(item, slot) -> str:
    # Phase 4 callers pass a legacy view-role string. Phase 5.1 planners pass a
    # MediaSlot. Support both so the universal planner does not break old code.
    slot = _coerce_media_slot(slot)
    identity = _identity(item)
    return (
        f"Arolana media profile slot: {slot.label}. Exact item identity: {identity}. "
        f"{slot.prompt} "
        "Preserve the exact visible identity supported by supplied references. "
        "Do not include retailer/source branding, copied seller overlays, prices, website UI, or watermarks. "
        "Do not invent factual features, materials, labels, accessories, package contents, measurements, "
        "property/location facts, land boundaries, certifications, or technical geometry. "
        "If evidence is insufficient, the image must be held for manual review instead of guessing. "
        "Human review is mandatory before Product attachment."
    )


def _plan_reference_urls(item, slot, refs):
    # Creative slots use clean product identity anchors later in the creative
    # service.  Here we still give them a conservative initial identity set.
    try:
        selected = select_reference_urls(
            item,
            slot.legacy_view_role,
            max_refs=5,
        )
    except Exception:
        selected = []
    return selected or refs[:5]


def prepare_media_plan(item):
    """Prepare a category-aware media plan of at most batch.max_images slots.

    Existing Product/Vendor/Storefront models remain untouched.  Universal role,
    media type, trust level and category-profile semantics are stored in candidate
    metadata while the legacy view_role remains a compatibility bridge.
    """
    refs = manufacturer_reference_urls(item)
    profile = get_media_profile(item)

    # Replace only untouched planner rows. Reviewed/approved/attached media stays.
    item.media_candidates.filter(
        kind__in=[
            ImportMediaCandidate.KIND_REFERENCE,
            ImportMediaCandidate.KIND_GENERATION,
        ],
        status__in=[
            ImportMediaCandidate.STATUS_REFERENCE,
            ImportMediaCandidate.STATUS_PLANNED,
        ],
    ).delete()

    for order, url in enumerate(refs[:10], 1):
        ImportMediaCandidate.objects.create(
            item=item,
            kind=ImportMediaCandidate.KIND_REFERENCE,
            status=ImportMediaCandidate.STATUS_REFERENCE,
            order=order,
            source_url=url,
            exact_identity_required=True,
            exact_identity_verified=bool(item.identity_verified),
            rights_status=ImportMediaCandidate.RIGHTS_UNKNOWN,
            metadata={
                "media_profile": profile.key,
                "media_profile_label": profile.label,
                "taxonomy_version": "5.1",
                "reference_role": "official_identity_evidence",
            },
            notes=(
                "Official-manufacturer visual reference. Reference-only until usage rights "
                "are confirmed; never publish this source image automatically."
            ),
        )

    planned = 0
    max_images = min(max(int(item.batch.max_images or 1), 1), 10)
    dynamic_selection = select_dynamic_verified_slots(
        item,
        profile=profile,
        max_images=max_images,
    )
    chosen_slots = dynamic_selection["slots"]

    if item.batch.generate_or_prepare_images and item.identity_verified:
        for order, slot in enumerate(chosen_slots, 1):
            metadata = (
                dynamic_slot_metadata(profile, slot)
                if is_dynamic_verified_slot(slot)
                else slot_metadata(profile, slot)
            )
            metadata["planner_version"] = DYNAMIC_PLANNER_VERSION
            note = (
                f"Phase {DYNAMIC_PLANNER_VERSION} profile={profile.key}; role={slot.universal_role}; "
                f"type={slot.media_type}; trust={slot.trust_policy}; "
                f"policy={slot.generation_policy}. "
            )
            if slot.generation_policy == "actual_only":
                note += (
                    "Actual seller/verified documentary media is required. "
                    "AI generation is deliberately disabled for this slot."
                )
            elif slot.generation_policy == "creative":
                note += (
                    "Intentional creative/support slot. Output must remain clearly labelled "
                    "as creative/unverified until human approval."
                )
            else:
                note += (
                    "Verified/reference-preserving media is preferred. Creative fallback is "
                    "available only when allowed by this profile."
                )

            ImportMediaCandidate.objects.create(
                item=item,
                kind=ImportMediaCandidate.KIND_GENERATION,
                status=ImportMediaCandidate.STATUS_PLANNED,
                order=order,
                view_role=slot.legacy_view_role,
                reference_urls=_plan_reference_urls(item, slot, refs),
                generation_prompt=generation_prompt(item, slot),
                exact_identity_required=True,
                exact_identity_verified=False,
                watermark_status=ImportMediaCandidate.WATERMARK_UNKNOWN,
                rights_status=ImportMediaCandidate.RIGHTS_UNKNOWN,
                metadata=metadata,
                notes=note,
            )
            planned += 1

    item.media_plan_prepared_at = timezone.now()
    item.image_report = {
        "phase": "universal_category_media_profiles",
        "taxonomy_version": "5.1",
        "media_profile": profile.key,
        "media_profile_label": profile.label,
        "profile_notes": profile.notes,
        "planned_slots": [
            {
                "order": index,
                "slot_key": slot.key,
                "display_label": slot.label,
                "universal_role": slot.universal_role,
                "media_type": slot.media_type,
                "trust_policy": slot.trust_policy,
                "generation_policy": slot.generation_policy,
                "legacy_view_role": slot.legacy_view_role,
            }
            for index, slot in enumerate(chosen_slots, 1)
        ],
        "official_reference_count": len(refs),
        "generation_jobs_planned": planned,
        "maximum_images": max_images,
        "planner_version": DYNAMIC_PLANNER_VERSION,
        "dynamic_verified_replacements": dynamic_selection["replacements"],
        "publication_rule": (
            "Every candidate remains review-only. Actual-only real-estate/land slots cannot "
            "be AI-generated. Creative media must be explicitly acknowledged as unverified "
            "before Product attachment."
        ),
    }
    item.save(
        update_fields=[
            "media_plan_prepared_at",
            "image_report",
            "updated_at",
        ]
    )
    return item.image_report
