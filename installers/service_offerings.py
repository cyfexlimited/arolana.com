"""Shared provider-service access rules used by web, admin, and mobile APIs."""

from dataclasses import asdict, dataclass

from django.core.cache import cache

from subscriptions.lifecycle import get_effective_subscription


@dataclass(frozen=True)
class ServiceAccess:
    allowed: bool
    used: int
    limit: int
    remaining: int | None
    unlimited: bool
    upgrade_required: bool
    message: str

    def as_dict(self):
        payload = asdict(self)
        payload["limit_label"] = "Unlimited" if self.unlimited else str(self.limit)
        payload["remaining_label"] = "Unlimited" if self.unlimited else str(self.remaining)
        return payload


class ProviderServicePolicy:
    """Resolve the optional provider-service entitlement in one place.

    Existing plans predate service-count entitlements, so an absent setting is
    deliberately unlimited. A plan may opt in with ``max_active_services`` or
    the legacy-compatible ``provider_service_limit`` key.
    """

    ENTITLEMENT_KEYS = ("max_active_services", "provider_service_limit")

    def __init__(self, provider):
        self.provider = provider
        self.subscription = get_effective_subscription(
            provider.user,
            role_context="provider",
        )

    @property
    def limit(self):
        entitlements = self.subscription.entitlements or {}
        for key in self.ENTITLEMENT_KEYS:
            if key in entitlements:
                try:
                    return int(entitlements[key])
                except (TypeError, ValueError):
                    return -1
        return -1

    def access(self, service=None):
        queryset = self.provider.services.filter(is_active=True)
        if service and service.pk:
            queryset = queryset.exclude(pk=service.pk)
        used = queryset.count()
        limit = self.limit
        unlimited = limit < 0
        allowed = unlimited or used < limit
        remaining = None if unlimited else max(limit - used, 0)
        if allowed:
            message = "Your plan allows this service to be active."
        else:
            message = (
                f"Your {self.subscription.display_name} plan has reached its "
                f"active service limit of {limit}. Deactivate a service or upgrade to continue."
            )
        return ServiceAccess(
            allowed=allowed,
            used=used,
            limit=limit,
            remaining=remaining,
            unlimited=unlimited,
            upgrade_required=not allowed,
            message=message,
        )

    def can_activate(self, service=None):
        """Return the canonical decision used before activating an offering."""
        return self.access(service=service)

    def payload(self, service=None):
        payload = self.access(service=service).as_dict()
        payload.update({
            "plan": self.subscription.display_name,
            "tier": self.subscription.tier,
        })
        return payload


def invalidate_provider_service_cache(provider):
    """Invalidate known provider marketplace cache keys after service changes."""
    if not provider or not provider.pk:
        return
    cache.delete_many([
        f"provider-detail:{provider.pk}",
        f"provider-services:{provider.pk}",
        f"provider-directory:{provider.pk}",
        "provider-directory:public",
    ])
