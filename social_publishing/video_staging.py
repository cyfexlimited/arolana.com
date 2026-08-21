import os
import uuid
from datetime import timedelta

from django.core.files.storage import default_storage
from django.utils import timezone

from .models import TemporaryVideoLease


DEFAULT_LEASE_MINUTES = 60


def _safe_filename(filename):
    filename = os.path.basename(str(filename or "video.mp4")).strip()
    return filename or "video.mp4"


def stage_video_for_social(
    *,
    owner_user,
    owner_role,
    uploaded_file,
    lease_minutes=DEFAULT_LEASE_MINUTES,
):
    """
    Temporarily stage a video in Django's configured default storage.
    """

    if uploaded_file is None:
        raise ValueError("uploaded_file is required.")

    filename = _safe_filename(
        getattr(uploaded_file, "name", "video.mp4")
    )

    extension = os.path.splitext(filename)[1].lower() or ".mp4"

    storage_key = (
        "social-publishing/temp-video/"
        f"{owner_user.pk}/"
        f"{uuid.uuid4().hex}{extension}"
    )

    saved_key = default_storage.save(
        storage_key,
        uploaded_file,
    )

    try:
        lease = TemporaryVideoLease.objects.create(
            owner_user=owner_user,
            owner_role=owner_role,
            storage_key=saved_key,
            original_filename=filename,
            file_size=getattr(uploaded_file, "size", 0) or 0,
            mime_type=getattr(
                uploaded_file,
                "content_type",
                "",
            ) or "",
            expires_at=timezone.now()
            + timedelta(minutes=lease_minutes),
        )
    except Exception:
        default_storage.delete(saved_key)
        raise

    return lease


def get_video_delivery_url(lease, *, expire=3600):
    """
    Return a temporary URL for the staged video.
    """

    if lease.cleanup_completed_at:
        raise ValueError(
            "Temporary video has already been cleaned up."
        )

    if lease.is_expired:
        raise ValueError(
            "Temporary video lease has expired."
        )

    try:
        return default_storage.url(
            lease.storage_key,
            expire=expire,
            http_method="GET",
        )
    except TypeError:
        return default_storage.url(
            lease.storage_key
        )


def cleanup_video_lease(lease):
    """
    Delete the staged video and mark its lease cleaned.
    """

    if lease.cleanup_completed_at:
        return True

    try:
        if default_storage.exists(lease.storage_key):
            default_storage.delete(lease.storage_key)

        lease.cleanup_completed_at = timezone.now()
        lease.cleanup_error = ""

        lease.save(
            update_fields=[
                "cleanup_completed_at",
                "cleanup_error",
                "updated_at",
            ]
        )

        return True

    except Exception as exc:
        lease.cleanup_error = str(exc)[:4000]

        lease.save(
            update_fields=[
                "cleanup_error",
                "updated_at",
            ]
        )

        return False