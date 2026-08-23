"""Moderation hooks for deferred social publications."""

from django.db import transaction
from django.utils import timezone


def _release_after_commit(model, object_ids):
    object_ids = tuple(object_ids)
    if not object_ids:
        return

    def release():
        from .publisher import release_pending_instagram_publications

        release_pending_instagram_publications(model.objects.filter(pk__in=object_ids))

    transaction.on_commit(release)


@transaction.atomic
def approve_product_package(product, actor):
    """Approve a product and its pending videos as one moderation decision."""

    from products.models import ProductVideo

    now = timezone.now()
    product.approval_status = "approved"
    product.approved_by = actor
    product.approved_at = now
    product.is_active = True
    product.save(
        update_fields=["approval_status", "approved_by", "approved_at", "is_active", "updated_at"]
    )
    pending_video_ids = list(
        product.additional_videos.filter(moderation_status="pending").values_list("pk", flat=True)
    )
    ProductVideo.objects.filter(pk__in=pending_video_ids).update(
        moderation_status="approved", approved_by=actor, approved_at=now, is_active=True
    )
    # Include videos that an admin approved through an inline in the same form
    # submission. Their status is already approved by the time save_related
    # invokes this service, but their deferred publication still needs release.
    video_ids = list(
        product.additional_videos.filter(moderation_status="approved")
        .values_list("pk", flat=True)
    )
    _release_after_commit(ProductVideo, video_ids)
    return product


@transaction.atomic
def approve_product_video(video, actor, note=""):
    video.moderation_status = "approved"
    video.moderation_note = note
    video.approved_by = actor
    video.approved_at = timezone.now()
    video.is_active = True
    video.save(
        update_fields=[
            "moderation_status", "moderation_note", "approved_by", "approved_at",
            "is_active", "updated_at",
        ]
    )
    _release_after_commit(type(video), [video.pk])
    return video


@transaction.atomic
def approve_project_media_package(project, actor):
    """Approve pending project media and release its deferred publications."""

    from installers.models import ServiceProjectMedia

    now = timezone.now()
    media_ids = list(
        project.media_items.filter(approval_status=ServiceProjectMedia.STATUS_PENDING)
        .values_list("pk", flat=True)
    )
    ServiceProjectMedia.objects.filter(pk__in=media_ids).update(
        approval_status=ServiceProjectMedia.STATUS_APPROVED,
        moderation_note="",
        approved_by=actor,
        approved_at=now,
        is_active=True,
    )
    _release_after_commit(ServiceProjectMedia, media_ids)
    return media_ids


@transaction.atomic
def approve_project_media(media, actor):
    from installers.models import ServiceProjectMedia

    media.approval_status = ServiceProjectMedia.STATUS_APPROVED
    media.moderation_note = ""
    media.approved_by = actor
    media.approved_at = timezone.now()
    media.is_active = True
    media.save(
        update_fields=[
            "approval_status", "moderation_note", "approved_by", "approved_at",
            "is_active", "updated_at",
        ]
    )
    _release_after_commit(type(media), [media.pk])
    return media
