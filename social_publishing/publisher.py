"""Shared orchestration for publishing temporary videos to Instagram."""

import re
from urllib.parse import urlparse

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


def _prepare_publication(*, user, owner_role, account, content_type, object_id, share_to_feed):
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

        publication.social_account = account
        publication.status = PublicationStatus.UPLOADING
        publication.attempt_count += 1
        publication.last_attempt_at = timezone.now()
        publication.error_code = ""
        publication.error_message = ""
        publication.request_metadata = {"share_to_feed": bool(share_to_feed)}
        publication.response_metadata = {}
        publication.save(
            update_fields=[
                "social_account",
                "status",
                "attempt_count",
                "last_attempt_at",
                "error_code",
                "error_message",
                "request_metadata",
                "response_metadata",
                "updated_at",
            ]
        )
    return publication


def publish_uploaded_video_to_instagram(
    *, user, owner_role, content_object, uploaded_file, caption="", share_to_feed=True
):
    """Publish one uploaded video through the user's role-bound Instagram account.

    The uploaded file is staged only for the duration of this call. The returned
    value is the persisted ``SocialPublication``.
    """

    owner_role = normalize_owner_role(owner_role)
    access = social_publishing_access(user, owner_role)
    if not access.allowed:
        raise InstagramPublicationError(
            access.reason or "Social publishing is not available.",
            code="social_publishing_access_denied",
        )
    if not platform_enabled(SocialPlatform.INSTAGRAM):
        raise InstagramPublicationError(
            "Instagram publishing is not enabled.",
            code="instagram_publishing_disabled",
        )

    content_type, object_id = _content_identity(content_object)
    account = _connected_instagram_account(user, owner_role)
    publication = _prepare_publication(
        user=user,
        owner_role=owner_role,
        account=account,
        content_type=content_type,
        object_id=object_id,
        share_to_feed=share_to_feed,
    )

    lease = None
    try:
        if not _content_is_approved_for_distribution(content_type, content_object):
            raise InstagramPublicationError(
                "This video is awaiting Arolana approval before external publishing.",
                code="content_awaiting_moderation",
                publication=publication,
            )
        lease = stage_video_for_social(
            owner_user=user,
            owner_role=owner_role,
            uploaded_file=uploaded_file,
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
        result = publish_reel(
            account,
            video_url=video_url,
            caption=str(caption or ""),
            share_to_feed=bool(share_to_feed),
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
                "status",
                "external_id",
                "external_url",
                "published_at",
                "error_code",
                "error_message",
                "response_metadata",
                "updated_at",
            ]
        )
        return publication
    except Exception as exc:
        if str(getattr(exc, "error_code", "")) == "190":
            account.status = SocialConnectionStatus.EXPIRED
            account.last_error = "Instagram authorization expired. Reauthorization is required."
            account.save(update_fields=["status", "last_error", "updated_at"])
        safe_code = exc.code if isinstance(exc, InstagramPublicationError) else _safe_error_code(exc)
        safe_message = _safe_error_message(exc)
        publication.status = PublicationStatus.FAILED
        publication.error_code = safe_code
        publication.error_message = safe_message
        publication.save(
            update_fields=["status", "error_code", "error_message", "updated_at"]
        )
        if isinstance(exc, InstagramPublicationError):
            exc.args = (safe_message,)
            exc.publication = publication
            raise
        raise InstagramPublicationError(
            safe_message,
            code=safe_code,
            publication=publication,
        ) from exc
    finally:
        if lease is not None:
            cleanup_video_lease(lease)
