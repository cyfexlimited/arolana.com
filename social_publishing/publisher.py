"""Shared orchestration for publishing temporary videos to Instagram."""

import re
from urllib.parse import urlparse

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from .instagram import publish_reel
from .models import (
    PublicationStatus,
    SocialAccount,
    SocialConnectionStatus,
    SocialPlatform,
    SocialPublication,
)
from .oauth import InstagramTokenLifecycleError, refresh_instagram_account_if_needed
from .services import normalize_owner_role, platform_enabled, social_publishing_access
from .video_staging import (
    cleanup_video_lease,
    get_video_delivery_url,
    stage_video_for_social,
)


_SECRET_PATTERNS = (
    re.compile(r"(?i)(access[_ -]?token|refresh[_ -]?token|client[_ -]?secret)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"(?i)(authorization)\s*:\s*bearer\s+[^\s,;]+"),
)
_SAFE_CODE_PATTERN = re.compile(r"[^A-Za-z0-9_.:-]+")


class InstagramPublicationError(Exception):
    """A safe, caller-facing failure from Instagram publication orchestration."""

    def __init__(self, message, *, code="instagram_publish_failed", publication=None):
        super().__init__(message)
        self.code = code
        self.publication = publication


def _safe_error_message(exc):
    message = " ".join(str(exc or "Instagram publishing failed.").split())
    for pattern in _SECRET_PATTERNS:
        message = pattern.sub(lambda match: f"{match.group(1)}=[redacted]", message)
    return message[:1000] or "Instagram publishing failed."


def _safe_error_code(exc):
    code = getattr(exc, "error_code", "") or "instagram_publish_failed"
    code = _SAFE_CODE_PATTERN.sub("_", str(code)).strip("_")
    return code[:120] or "instagram_publish_failed"


def _content_identity(content_object):
    if content_object is None or getattr(content_object, "pk", None) is None:
        raise InstagramPublicationError(
            "Published content must be a saved object.",
            code="invalid_content_object",
        )
    return (
        ContentType.objects.get_for_model(content_object, for_concrete_model=False),
        content_object.pk,
    )


def _content_is_approved_for_distribution(content_type, content_object):
    """Keep external distribution behind existing Arolana video moderation."""

    label = f"{content_type.app_label}.{content_type.model}"
    if label == "products.productvideo":
        return getattr(content_object, "moderation_status", "") == "approved"
    if label == "installers.serviceprojectmedia":
        return getattr(content_object, "approval_status", "") == "approved"
    return True


def _connected_instagram_account(user, owner_role):
    try:
        account = SocialAccount.objects.get(
            user=user,
            owner_role=owner_role,
            platform=SocialPlatform.INSTAGRAM,
            status=SocialConnectionStatus.CONNECTED,
        )
    except SocialAccount.DoesNotExist as exc:
        raise InstagramPublicationError(
            "A connected Instagram account is required.",
            code="instagram_not_connected",
        ) from exc

    try:
        account = refresh_instagram_account_if_needed(account)
    except InstagramTokenLifecycleError as exc:
        raise InstagramPublicationError(
            "The connected Instagram account requires reauthorization.",
            code="instagram_reauthorization_required",
        ) from exc

    if not account.is_connected:
        raise InstagramPublicationError(
            "The connected Instagram account requires reauthorization.",
            code="instagram_reauthorization_required",
        )
    return account


def _prepare_publication(
    *, user, owner_role, account, content_type, object_id, share_to_feed, caption=""
):
    with transaction.atomic():
        publication, _created = SocialPublication.objects.select_for_update().get_or_create(
            owner_user=user,
            owner_role=owner_role,
            platform=SocialPlatform.INSTAGRAM,
            content_type=content_type,
            object_id=object_id,
            defaults={"social_account": account},
        )
        if publication.status == PublicationStatus.PUBLISHED:
            raise InstagramPublicationError(
                "This content has already been published to Instagram.",
                code="already_published",
                publication=publication,
            )
        if publication.status in {
            PublicationStatus.UPLOADING,
            PublicationStatus.PROCESSING,
        }:
            raise InstagramPublicationError(
                "This content is already being published to Instagram.",
                code="publish_in_progress",
                publication=publication,
            )

        if account is not None:
            publication.social_account = account
        publication.status = PublicationStatus.UPLOADING
        publication.attempt_count += 1
        publication.last_attempt_at = timezone.now()
        publication.error_code = ""
        publication.error_message = ""
        publication.request_metadata = {
            "share_to_feed": bool(share_to_feed),
            "caption": str(caption or "")[:2200],
        }
        publication.response_metadata = {}
        update_fields = [
                "status",
                "attempt_count",
                "last_attempt_at",
                "error_code",
                "error_message",
                "request_metadata",
                "response_metadata",
                "updated_at",
        ]
        if account is not None:
            update_fields.insert(0, "social_account")
        publication.save(update_fields=update_fields)
    return publication


def _deferred_lease_minutes():
    days = max(1, int(getattr(settings, "SOCIAL_PUBLISHING_MODERATION_LEASE_DAYS", 30)))
    return days * 24 * 60


def _stage_publication_source(publication, uploaded_file):
    old_lease = publication.deferred_video_lease
    if old_lease and not old_lease.cleanup_completed_at:
        cleanup_video_lease(old_lease)
    if hasattr(uploaded_file, "seek"):
        uploaded_file.seek(0)
    lease = stage_video_for_social(
        owner_user=publication.owner_user,
        owner_role=publication.owner_role,
        uploaded_file=uploaded_file,
        lease_minutes=_deferred_lease_minutes(),
    )
    publication.deferred_video_lease = lease
    publication.save(update_fields=["deferred_video_lease", "updated_at"])
    return lease


def _mark_publication_failure(publication, exc, account=None):
    if account is not None and str(getattr(exc, "error_code", "")) == "190":
        account.status = SocialConnectionStatus.EXPIRED
        account.last_error = "Instagram authorization expired. Reauthorization is required."
        account.save(update_fields=["status", "last_error", "updated_at"])
    safe_code = exc.code if isinstance(exc, InstagramPublicationError) else _safe_error_code(exc)
    safe_message = _safe_error_message(exc)
    publication.status = PublicationStatus.FAILED
    publication.error_code = safe_code
    publication.error_message = safe_message
    publication.save(update_fields=["status", "error_code", "error_message", "updated_at"])
    return safe_code, safe_message


def _publish_from_deferred_source(publication, account):
    lease = publication.deferred_video_lease
    if lease is None or lease.cleanup_completed_at or lease.is_expired:
        raise InstagramPublicationError(
            "The temporary Instagram source is no longer available.",
            code="deferred_video_unavailable",
            publication=publication,
        )
    video_url = str(get_video_delivery_url(lease) or "").strip()
    parsed_video_url = urlparse(video_url)
    if parsed_video_url.scheme.lower() != "https" or not parsed_video_url.netloc:
        raise InstagramPublicationError(
            "Instagram video delivery requires HTTPS.",
            code="https_video_url_required",
            publication=publication,
        )

    publication.status = PublicationStatus.PROCESSING
    publication.save(update_fields=["status", "updated_at"])
    metadata = publication.request_metadata or {}
    result = publish_reel(
        account,
        video_url=video_url,
        caption=str(metadata.get("caption") or "")[:2200],
        share_to_feed=bool(metadata.get("share_to_feed", True)),
    )
    media_id = str(result.get("media_id") or "").strip()
    if not media_id:
        raise InstagramPublicationError(
            "Instagram returned no media ID.",
            code="instagram_media_id_missing",
            publication=publication,
        )

    publication.status = PublicationStatus.PUBLISHED
    publication.external_id = media_id
    publication.external_url = str(result.get("permalink") or "").strip()
    publication.published_at = timezone.now()
    publication.error_code = ""
    publication.error_message = ""
    publication.response_metadata = {
        "container_id": str(result.get("container_id") or "").strip(),
        "media_id": media_id,
    }
    publication.save(
        update_fields=[
            "status", "external_id", "external_url", "published_at",
            "error_code", "error_message", "response_metadata", "updated_at",
        ]
    )
    cleanup_video_lease(lease)
    return publication


def publish_uploaded_video_to_instagram(
    *, user, owner_role, content_object, uploaded_file, caption="", share_to_feed=True
):
    """Publish one uploaded video through the user's role-bound Instagram account.

    The uploaded file is staged only for the duration of this call. The returned
    value is the persisted ``SocialPublication``. Pending moderation retains a
    bounded temporary source lease so approval can continue automatically.
    """

    owner_role = normalize_owner_role(owner_role)
    content_type, object_id = _content_identity(content_object)
    publication = _prepare_publication(
        user=user,
        owner_role=owner_role,
        account=None,
        content_type=content_type,
        object_id=object_id,
        share_to_feed=share_to_feed,
        caption=caption,
    )

    account = None
    try:
        access = social_publishing_access(user, owner_role)
        if not access.allowed:
            raise InstagramPublicationError(
                access.reason or "Social publishing is not available.",
                code="social_publishing_access_denied",
                publication=publication,
            )
        if not platform_enabled(SocialPlatform.INSTAGRAM):
            raise InstagramPublicationError(
                "Instagram publishing is not enabled.",
                code="instagram_publishing_disabled",
                publication=publication,
            )

        account = _connected_instagram_account(user, owner_role)
        publication.social_account = account
        publication.save(update_fields=["social_account", "updated_at"])

        if not _content_is_approved_for_distribution(content_type, content_object):
            _stage_publication_source(publication, uploaded_file)
            publication.status = PublicationStatus.PENDING
            publication.error_code = ""
            publication.error_message = ""
            publication.request_metadata = {
                **(publication.request_metadata or {}),
                "awaiting_moderation": True,
            }
            publication.save(
                update_fields=[
                    "status", "error_code", "error_message",
                    "request_metadata", "updated_at",
                ]
            )
            return publication

        if publication.deferred_video_lease is None:
            _stage_publication_source(publication, uploaded_file)
        publication.request_metadata = {
            **(publication.request_metadata or {}),
            "awaiting_moderation": False,
        }
        publication.save(update_fields=["request_metadata", "updated_at"])
        return _publish_from_deferred_source(publication, account)
    except Exception as exc:
        safe_code, safe_message = _mark_publication_failure(publication, exc, account)
        if isinstance(exc, InstagramPublicationError):
            exc.args = (safe_message,)
            exc.publication = publication
            raise
        raise InstagramPublicationError(
            safe_message,
            code=safe_code,
            publication=publication,
        ) from exc


def continue_deferred_instagram_publication(publication):
    """Release one approved, moderation-pending publication without new upload bytes."""

    with transaction.atomic():
        publication = (
            SocialPublication.objects.select_for_update()
            .select_related("owner_user", "deferred_video_lease")
            .get(pk=publication.pk)
        )
        if publication.status == PublicationStatus.PUBLISHED:
            return publication
        if publication.status in {PublicationStatus.UPLOADING, PublicationStatus.PROCESSING}:
            return publication
        content_object = publication.content_object
        if content_object is None or not _content_is_approved_for_distribution(
            publication.content_type, content_object
        ):
            return publication
        publication.status = PublicationStatus.UPLOADING
        publication.attempt_count += 1
        publication.last_attempt_at = timezone.now()
        publication.error_code = ""
        publication.error_message = ""
        publication.request_metadata = {
            **(publication.request_metadata or {}),
            "awaiting_moderation": False,
        }
        publication.save(
            update_fields=[
                "status", "attempt_count", "last_attempt_at", "error_code", "error_message",
                "request_metadata", "updated_at",
            ]
        )

    account = None
    try:
        access = social_publishing_access(publication.owner_user, publication.owner_role)
        if not access.allowed:
            raise InstagramPublicationError(
                access.reason or "Social publishing is not available.",
                code="social_publishing_access_denied",
                publication=publication,
            )
        if not platform_enabled(SocialPlatform.INSTAGRAM):
            raise InstagramPublicationError(
                "Instagram publishing is not enabled.",
                code="instagram_publishing_disabled",
                publication=publication,
            )
        account = _connected_instagram_account(publication.owner_user, publication.owner_role)
        publication.social_account = account
        publication.save(update_fields=["social_account", "updated_at"])
        return _publish_from_deferred_source(publication, account)
    except Exception as exc:
        safe_code, safe_message = _mark_publication_failure(publication, exc, account)
        if isinstance(exc, InstagramPublicationError):
            exc.args = (safe_message,)
            exc.publication = publication
            raise
        raise InstagramPublicationError(
            safe_message, code=safe_code, publication=publication
        ) from exc


def release_pending_instagram_publications(content_objects):
    """Best-effort post-approval release; moderation success is never rolled back."""

    released = []
    for content_object in content_objects:
        content_type, object_id = _content_identity(content_object)
        publications = SocialPublication.objects.filter(
            platform=SocialPlatform.INSTAGRAM,
            content_type=content_type,
            object_id=object_id,
            status=PublicationStatus.PENDING,
            deferred_video_lease__isnull=False,
        )
        for publication in publications:
            try:
                released.append(continue_deferred_instagram_publication(publication))
            except InstagramPublicationError:
                released.append(SocialPublication.objects.get(pk=publication.pk))
    return released


def cleanup_orphaned_pending_instagram_publications():
    """Fail closed and clean temporary sources whose content was deleted."""

    cleaned = 0
    publications = SocialPublication.objects.filter(
        platform=SocialPlatform.INSTAGRAM,
        status=PublicationStatus.PENDING,
        deferred_video_lease__isnull=False,
    ).select_related("deferred_video_lease")
    for publication in publications:
        if publication.content_object is not None:
            continue
        lease = publication.deferred_video_lease
        cleanup_video_lease(lease)
        publication.status = PublicationStatus.FAILED
        publication.error_code = "content_deleted"
        publication.error_message = "The content for this publication is no longer available."
        publication.save(
            update_fields=["status", "error_code", "error_message", "updated_at"]
        )
        cleaned += 1
    return cleaned
