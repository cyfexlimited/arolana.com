from pathlib import Path

from django.core.files.base import ContentFile
from django.core.files.storage import storages
from django.db import transaction
from django.utils import timezone

from catalog_imports.models import ImportMediaCandidate
from .media_profiles import candidate_display_label


class MediaAttachmentError(Exception):
    pass


def _candidate_has_materialized_asset(candidate):
    return bool(
        str(getattr(candidate, "asset_storage_alias", "") or "").strip()
        and str(getattr(candidate, "asset_storage_name", "") or "").strip()
    )


def _candidate_is_safe(candidate):
    return bool(
        getattr(candidate, "kind", None) == ImportMediaCandidate.KIND_GENERATION
        and _candidate_has_materialized_asset(candidate)
        and bool(getattr(candidate, "selected_for_product", False))
        and getattr(candidate, "status", None) in {ImportMediaCandidate.STATUS_APPROVED, ImportMediaCandidate.STATUS_ATTACHED}
        and bool(getattr(candidate, "exact_identity_verified", False))
        and bool(getattr(candidate, "source_identity_check_passed", False))
        and getattr(candidate, "watermark_status", None) == ImportMediaCandidate.WATERMARK_CLEAR
        and getattr(candidate, "rights_status", None) == ImportMediaCandidate.RIGHTS_CONFIRMED
    )


def _read_candidate_bytes(candidate):
    alias = str(candidate.asset_storage_alias or "").strip()
    name = str(candidate.asset_storage_name or "").strip()
    if not alias or not name:
        raise MediaAttachmentError("Approved media has not been materialized into review storage yet.")
    try:
        storage = storages[alias]
    except Exception as exc:
        raise MediaAttachmentError(f"Unknown media storage alias: {alias}") from exc
    try:
        with storage.open(name, "rb") as handle:
            return handle.read()
    except Exception as exc:
        raise MediaAttachmentError(f"Could not read approved media asset from storage: {name}") from exc


def attach_approved_media(item):
    """Copy only explicitly approved generated media into existing Product media fields.

    Reference-only manufacturer images remain reference-only. Generated review
    assets must pass human identity/watermark/source-identity/rights checks before
    this service will copy them into ProductImage/main_image.
    """
    from products.models import Product, ProductImage
    with transaction.atomic():
        locked_item = (
            item.__class__.objects.select_for_update()
            .select_related("batch")
            .get(pk=item.pk)
        )
        if not locked_item.created_product_id:
            raise MediaAttachmentError("Prepare the Arolana Product draft before attaching media.")

        product = Product.objects.select_for_update().get(pk=locked_item.created_product_id)
        if getattr(product, "is_active", False):
            raise MediaAttachmentError("Importer media may only be attached while the Product remains inactive.")

        candidates = list(
            locked_item.media_candidates.filter(
                kind=ImportMediaCandidate.KIND_GENERATION,
                selected_for_product=True,
            )
            .select_for_update()
            .select_related("attached_product_image")
            .order_by("order", "id")
        )
        invalid = [candidate for candidate in candidates if not _candidate_is_safe(candidate)]
        if invalid:
            raise MediaAttachmentError(
                "Every selected image must be generated review media, Approved, exact-product verified, "
                "watermark-clear, retailer/source-identity-clear and usage-rights-confirmed."
            )

        candidates = candidates[: min(int(locked_item.batch.max_images or 10), 10)]
        if not candidates:
            raise MediaAttachmentError("No fully approved generated media candidates are selected for the Product.")

        seen_hashes = set()
        duplicates = []
        for candidate in candidates:
            digest = str(candidate.sha256 or "").strip()
            if digest and digest in seen_hashes and not candidate.attached_product_image_id:
                duplicates.append(candidate.pk)
            if digest:
                seen_hashes.add(digest)
        if duplicates:
            raise MediaAttachmentError(
                "Duplicate generated image content was detected in the selected gallery. Reject/regenerate duplicates first."
            )

        main_candidate = next(
            (candidate for candidate in candidates if candidate.view_role == ImportMediaCandidate.VIEW_MAIN),
            candidates[0],
        )
        attached = []
        for index, candidate in enumerate(candidates):
            if candidate.attached_product_image_id:
                attached.append(candidate.attached_product_image)
                continue

            raw = _read_candidate_bytes(candidate)
            source_name = candidate.asset_original_name or candidate.asset_storage_name
            suffix = Path(source_name).suffix.lower() or ".webp"
            is_main = candidate.pk == main_candidate.pk
            filename = f"import-{item.pk}-{candidate.view_role or candidate.pk}{suffix}"

            product_image = ProductImage(
                product=product,
                alt_text=f"{product.name} {candidate_display_label(candidate)}"[:200],
                is_main=is_main,
                order=index,
            )
            product_image.image.save(filename, ContentFile(raw), save=False)
            product_image.save()

            candidate.attached_product_image = product_image
            candidate.attached_at = timezone.now()
            candidate.status = ImportMediaCandidate.STATUS_ATTACHED
            candidate.save(update_fields=[
                "attached_product_image", "attached_at", "status", "updated_at"
            ])
            attached.append(product_image)

            if is_main and not product.main_image:
                main_filename = f"import-main-{item.pk}{suffix}"
                product.main_image.save(main_filename, ContentFile(raw), save=False)
                product.save()

        # Attachment must not publish or approve a Product.
        if getattr(product, "is_active", False):
            raise MediaAttachmentError("Safety check failed: Product became active during media attachment.")
        if str(getattr(product, "approval_status", "") or "").lower() not in {"", "draft"}:
            raise MediaAttachmentError("Safety check failed: Product approval state changed during media attachment.")

    return attached
