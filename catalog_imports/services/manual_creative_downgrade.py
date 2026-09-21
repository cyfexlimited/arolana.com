"""Phase 5.3.4 — Manual creative downgrade for weakly verified media.

A useful generated image may have references that are too weak to justify an
exact/factual requested-view claim. This action lets an admin REDUCE trust from
verified review to manual creative / unverified appearance without regenerating
the pixels or losing the immutable generation trace.
"""

from __future__ import annotations

from django.db import transaction

from catalog_imports.models import ImportAuditEvent, ImportMediaCandidate


DOWNGRADE_VERSION = "5.3.4"


class ManualCreativeDowngradeError(Exception):
    pass


def can_downgrade_to_manual_creative(candidate) -> bool:
    if candidate.kind != ImportMediaCandidate.KIND_GENERATION:
        return False
    if candidate.status not in {
        ImportMediaCandidate.STATUS_READY_REVIEW,
        ImportMediaCandidate.STATUS_APPROVED,
    }:
        return False
    if getattr(candidate, "attached_product_image_id", None):
        return False
    if not str(getattr(candidate, "asset_storage_name", "") or "").strip():
        return False

    response = candidate.provider_response or {}
    if response.get("_arolana_creative_fallback"):
        return False
    if response.get("_arolana_manual_creative_downgrade"):
        return False
    return True


def downgrade_to_manual_creative(candidate, *, actor=None, reason=""):
    if not can_downgrade_to_manual_creative(candidate):
        raise ManualCreativeDowngradeError(
            "Only an unattached generated candidate in Ready for review or "
            "Approved status can be downgraded to manual creative use."
        )

    clean_reason = str(reason or "").strip()[:1000]
    if not clean_reason:
        clean_reason = (
            "Official references are insufficient to verify the requested visual "
            "geometry, but the generated image is still useful as manually reviewed "
            "creative product media."
        )

    with transaction.atomic():
        response = dict(candidate.provider_response or {})
        response.update({
            "_arolana_creative_fallback": True,
            "_arolana_manual_creative_downgrade": True,
            "_arolana_accuracy_class": "manual_creative_unverified",
            "_arolana_requested_view_verified": False,
            "_arolana_factual_geometry_claim": False,
            "_arolana_ai_redraw": True,
            "_arolana_downgrade_version": DOWNGRADE_VERSION,
            "_arolana_downgrade_reason": clean_reason,
        })
        candidate.provider_response = response

        metadata = dict(candidate.metadata or {})
        history = list(metadata.get("manual_creative_downgrade_history") or [])
        history.append({
            "version": DOWNGRADE_VERSION,
            "reason": clean_reason,
            "previous_provider_key": candidate.provider_key,
            "previous_exact_identity_verified": bool(candidate.exact_identity_verified),
            "previous_source_identity_check_passed": bool(candidate.source_identity_check_passed),
        })
        metadata["manual_creative_downgrade_history"] = history[-20:]
        metadata["manual_creative_downgrade"] = {
            "version": DOWNGRADE_VERSION,
            "reason": clean_reason,
            "unverified_appearance": True,
            "requested_view_verified": False,
            "factual_geometry_claim": False,
        }
        candidate.metadata = metadata

        # Preserve the immutable generation/reference trace in metadata, but
        # remove the current exact visual-verification claim.  If this candidate
        # had already been approved as factual, return it to human review so the
        # creative acknowledgement is explicitly collected.
        candidate.exact_identity_verified = False
        candidate.selected_for_product = False
        candidate.status = ImportMediaCandidate.STATUS_READY_REVIEW
        candidate.approved_by = None
        candidate.approved_at = None

        if candidate.provider_key:
            if not candidate.provider_key.endswith("-manual-creative"):
                candidate.provider_key = (
                    candidate.provider_key + "-manual-creative"
                )
        else:
            candidate.provider_key = "manual-creative"

        candidate.notes = (
            (candidate.notes or "").strip()
            + "\n"
            + f"Phase {DOWNGRADE_VERSION}: manually downgraded to creative/"
              f"unverified appearance. Reason: {clean_reason}"
        ).strip()

        candidate.save(update_fields=[
            "provider_response",
            "metadata",
            "exact_identity_verified",
            "selected_for_product",
            "status",
            "approved_by",
            "approved_at",
            "provider_key",
            "notes",
            "updated_at",
        ])

        ImportAuditEvent.objects.create(
            item=candidate.item,
            event_type="media_candidate_manual_creative_downgrade",
            message=(
                f"{candidate.get_view_role_display()} downgraded from verified "
                "review to manual creative/unverified appearance."
            )[:500],
            payload={
                "version": DOWNGRADE_VERSION,
                "candidate_id": candidate.pk,
                "view_role": candidate.view_role,
                "reason": clean_reason,
                "actor_id": getattr(actor, "pk", None),
                "generation_reference_trace_preserved": bool(
                    (candidate.metadata or {}).get("generation_reference_trace")
                ),
            },
        )

    return candidate
