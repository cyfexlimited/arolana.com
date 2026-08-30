from dataclasses import dataclass
import re
from urllib.parse import urlparse

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from subscriptions.lifecycle import get_effective_subscription

from .models import (
    PublicationStatus,
    SocialAccount,
    SocialConnectionStatus,
    SocialOwnerRole,
    SocialPlatform,
    SocialPublication,
)


DEFAULT_SOCIAL_PUBLISHING_TIERS = {"pro", "special", "enterprise"}
_SAFE_EXTERNAL_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,255}$")


@dataclass(frozen=True)
class SocialPublishingAccess:
    allowed: bool
    role: str
    tier: str
    reason: str = ""


def publication_summary_for_content(content_object, *, platform, owner_user_id=None, owner_role=""):
    """Return a credential-free publication summary for an owned content object.

    This deliberately excludes request/response metadata and provider messages so
    mobile clients can render moderation/publication state without receiving
    encrypted credentials, raw Graph responses, or staging details.
    """
    if content_object is None or not getattr(content_object, "pk", None):
        return None
    content_type = ContentType.objects.get_for_model(
        content_object, for_concrete_model=False
    )
    publications = SocialPublication.objects.filter(
        platform=platform,
        content_type=content_type,
        object_id=content_object.pk,
    )
    if owner_user_id:
        publications = publications.filter(owner_user_id=owner_user_id)
    if owner_role:
        publications = publications.filter(owner_role=owner_role)
    publication = publications.order_by("-updated_at", "-pk").first()
    if publication is None:
        return None

    external_url = str(publication.external_url or "").strip()
    parsed = urlparse(external_url)
    hostname = (parsed.hostname or "").lower()
    safe_permalink = (
        external_url
        if parsed.scheme == "https"
        and (hostname == "facebook.com" or hostname.endswith(".facebook.com"))
        else ""
    )
    external_id = str(publication.external_id or "").strip()
    safe_external_id = external_id if _SAFE_EXTERNAL_ID.fullmatch(external_id) else ""
    metadata = publication.response_metadata or {}
    post_id = str(metadata.get("facebook_post_id") or "").strip()
    safe_post_id = post_id if _SAFE_EXTERNAL_ID.fullmatch(post_id) else ""
    failed = publication.status == PublicationStatus.FAILED
    return {
        "publication_id": publication.pk,
        "exists": True,
        "status": publication.status,
        "facebook_video_id": safe_external_id,
        "facebook_post_id": safe_post_id,
        "facebook_permalink": safe_permalink,
        "awaiting_moderation": bool(
            publication.status == PublicationStatus.PENDING
            and (publication.request_metadata or {}).get("awaiting_moderation")
        ),
        "attempt_count": int(publication.attempt_count or 0),
        "retry_available": bool(
            failed and publication.deferred_video_lease_id
        ),
        "error_message": (
            "Facebook publication could not be completed."
            if failed
            else ""
        ),
        "last_attempt_at": (
            publication.last_attempt_at.isoformat()
            if publication.last_attempt_at else ""
        ),
        "next_retry_at": (
            publication.next_retry_at.isoformat()
            if publication.next_retry_at else ""
        ),
    }


def normalize_owner_role(role):
    role = str(role or "").strip().lower()
    aliases = {
        "installer": SocialOwnerRole.PROVIDER,
        "engineer": SocialOwnerRole.PROVIDER,
        "service_provider": SocialOwnerRole.PROVIDER,
        "staff": SocialOwnerRole.ADMIN,
    }
    role = aliases.get(role, role)
    if role not in {SocialOwnerRole.VENDOR, SocialOwnerRole.PROVIDER, SocialOwnerRole.ADMIN}:
        raise ValueError("Unsupported social publishing owner role.")
    return role


def social_publishing_access(user, role):
    role = normalize_owner_role(role)
    if role == SocialOwnerRole.ADMIN:
        allowed = bool(getattr(user, "is_staff", False) or getattr(user, "is_superuser", False))
        return SocialPublishingAccess(allowed, role, "admin", "" if allowed else "Staff access is required.")

    effective = get_effective_subscription(user, role_context=role)
    explicit = effective.entitlements.get("social_publishing")
    if explicit is None:
        explicit = effective.tier in DEFAULT_SOCIAL_PUBLISHING_TIERS
    allowed = bool(explicit)
    reason = "" if allowed else "Social publishing is not included in your current subscription plan."
    return SocialPublishingAccess(allowed, role, effective.tier, reason)


def connected_platforms(user, role):
    role = normalize_owner_role(role)
    return set(
        SocialAccount.objects.filter(
            user=user,
            owner_role=role,
            status=SocialConnectionStatus.CONNECTED,
        ).values_list("platform", flat=True)
    )


def ensure_instagram_account_identity(account):
    """Populate a legacy connected account's safe display identity once."""
    if (
        not account
        or account.platform != SocialPlatform.INSTAGRAM
        or not account.is_connected
        or account.account_username
        or not account.access_token_encrypted
    ):
        return account

    try:
        from .instagram import verify_instagram_account
        from .oauth import instagram_identity_from_profile

        profile = verify_instagram_account(account)
        identity = instagram_identity_from_profile(profile, account.external_account_id)
        account.external_account_id = identity["external_account_id"]
        account.account_name = identity["account_name"]
        account.account_username = identity["account_username"]
        account.platform_metadata = {
            **(account.platform_metadata or {}),
            **identity["platform_metadata"],
        }
        account.last_verified_at = timezone.now()
        account.save(update_fields=[
            "external_account_id",
            "account_name",
            "account_username",
            "platform_metadata",
            "last_verified_at",
            "updated_at",
        ])
    except Exception:
        # Identity is presentation-only; connection and publishing stay usable.
        return account
    return account


def platform_enabled(platform):
    """Publishing capability gate. Facebook connection never implies publishing."""
    platform = str(platform or "").strip().lower()
    if platform == SocialPlatform.YOUTUBE:
        return True
    if not bool(getattr(settings, "SOCIAL_PUBLISHING_ENABLED", False)):
        return False
    if platform == SocialPlatform.FACEBOOK:
        return bool(getattr(settings, "SOCIAL_PUBLISHING_FACEBOOK_PUBLISHING_ENABLED", False))
    return bool(getattr(settings, f"SOCIAL_PUBLISHING_{platform.upper()}_ENABLED", False))


def platform_connection_enabled(platform):
    platform = str(platform or "").strip().lower()
    if platform == SocialPlatform.YOUTUBE:
        return False
    if not bool(getattr(settings, "SOCIAL_PUBLISHING_ENABLED", False)):
        return False
    if platform == SocialPlatform.FACEBOOK:
        return bool(getattr(settings, "SOCIAL_PUBLISHING_FACEBOOK_CONNECTION_ENABLED", False))
    return bool(getattr(settings, f"SOCIAL_PUBLISHING_{platform.upper()}_ENABLED", False))


def facebook_page_publishing_ready(account):
    """Whether a connected Page has the minimum stored grant to publish."""
    if (
        not account
        or account.platform != SocialPlatform.FACEBOOK
        or not account.is_connected
        or not account.external_account_id
        or not account.access_token_encrypted
    ):
        return False
    scopes = account.scopes or []
    if isinstance(scopes, str):
        scopes = scopes.replace(",", " ").split()
    return "pages_manage_posts" in {
        str(scope or "").strip().lower() for scope in scopes
    }
