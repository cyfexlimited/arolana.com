from dataclasses import dataclass

from django.conf import settings
from django.utils import timezone

from subscriptions.lifecycle import get_effective_subscription

from .models import SocialAccount, SocialConnectionStatus, SocialOwnerRole, SocialPlatform


DEFAULT_SOCIAL_PUBLISHING_TIERS = {"pro", "special", "enterprise"}


@dataclass(frozen=True)
class SocialPublishingAccess:
    allowed: bool
    role: str
    tier: str
    reason: str = ""


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
