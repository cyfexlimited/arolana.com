from catalog_imports.models import ImportMediaCandidate

from .media_storage import review_asset_exists


class MediaValidationError(ValueError):
    pass


def validate_materialized_candidate(candidate):
    errors = []
    if candidate.kind != ImportMediaCandidate.KIND_GENERATION:
        errors.append("Only generation jobs may become generated review candidates.")
    if not review_asset_exists(candidate):
        errors.append("Generated review asset is missing from configured storage.")
    if not candidate.sha256 or len(candidate.sha256) != 64:
        errors.append("Generated asset SHA-256 is missing.")
    if not candidate.width or not candidate.height:
        errors.append("Generated asset dimensions are missing.")
    if candidate.width != candidate.height:
        errors.append("Generated marketplace asset must be square.")
    if candidate.mime_type not in {"image/webp", "image/png", "image/jpeg"}:
        errors.append("Unsupported generated image MIME type.")
    return errors


def duplicate_hash_exists(candidate):
    if not candidate.sha256:
        return False
    return candidate.item.media_candidates.exclude(pk=candidate.pk).filter(
        sha256=candidate.sha256,
        status__in=[
            ImportMediaCandidate.STATUS_READY_REVIEW,
            ImportMediaCandidate.STATUS_APPROVED,
            ImportMediaCandidate.STATUS_ATTACHED,
        ],
    ).exists()
