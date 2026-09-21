from django.utils import timezone

from catalog_imports.models import ImportMediaCandidate

from .media_storage import delete_review_asset, review_asset_exists
from .media_validation import duplicate_hash_exists
from .media_creative_fallback import is_creative_fallback_candidate
from .media_references import reference_support_for_view


class MediaReviewError(ValueError):
    pass


def approve_candidate(
    candidate,
    *,
    actor,
    exact_identity_verified,
    watermark_clear,
    source_identity_clear,
    rights_confirmed,
    creative_fallback_ack=False,
):
    if candidate.kind != ImportMediaCandidate.KIND_GENERATION:
        raise MediaReviewError("Reference-only media cannot be approved as Product media.")
    if candidate.status != ImportMediaCandidate.STATUS_READY_REVIEW:
        raise MediaReviewError("Only generated media waiting for review can be approved.")
    if not review_asset_exists(candidate):
        raise MediaReviewError("Generated review asset is missing.")
    if not exact_identity_verified:
        raise MediaReviewError("Confirm that this is the exact verified product before approval.")
    if not watermark_clear:
        raise MediaReviewError("Confirm that no watermark is visible before approval.")
    if not source_identity_clear:
        raise MediaReviewError("Confirm that no retailer/source identity or seller overlay is present before approval.")
    if not rights_confirmed:
        raise MediaReviewError("Usage rights confirmation is required before approval.")

    # Legacy candidates created before provider_response existed remain valid
    # inputs. Missing metadata is treated as empty, never as creative or
    # factual proof; the existing role/trust gates still apply below.
    provider_response = getattr(candidate, "provider_response", None) or {}
    creative = is_creative_fallback_candidate(candidate)

    # Main/Hero may use exact identity references. Every other factual
    # manufacturer-verified claim now requires a pixel-classified reference for
    # the same requested role. Identity-only references may still support the
    # explicitly labelled creative fallback path.
    if (
        not creative
        and getattr(candidate, "view_role", ImportMediaCandidate.VIEW_MAIN) != ImportMediaCandidate.VIEW_MAIN
    ):
        support = reference_support_for_view(candidate.item, candidate.view_role)
        if not support.get("supported"):
            raise MediaReviewError(
                "This factual view does not have a visually role-matched official "
                "manufacturer reference. Regenerate after stronger evidence is "
                "found, or downgrade this candidate to creative/unverified "
                "appearance before approval."
            )

    if provider_response.get("_arolana_creative_fallback") and not creative_fallback_ack:
        raise MediaReviewError(
            "Creative fallback requires explicit confirmation that the requested "
            "perspective/geometry is unverified and has been manually checked or edited before Product use."
        )

    if duplicate_hash_exists(candidate):
        raise MediaReviewError("This image duplicates another generated candidate for the same item.")

    now = timezone.now()
    candidate.exact_identity_verified = True
    candidate.watermark_status = ImportMediaCandidate.WATERMARK_CLEAR
    candidate.source_identity_check_passed = True
    candidate.rights_status = ImportMediaCandidate.RIGHTS_CONFIRMED
    candidate.selected_for_product = True
    candidate.status = ImportMediaCandidate.STATUS_APPROVED
    candidate.reviewed_at = now
    candidate.approved_by = actor
    candidate.approved_at = now
    candidate.rejected_by = None
    candidate.rejected_at = None
    candidate.rejection_reason = ""
    candidate.last_error = ""
    candidate.save()
    return candidate


def reject_candidate(candidate, *, actor, reason=""):
    if candidate.kind != ImportMediaCandidate.KIND_GENERATION:
        raise MediaReviewError("Reference-only media is not part of the approval queue.")
    if candidate.status not in {
        ImportMediaCandidate.STATUS_READY_REVIEW,
        ImportMediaCandidate.STATUS_APPROVED,
    }:
        raise MediaReviewError("Only generated/reviewed media can be rejected.")
    now = timezone.now()
    candidate.status = ImportMediaCandidate.STATUS_REJECTED
    candidate.selected_for_product = False
    candidate.exact_identity_verified = False
    candidate.source_identity_check_passed = False
    candidate.watermark_status = ImportMediaCandidate.WATERMARK_UNKNOWN
    candidate.rights_status = ImportMediaCandidate.RIGHTS_UNKNOWN
    candidate.reviewed_at = now
    candidate.approved_by = None
    candidate.approved_at = None
    candidate.rejected_by = actor
    candidate.rejected_at = now
    candidate.rejection_reason = str(reason or "Rejected during media review.")
    candidate.save()
    return candidate


def reset_candidate_for_retry(candidate, *, actor=None):
    if candidate.kind != ImportMediaCandidate.KIND_GENERATION:
        raise MediaReviewError("Reference-only media cannot be regenerated.")
    if candidate.status == ImportMediaCandidate.STATUS_ATTACHED:
        raise MediaReviewError("Attached Product media cannot be regenerated from the importer review queue.")
    delete_review_asset(candidate)
    candidate.status = ImportMediaCandidate.STATUS_PLANNED
    candidate.asset_storage_alias = ""
    candidate.asset_storage_name = ""
    candidate.asset_original_name = ""
    candidate.mime_type = ""
    candidate.width = None
    candidate.height = None
    candidate.file_size = None
    candidate.sha256 = ""
    candidate.generated_at = None
    candidate.provider_asset_id = ""
    candidate.provider_response = {}
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
    candidate.save()
    return candidate
