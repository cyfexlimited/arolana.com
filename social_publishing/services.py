from dataclasses import dataclass

from django.conf import settings

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


def platform_enabled(platform):
    platform = str(platform or "").strip().lower()
    if platform == SocialPlatform.YOUTUBE:
        return True
    if not bool(getattr(settings, "SOCIAL_PUBLISHING_ENABLED", False)):
        return False
    return bool(getattr(settings, f"SOCIAL_PUBLISHING_{platform.upper()}_ENABLED", False))
