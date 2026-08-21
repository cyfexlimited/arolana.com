from dataclasses import dataclass
from typing import Optional

from django.contrib.contenttypes.models import ContentType

from .models import AdvertiserIdentity


@dataclass(frozen=True)
class OwnershipResolution:
    is_resolved: bool
    owner_type: str = ""
    vendor: object = None
    provider: object = None
    user: object = None
    reason: str = ""

    @property
    def owner(self):
        return self.vendor or self.provider or self.user


class AdvertiserOwnershipResolver:
    """Resolve sponsorship ownership without making Ads depend on one data source."""

    def resolve_product_owner(self, product) -> OwnershipResolution:
        if not product:
            return OwnershipResolution(False, reason="missing_product")

        evidence = []
        legacy_user = getattr(product, "vendor", None)
        legacy_profile = getattr(legacy_user, "vendor_profile", None) if legacy_user else None
        if legacy_profile and self._vendor_can_advertise(legacy_profile):
            evidence.append(("legacy_product_vendor", legacy_profile))

        offers = (
            product.vendor_offers.filter(is_active=True, approval_status="approved")
            .select_related("vendor")
            .order_by("-is_preferred", "-is_featured", "price", "id")
        )
        offer_vendors = []
        for offer in offers:
            vendor = offer.vendor
            if self._vendor_can_advertise(vendor) and vendor not in offer_vendors:
                offer_vendors.append(vendor)

        if len(offer_vendors) == 1:
            evidence.append(("vendor_product_offer", offer_vendors[0]))
        elif len(offer_vendors) > 1:
            return OwnershipResolution(False, reason="conflicting_product_offers")

        distinct_vendor_ids = {vendor.pk for _, vendor in evidence}
        if len(distinct_vendor_ids) == 1:
            vendor = evidence[0][1]
            return OwnershipResolution(
                True,
                owner_type=AdvertiserIdentity.OWNER_VENDOR,
                vendor=vendor,
                user=getattr(vendor, "user", None),
                reason="resolved_product_vendor",
            )
        if len(distinct_vendor_ids) > 1:
            return OwnershipResolution(False, reason="conflicting_product_ownership")

        return OwnershipResolution(False, reason="missing_product_owner")

    def resolve_product_video_owner(self, product_video) -> OwnershipResolution:
        if not product_video:
            return OwnershipResolution(False, reason="missing_product_video")

        video_vendor = getattr(product_video, "vendor", None)
        product_resolution = self.resolve_product_owner(getattr(product_video, "product", None))
        if video_vendor and self._vendor_can_advertise(video_vendor):
            if (
                product_resolution.is_resolved
                and product_resolution.vendor
                and product_resolution.vendor.pk != video_vendor.pk
            ):
                return OwnershipResolution(False, reason="conflicting_video_product_owner")
            return OwnershipResolution(
                True,
                owner_type=AdvertiserIdentity.OWNER_VENDOR,
                vendor=video_vendor,
                user=getattr(video_vendor, "user", None),
                reason="resolved_product_video_vendor",
            )
        return product_resolution

    def resolve_provider_owner(self, provider) -> OwnershipResolution:
        if provider and self._provider_can_advertise(provider):
            return OwnershipResolution(
                True,
                owner_type=AdvertiserIdentity.OWNER_PROVIDER,
                provider=provider,
                user=getattr(provider, "user", None),
                reason="resolved_provider",
            )
        return OwnershipResolution(False, reason="missing_or_ineligible_provider")

    def resolve_provider_service_owner(self, provider_service) -> OwnershipResolution:
        if not provider_service:
            return OwnershipResolution(False, reason="missing_provider_service")
        if not getattr(provider_service, "is_active", False):
            return OwnershipResolution(False, reason="inactive_provider_service")
        return self.resolve_provider_owner(getattr(provider_service, "provider", None))

    def resolve_asset_owner(self, asset) -> OwnershipResolution:
        content_object = getattr(asset, "content_object", None)
        asset_type = getattr(asset, "asset_type", "")
        if asset_type == "product":
            return self.resolve_product_owner(content_object)
        if asset_type == "product_video":
            return self.resolve_product_video_owner(getattr(asset, "product_video", None) or content_object)
        if asset_type == "vendor_store":
            return self._resolve_vendor_store(content_object)
        if asset_type == "provider_profile":
            return self.resolve_provider_owner(content_object)
        if asset_type == "provider_service":
            return self.resolve_provider_service_owner(content_object)
        return OwnershipResolution(False, reason="unsupported_asset_type")

    def can_user_manage_advertiser(self, user, advertiser_identity: Optional[AdvertiserIdentity]) -> bool:
        if not user or not getattr(user, "is_authenticated", False) or not advertiser_identity:
            return False
        if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
            return True
        if advertiser_identity.owner_type == AdvertiserIdentity.OWNER_VENDOR:
            return advertiser_identity.vendor_id and advertiser_identity.vendor.user_id == user.pk
        if advertiser_identity.owner_type == AdvertiserIdentity.OWNER_PROVIDER:
            return advertiser_identity.provider_id and advertiser_identity.provider.user_id == user.pk
        return advertiser_identity.owner_type == AdvertiserIdentity.OWNER_PLATFORM and advertiser_identity.user_id == user.pk

    def get_or_create_identity(self, resolution: OwnershipResolution):
        if not resolution.is_resolved:
            return None
        defaults = {"user": resolution.user, "display_name": self._display_name(resolution)}
        if resolution.owner_type == AdvertiserIdentity.OWNER_VENDOR:
            identity, _ = AdvertiserIdentity.objects.get_or_create(
                owner_type=AdvertiserIdentity.OWNER_VENDOR,
                vendor=resolution.vendor,
                defaults=defaults,
            )
            return identity
        if resolution.owner_type == AdvertiserIdentity.OWNER_PROVIDER:
            identity, _ = AdvertiserIdentity.objects.get_or_create(
                owner_type=AdvertiserIdentity.OWNER_PROVIDER,
                provider=resolution.provider,
                defaults=defaults,
            )
            return identity
        return None

    def content_type_for(self, model_or_obj):
        return ContentType.objects.get_for_model(model_or_obj, for_concrete_model=False)

    def _resolve_vendor_store(self, vendor) -> OwnershipResolution:
        if vendor and self._vendor_can_advertise(vendor):
            return OwnershipResolution(
                True,
                owner_type=AdvertiserIdentity.OWNER_VENDOR,
                vendor=vendor,
                user=getattr(vendor, "user", None),
                reason="resolved_vendor_store",
            )
        return OwnershipResolution(False, reason="missing_or_ineligible_vendor")

    def _vendor_can_advertise(self, vendor) -> bool:
        return bool(
            vendor
            and getattr(vendor, "is_active", False)
            and getattr(vendor, "approval_status", "") == "approved"
            and getattr(vendor, "can_access_ads", False)
        )

    def _provider_can_advertise(self, provider) -> bool:
        return bool(
            provider
            and getattr(provider, "is_active", False)
            and getattr(provider, "verification_status", "") in {"approved", "verified"}
        )

    def _display_name(self, resolution: OwnershipResolution) -> str:
        if resolution.vendor:
            return getattr(resolution.vendor, "display_name", "") or str(resolution.vendor)
        if resolution.provider:
            return getattr(resolution.provider, "business_name", "") or str(resolution.provider)
        if resolution.user:
            return resolution.user.get_full_name() or resolution.user.username
        return ""


ownership_resolver = AdvertiserOwnershipResolver()
