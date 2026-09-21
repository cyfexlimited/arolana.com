"""Phase 5.3.3 — Dynamic verified media slots.

The fixed category profile remains the baseline, but when Arolana has strong
official manufacturer evidence for a factual view that is NOT represented by a
factual slot, the planner may replace a lower-value creative slot with that real
verified view.

Examples:
- electronics + verified Back -> replace 3D-style creative with Back / rear
- electronics + verified Side -> replace the legacy side-based creative slot
- generic + verified Back -> prefer factual Back over final creative support

Approved/attached media is never replaced automatically. Existing plans require
an explicit admin action to replace only unapproved creative candidates.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

from django.db import transaction

from catalog_imports.models import ImportAuditEvent, ImportMediaCandidate

from .media_profiles import (
    MediaSlot,
    POLICY_ACTUAL_ONLY,
    POLICY_CREATIVE,
    POLICY_VERIFIED,
    TRUST_EXACT,
    TRUST_SUPPORTING,
    TYPE_CLOSEUP,
    TYPE_PACKAGING,
    TYPE_PRODUCT,
    TYPE_SCENE,
    TYPE_TECHNICAL,
    candidate_generation_policy,
    get_media_profile,
    slot_metadata,
)
from .media_references import (
    reference_support_report,
    select_reference_urls,
)
from .media_storage import delete_review_asset


DYNAMIC_PLANNER_VERSION = "5.3.3"

# Main is intentionally omitted: category profiles already carry a main/hero slot.
# Existing factual profile slots (Front, Ports, Package, Closeup, etc.) are not
# duplicated; only factual views missing from the profile are injected.
DYNAMIC_ROLE_PRIORITY = (
    ImportMediaCandidate.VIEW_BACK,
    ImportMediaCandidate.VIEW_SIDE,
    ImportMediaCandidate.VIEW_LEFT,
    ImportMediaCandidate.VIEW_RIGHT,
    ImportMediaCandidate.VIEW_TOP,
    ImportMediaCandidate.VIEW_CLOSEUP,
    ImportMediaCandidate.VIEW_PORTS,
    ImportMediaCandidate.VIEW_PACKAGE,
    ImportMediaCandidate.VIEW_FRONT,
    ImportMediaCandidate.VIEW_LIFESTYLE,
)


ROLE_DEFINITIONS = {
    ImportMediaCandidate.VIEW_FRONT: {
        "label": "Front",
        "universal_role": "factual_primary",
        "media_type": TYPE_PRODUCT,
        "trust": TRUST_EXACT,
        "prompt": "Show the exact official manufacturer front/product view only.",
    },
    ImportMediaCandidate.VIEW_BACK: {
        "label": "Back / rear",
        "universal_role": "factual_secondary",
        "media_type": TYPE_PRODUCT,
        "trust": TRUST_EXACT,
        "prompt": "Show the exact manufacturer-verified rear/back view only.",
    },
    ImportMediaCandidate.VIEW_LEFT: {
        "label": "Left angle",
        "universal_role": "factual_secondary",
        "media_type": TYPE_PRODUCT,
        "trust": TRUST_SUPPORTING,
        "prompt": "Show the exact manufacturer-verified left-angle view only.",
    },
    ImportMediaCandidate.VIEW_RIGHT: {
        "label": "Right angle",
        "universal_role": "factual_secondary",
        "media_type": TYPE_PRODUCT,
        "trust": TRUST_SUPPORTING,
        "prompt": "Show the exact manufacturer-verified right-angle view only.",
    },
    ImportMediaCandidate.VIEW_SIDE: {
        "label": "Side profile",
        "universal_role": "factual_secondary",
        "media_type": TYPE_PRODUCT,
        "trust": TRUST_SUPPORTING,
        "prompt": "Show the exact manufacturer-verified side/profile view only.",
    },
    ImportMediaCandidate.VIEW_TOP: {
        "label": "Top / detail",
        "universal_role": "detail_secondary",
        "media_type": TYPE_CLOSEUP,
        "trust": TRUST_SUPPORTING,
        "prompt": "Show the exact manufacturer-verified top/detail view only.",
    },
    ImportMediaCandidate.VIEW_PORTS: {
        "label": "Controls / technical detail",
        "universal_role": "technical_detail",
        "media_type": TYPE_TECHNICAL,
        "trust": TRUST_EXACT,
        "prompt": "Show only manufacturer-verified ports, controls, connectors, or technical geometry.",
    },
    ImportMediaCandidate.VIEW_PACKAGE: {
        "label": "Package / contents",
        "universal_role": "package_or_extra",
        "media_type": TYPE_PACKAGING,
        "trust": TRUST_EXACT,
        "prompt": "Show only exact manufacturer-verified packaging or included contents.",
    },
    ImportMediaCandidate.VIEW_LIFESTYLE: {
        "label": "Lifestyle / in use — verified",
        "universal_role": "lifestyle",
        "media_type": TYPE_SCENE,
        "trust": TRUST_SUPPORTING,
        "prompt": "Use the exact official manufacturer lifestyle/in-use scene as factual visual grounding.",
    },
    ImportMediaCandidate.VIEW_CLOSEUP: {
        "label": "Product detail",
        "universal_role": "detail",
        "media_type": TYPE_CLOSEUP,
        "trust": TRUST_SUPPORTING,
        "prompt": "Show only an exact manufacturer-supported close product detail.",
    },
}


def _dynamic_slot(role: str) -> MediaSlot:
    definition = ROLE_DEFINITIONS[role]
    return MediaSlot(
        key=f"dynamic_verified_{role}",
        label=definition["label"],
        universal_role=definition["universal_role"],
        media_type=definition["media_type"],
        trust_policy=definition["trust"],
        generation_policy=POLICY_VERIFIED,
        legacy_view_role=role,
        prompt=definition["prompt"],
        creative_prompt="",
        creative_allowed=False,
        # Reference-preserving technical/package views bypass free-form redraw.
        requires_specifications=role in {
            ImportMediaCandidate.VIEW_PORTS,
            ImportMediaCandidate.VIEW_PACKAGE,
        },
        representation_rule="product",
    )


def is_dynamic_verified_slot(slot) -> bool:
    return str(getattr(slot, "key", "") or "").startswith("dynamic_verified_")


def dynamic_slot_metadata(profile, slot):
    metadata = slot_metadata(profile, slot)
    metadata["planner_version"] = DYNAMIC_PLANNER_VERSION
    metadata["dynamic_verified_slot"] = True
    metadata["verified_support_role"] = slot.legacy_view_role
    metadata["creative_fallback_allowed"] = False
    return metadata


def _slot_replacement_score(slot) -> int:
    """Higher number = lower-value creative slot, replace this first."""
    if getattr(slot, "generation_policy", "") != POLICY_CREATIVE:
        return -1

    media_type = str(getattr(slot, "media_type", "") or "")
    universal_role = str(getattr(slot, "universal_role", "") or "")
    key = str(getattr(slot, "key", "") or "").lower()

    if "render" in key or universal_role == "creative_support":
        return 1000
    if media_type == "concept_visualization":
        return 950
    if universal_role == "context":
        return 850
    if universal_role == "usage":
        return 800
    if universal_role == "installation":
        return 750
    if universal_role in {"lifestyle", "model_worn"}:
        return 650
    return 500


def _supported_roles(support: Dict) -> set:
    return {
        role
        for role, info in (support or {}).items()
        if isinstance(info, dict) and info.get("supported")
    }


def select_dynamic_verified_slots(
    item,
    *,
    profile=None,
    max_images=None,
    support=None,
):
    """Return a future-plan slot selection that prefers discovered factual views.

    No database mutation occurs here.
    """
    profile = profile or get_media_profile(item)
    max_images = min(
        max(
            int(
                max_images
                if max_images is not None
                else getattr(getattr(item, "batch", None), "max_images", 10) or 10
            ),
            1,
        ),
        10,
    )
    base_slots = list(profile.slots[:max_images])

    # Property/land require seller/actual documentary media. Manufacturer-style
    # dynamic substitution is deliberately not applied to those profiles.
    if profile.key in {"property", "land"}:
        return {
            "slots": tuple(base_slots),
            "replacements": [],
            "supported_roles": [],
            "planner_version": DYNAMIC_PLANNER_VERSION,
        }

    support = support or reference_support_report(item)
    supported = _supported_roles(support)

    # Roles already represented by factual/actual slots should simply unlock
    # through the existing generation gate; they do not need a new slot.
    factual_roles = {
        slot.legacy_view_role
        for slot in base_slots
        if slot.generation_policy in {POLICY_VERIFIED, POLICY_ACTUAL_ONLY}
    }

    replacements = []
    used_indices = set()

    for role in DYNAMIC_ROLE_PRIORITY:
        if role not in supported or role not in ROLE_DEFINITIONS:
            continue
        if role in factual_roles:
            continue

        # If a creative slot already uses this legacy role, upgrade that exact
        # position first (e.g. electronics Side/3D slot -> verified Side).
        direct_index = None
        for index, slot in enumerate(base_slots):
            if index in used_indices:
                continue
            if (
                slot.legacy_view_role == role
                and slot.generation_policy == POLICY_CREATIVE
            ):
                direct_index = index
                break

        if direct_index is None:
            creative_indices = [
                index
                for index, slot in enumerate(base_slots)
                if index not in used_indices
                and slot.generation_policy == POLICY_CREATIVE
            ]
            if not creative_indices:
                continue
            direct_index = max(
                creative_indices,
                key=lambda index: _slot_replacement_score(base_slots[index]),
            )

        old_slot = base_slots[direct_index]
        new_slot = _dynamic_slot(role)
        base_slots[direct_index] = new_slot
        used_indices.add(direct_index)
        factual_roles.add(role)

        replacements.append({
            "role": role,
            "old_slot_key": old_slot.key,
            "old_label": old_slot.label,
            "new_slot_key": new_slot.key,
            "new_label": new_slot.label,
            "position": direct_index + 1,
        })

    return {
        "slots": tuple(base_slots),
        "replacements": replacements,
        "supported_roles": sorted(supported),
        "planner_version": DYNAMIC_PLANNER_VERSION,
    }


def _candidate_metadata(candidate):
    data = getattr(candidate, "metadata", None) or {}
    return data if isinstance(data, dict) else {}


def _candidate_replacement_score(candidate) -> int:
    metadata = _candidate_metadata(candidate)
    policy = str(metadata.get("generation_policy") or "")
    if policy != POLICY_CREATIVE:
        return -1

    slot_key = str(metadata.get("slot_key") or "").lower()
    universal_role = str(metadata.get("universal_role") or "")
    media_type = str(metadata.get("media_type") or "")

    if "render" in slot_key or universal_role == "creative_support":
        return 1000
    if media_type == "concept_visualization":
        return 950
    if universal_role == "context":
        return 850
    if universal_role == "usage":
        return 800
    if universal_role == "installation":
        return 750
    if universal_role in {"lifestyle", "model_worn"}:
        return 650
    return 500


def candidate_can_be_replaced(candidate) -> bool:
    """Only unapproved/unattached creative candidates may be superseded."""
    if candidate_generation_policy(candidate) != POLICY_CREATIVE:
        return False
    if getattr(candidate, "status", "") in {
        ImportMediaCandidate.STATUS_APPROVED,
        ImportMediaCandidate.STATUS_ATTACHED,
        ImportMediaCandidate.STATUS_GENERATING,
    }:
        return False
    if bool(getattr(candidate, "selected_for_product", False)):
        return False
    if getattr(candidate, "attached_product_image_id", None):
        return False
    return True


def _existing_factual_roles(candidates: Iterable) -> set:
    roles = set()
    for candidate in candidates:
        if candidate_generation_policy(candidate) != POLICY_CREATIVE:
            roles.add(str(getattr(candidate, "view_role", "") or ""))
    return roles


def dynamic_verified_slot_report(item, *, support=None):
    """Describe actionable factual replacements for an existing media plan."""
    profile = get_media_profile(item)
    support = support or reference_support_report(item)
    selection = select_dynamic_verified_slots(
        item,
        profile=profile,
        support=support,
    )

    candidates = list(
        item.media_candidates.filter(
            kind=ImportMediaCandidate.KIND_GENERATION,
        ).order_by("order", "id")
    )
    factual_roles = _existing_factual_roles(candidates)
    reserved = set()
    actions = []
    blocked = []

    for replacement in selection["replacements"]:
        role = replacement["role"]
        if role in factual_roles:
            continue

        desired_old_key = replacement["old_slot_key"]
        direct = None
        for candidate in candidates:
            if candidate.pk in reserved or not candidate_can_be_replaced(candidate):
                continue
            metadata = _candidate_metadata(candidate)
            if str(metadata.get("slot_key") or "") == desired_old_key:
                direct = candidate
                break

        if direct is None:
            same_role = [
                candidate
                for candidate in candidates
                if candidate.pk not in reserved
                and candidate_can_be_replaced(candidate)
                and candidate.view_role == role
            ]
            if same_role:
                direct = max(same_role, key=_candidate_replacement_score)

        if direct is None:
            replaceable = [
                candidate
                for candidate in candidates
                if candidate.pk not in reserved
                and candidate_can_be_replaced(candidate)
            ]
            if replaceable:
                direct = max(replaceable, key=_candidate_replacement_score)

        if direct is None:
            blocked.append({
                **replacement,
                "reason": (
                    "No unapproved creative slot is available. Approved/attached "
                    "media is deliberately never replaced automatically."
                ),
            })
            continue

        reserved.add(direct.pk)
        metadata = _candidate_metadata(direct)
        actions.append({
            **replacement,
            "candidate_id": direct.pk,
            "candidate_order": direct.order,
            "current_label": str(
                metadata.get("display_label")
                or getattr(direct, "get_view_role_display", lambda: "")()
                or direct.view_role
            ),
            "current_status": direct.status,
            "will_discard_unapproved_preview": bool(
                getattr(direct, "asset_storage_name", "")
            ),
        })

    return {
        "planner_version": DYNAMIC_PLANNER_VERSION,
        "profile": profile.key,
        "available_count": len(actions),
        "actions": actions,
        "blocked": blocked,
        "supported_roles": selection["supported_roles"],
        "rule": (
            "Verified factual views replace only unapproved creative slots. "
            "Approved/attached media is never changed automatically."
        ),
    }


def _clear_generation_state(candidate):
    """Clear an unapproved creative preview before repurposing the same slot."""
    delete_review_asset(candidate)

    candidate.status = ImportMediaCandidate.STATUS_PLANNED
    candidate.asset_storage_alias = ""
    candidate.asset_storage_name = ""
    candidate.asset_original_name = ""
    candidate.provider_key = ""
    candidate.provider_asset_id = ""
    candidate.provider_response = {}
    candidate.generation_attempts = 0
    candidate.mime_type = ""
    candidate.width = None
    candidate.height = None
    candidate.file_size = None
    candidate.sha256 = ""
    candidate.generated_at = None
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
    candidate.last_error = ""

    metadata = dict(candidate.metadata or {})
    for key in (
        "generation_reference_trace",
        "generation_reference_history",
        "creative_text_grounding_trace",
    ):
        metadata.pop(key, None)
    candidate.metadata = metadata


def reconcile_existing_media_plan(item, *, actor=None):
    """Explicitly replace unapproved creative slots with newly verified views."""
    support = reference_support_report(item)
    report = dynamic_verified_slot_report(item, support=support)
    profile = get_media_profile(item)

    applied = []
    held = list(report.get("blocked") or [])

    for action in report.get("actions") or []:
        role = action["role"]
        candidate = (
            item.media_candidates.filter(
                pk=action["candidate_id"],
                kind=ImportMediaCandidate.KIND_GENERATION,
            )
            .first()
        )
        if candidate is None or not candidate_can_be_replaced(candidate):
            held.append({
                **action,
                "reason": "Candidate changed before reconciliation and is no longer replaceable.",
            })
            continue

        dynamic_slot = _dynamic_slot(role)
        old_metadata = dict(candidate.metadata or {})
        old_snapshot = {
            "candidate_id": candidate.pk,
            "old_view_role": candidate.view_role,
            "old_display_label": str(
                old_metadata.get("display_label")
                or getattr(candidate, "get_view_role_display", lambda: "")()
                or candidate.view_role
            ),
            "old_status": candidate.status,
            "old_provider_key": candidate.provider_key,
            "had_preview": bool(candidate.asset_storage_name),
        }

        with transaction.atomic():
            _clear_generation_state(candidate)

            candidate.view_role = role
            candidate.reference_urls = select_reference_urls(
                item,
                role,
                max_refs=5,
            )
            candidate.generation_prompt = (
                f"DYNAMIC VERIFIED FACTUAL SLOT: {dynamic_slot.label}. "
                f"{dynamic_slot.prompt} Human review is mandatory."
            )

            metadata = dynamic_slot_metadata(profile, dynamic_slot)
            metadata["superseded_creative_slot"] = {
                "slot_key": old_metadata.get("slot_key"),
                "display_label": old_snapshot["old_display_label"],
                "legacy_view_role": old_snapshot["old_view_role"],
            }
            candidate.metadata = metadata
            candidate.notes = (
                f"Phase {DYNAMIC_PLANNER_VERSION}: verified manufacturer evidence for "
                f"{dynamic_slot.label} replaced an unapproved creative slot. "
                "The old creative preview, if any, was discarded. Approved/attached "
                "media is never replaced by this operation."
            )

            candidate.save(update_fields=[
                "status",
                "view_role",
                "reference_urls",
                "generation_prompt",
                "provider_key",
                "provider_asset_id",
                "provider_response",
                "generation_attempts",
                "asset_storage_alias",
                "asset_storage_name",
                "asset_original_name",
                "mime_type",
                "width",
                "height",
                "file_size",
                "sha256",
                "generated_at",
                "exact_identity_verified",
                "source_identity_check_passed",
                "watermark_status",
                "rights_status",
                "selected_for_product",
                "reviewed_at",
                "approved_by",
                "approved_at",
                "rejected_by",
                "rejected_at",
                "rejection_reason",
                "last_error",
                "metadata",
                "notes",
                "updated_at",
            ])

            ImportAuditEvent.objects.create(
                item=item,
                event_type="dynamic_verified_media_slot_applied",
                message=(
                    f"{old_snapshot['old_display_label']} replaced by "
                    f"{dynamic_slot.label} using verified manufacturer evidence."
                )[:500],
                payload={
                    "planner_version": DYNAMIC_PLANNER_VERSION,
                    "actor_id": getattr(actor, "pk", None),
                    "role": role,
                    "candidate_id": candidate.pk,
                    "old": old_snapshot,
                    "new": {
                        "view_role": role,
                        "display_label": dynamic_slot.label,
                        "reference_count": len(candidate.reference_urls or []),
                    },
                },
            )

        applied.append({
            **action,
            "new_candidate_id": candidate.pk,
            "new_status": candidate.status,
            "new_label": dynamic_slot.label,
            "reference_count": len(candidate.reference_urls or []),
        })

    result = {
        "planner_version": DYNAMIC_PLANNER_VERSION,
        "applied_count": len(applied),
        "applied": applied,
        "held": held,
        "rule": report["rule"],
    }

    image_report = dict(item.image_report or {})
    image_report["dynamic_verified_slots"] = result
    item.image_report = image_report
    item.save(update_fields=["image_report", "updated_at"])

    return result
