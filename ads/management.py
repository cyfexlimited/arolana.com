from decimal import Decimal

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from installers.models import ProviderService, ServiceProviderProfile
from products.models import Product, ProductVideo
from vendors.models import VendorProfile

from .models import (
    AdAttribution,
    AdCampaign,
    AdChannelExecution,
    AdCreative,
    AdEvent,
    AdPlacement,
    AdvertiserIdentity,
    CampaignAsset,
    ExternalAdvertisingAccount,
)
from .ownership import ownership_resolver


OBJECTIVES = {value for value, _label in AdCampaign.OBJECTIVE_CHOICES}
ASSET_TYPES = {
    CampaignAsset.ASSET_PRODUCT,
    CampaignAsset.ASSET_PRODUCT_VIDEO,
    CampaignAsset.ASSET_PROVIDER_SERVICE,
    CampaignAsset.ASSET_PROVIDER_PROFILE,
    CampaignAsset.ASSET_VENDOR_STORE,
}


class AdvertiserAccessError(Exception):
    pass


class AdvertiserValidationError(Exception):
    pass


def authorized_identities_for_user(user):
    if not user or not user.is_authenticated:
        return AdvertiserIdentity.objects.none()
    qs = AdvertiserIdentity.objects.filter(is_active=True)
    if user.is_staff:
        return qs
    return qs.filter(user=user)


def current_advertiser_identity(user, advertiser_id=None):
    qs = authorized_identities_for_user(user)
    if advertiser_id:
        try:
            return qs.get(pk=advertiser_id)
        except AdvertiserIdentity.DoesNotExist as exc:
            raise AdvertiserAccessError("unauthorized_advertiser") from exc

    identity = qs.order_by("owner_type", "id").first()
    if identity:
        return identity

    # Safe bootstrap for users who already own an approved vendor/provider.
    vendor = getattr(user, "vendor_profile", None)
    if vendor and getattr(vendor, "approval_status", "") == "approved":
        vendor_ct = ContentType.objects.get_for_model(vendor)
        vendor_asset = CampaignAsset(
            asset_type=CampaignAsset.ASSET_VENDOR_STORE,
            content_type=vendor_ct,
            object_id=vendor.pk,
        )
        return ownership_resolver.get_or_create_identity(
            ownership_resolver.resolve_asset_owner(vendor_asset)
        )
    provider = getattr(user, "service_provider_profile", None)
    if provider and getattr(provider, "verification_status", "") in {"approved", "verified"}:
        return ownership_resolver.get_or_create_identity(
            ownership_resolver.resolve_provider_owner(provider)
        )
    raise AdvertiserAccessError("no_authorized_advertiser")


def identity_payload(identity):
    return {
        "id": identity.pk,
        "owner_type": identity.owner_type,
        "display_name": identity.display_name or str(identity),
        "vendor_id": identity.vendor_id,
        "provider_id": identity.provider_id,
    }


def campaign_queryset(identity):
    return (
        AdCampaign.objects
        .filter(advertiser_identity=identity)
        .prefetch_related("assets", "creatives", "channel_executions")
        .order_by("-created_at")
    )


def campaign_metrics(campaign):
    events = AdEvent.objects.filter(campaign=campaign, metadata__internal_test__isnull=True)
    attributions = AdAttribution.objects.filter(campaign=campaign, metadata__internal_test__isnull=True)
    valid_attributions = attributions.exclude(lifecycle_status=AdAttribution.LIFECYCLE_REVERSED)
    impressions = events.filter(event_type=AdEvent.EVENT_IMPRESSION).count()
    views = events.filter(event_type=AdEvent.EVENT_VIEW).count()
    clicks = events.filter(event_type=AdEvent.EVENT_CLICK).count()
    valid_orders = valid_attributions.filter(order_item__isnull=False).count()
    leads = valid_attributions.filter(metadata__commerce_event="qualified_service_lead").count()
    revenue = (
        valid_attributions
        .filter(order_item__isnull=False)
        .aggregate(total=Sum(Coalesce("net_revenue_amount", "revenue_amount")))
        .get("total")
        or Decimal("0.00")
    )
    spend = campaign.spent if campaign.spent and campaign.spent > 0 else None
    roas = (revenue / spend) if spend else None
    return {
        "impressions": impressions,
        "views": views,
        "clicks": clicks,
        "ctr": (clicks / impressions) if impressions else None,
        "valid_orders": valid_orders,
        "qualified_leads": leads,
        "net_attributed_revenue": revenue,
        "spend": spend,
        "roas": roas,
        "conversion_rate": (valid_orders / clicks) if clicks else None,
    }


def overview_metrics(identity):
    campaigns = campaign_queryset(identity)
    events = AdEvent.objects.filter(advertiser_identity=identity, metadata__internal_test__isnull=True)
    attributions = AdAttribution.objects.filter(advertiser_identity=identity, metadata__internal_test__isnull=True)
    valid_attributions = attributions.exclude(lifecycle_status=AdAttribution.LIFECYCLE_REVERSED)
    impressions = events.filter(event_type=AdEvent.EVENT_IMPRESSION).count()
    clicks = events.filter(event_type=AdEvent.EVENT_CLICK).count()
    views = events.filter(event_type=AdEvent.EVENT_VIEW).count()
    revenue = (
        valid_attributions
        .filter(order_item__isnull=False)
        .aggregate(total=Sum(Coalesce("net_revenue_amount", "revenue_amount")))
        .get("total")
        or Decimal("0.00")
    )
    spend = campaigns.aggregate(total=Sum("spent")).get("total") or Decimal("0.00")
    spend_valid = spend > 0
    return {
        "active_campaigns": campaigns.filter(status="active").count(),
        "pending_campaigns": campaigns.filter(status="pending").count(),
        "spend": spend if spend_valid else None,
        "impressions": impressions,
        "views": views,
        "clicks": clicks,
        "ctr": (clicks / impressions) if impressions else None,
        "valid_orders": valid_attributions.filter(order_item__isnull=False).count(),
        "qualified_leads": valid_attributions.filter(metadata__commerce_event="qualified_service_lead").count(),
        "net_attributed_revenue": revenue,
        "roas": (revenue / spend) if spend_valid else None,
    }


def serialize_campaign(campaign, include_metrics=True):
    from .execution import external_campaign_execution_service

    assets = list(campaign.assets.all())
    channels = list(campaign.channel_executions.all())
    payload = {
        "id": campaign.pk,
        "name": campaign.name,
        "campaign_id": campaign.campaign_id,
        "objective": campaign.objective or AdCampaign.OBJECTIVE_PRODUCT_VISITS,
        "campaign_type": campaign.campaign_type,
        "status": campaign.status,
        "approved": campaign.approved,
        "asset_summary": ", ".join(asset.title or asset.get_asset_type_display() for asset in assets) or "--",
        "channels": [channel.channel for channel in channels] or ["arolana"],
        "budget": {
            "type": campaign.budget_type,
            "daily": campaign.daily_budget,
            "total": campaign.total_budget,
            "spent": campaign.spent,
        },
        "schedule": {
            "start_date": campaign.start_date,
            "end_date": campaign.end_date,
            "timezone": campaign.timezone,
        },
        "execution_cards": external_campaign_execution_service.execution_cards(campaign),
    }
    if include_metrics:
        payload["performance"] = campaign_metrics(campaign)
    return payload


def owned_asset_options(identity):
    options = []
    if identity.owner_type == AdvertiserIdentity.OWNER_VENDOR and identity.vendor_id:
        vendor = identity.vendor
        products = Product.objects.filter(vendor=vendor.user, is_active=True, approval_status="approved")
        for product in products[:100]:
            options.append(_asset_option(CampaignAsset.ASSET_PRODUCT, product, product.name, product.get_absolute_url()))
        videos = ProductVideo.objects.filter(vendor=vendor, moderation_status="approved").select_related("product")
        for video in videos[:100]:
            options.append(_asset_option(CampaignAsset.ASSET_PRODUCT_VIDEO, video, video.title or video.product.name, ""))
        options.append(_asset_option(CampaignAsset.ASSET_VENDOR_STORE, vendor, vendor.store_name, vendor.get_absolute_url()))
    elif identity.owner_type == AdvertiserIdentity.OWNER_PROVIDER and identity.provider_id:
        provider = identity.provider
        options.append(_asset_option(CampaignAsset.ASSET_PROVIDER_PROFILE, provider, provider.business_name, provider.get_absolute_url()))
        services = ProviderService.objects.filter(provider=provider, is_active=True).select_related("category")
        for service in services[:100]:
            options.append(_asset_option(CampaignAsset.ASSET_PROVIDER_SERVICE, service, service.service_name, service.get_absolute_url()))

    # Brand/category are listed as future-safe discovery types only when owned
    # ownership can be resolved. Current repo data has no advertiser ownership
    # relation for public Brand/Category, so we intentionally do not expose them.
    return options


def _asset_option(asset_type, obj, title, url):
    return {
        "asset_type": asset_type,
        "object_id": obj.pk,
        "content_type_id": ContentType.objects.get_for_model(obj).pk,
        "title": title,
        "url": url,
    }


def get_or_create_campaign_asset(identity, asset_type, content_type_id, object_id):
    if asset_type not in ASSET_TYPES:
        raise AdvertiserValidationError("unsupported_asset_type")
    try:
        content_type = ContentType.objects.get(pk=content_type_id)
    except ContentType.DoesNotExist as exc:
        raise AdvertiserValidationError("invalid_content_type") from exc
    obj = content_type.get_object_for_this_type(pk=object_id)
    transient = CampaignAsset(
        advertiser_identity=identity,
        asset_type=asset_type,
        content_type=content_type,
        object_id=object_id,
        product_video=obj if asset_type == CampaignAsset.ASSET_PRODUCT_VIDEO else None,
    )
    resolution = ownership_resolver.resolve_asset_owner(transient)
    if not resolution.is_resolved:
        raise AdvertiserValidationError("asset_owner_unresolved")
    if resolution.owner_type != identity.owner_type:
        raise AdvertiserValidationError("asset_owner_mismatch")
    if resolution.vendor and resolution.vendor.pk != identity.vendor_id:
        raise AdvertiserValidationError("asset_vendor_mismatch")
    if resolution.provider and resolution.provider.pk != identity.provider_id:
        raise AdvertiserValidationError("asset_provider_mismatch")
    return transient, obj


def create_campaign(identity, data, *, submit=False):
    name = str(data.get("name") or "").strip()[:200]
    if not name:
        raise AdvertiserValidationError("name_required")
    objective = str(data.get("objective") or AdCampaign.OBJECTIVE_PRODUCT_VISITS)
    if objective not in OBJECTIVES:
        raise AdvertiserValidationError("invalid_objective")

    asset_type = str(data.get("asset_type") or "")
    content_type_id = data.get("content_type_id")
    object_id = data.get("object_id")
    asset_shell, obj = get_or_create_campaign_asset(identity, asset_type, content_type_id, object_id)

    campaign = AdCampaign.objects.create(
        name=name,
        advertiser_identity=identity,
        campaign_type=_campaign_type_for_asset(asset_type),
        objective=objective,
        status="pending" if submit else "draft",
        approved=False,
        budget_type=str(data.get("budget_type") or "total")[:10],
        daily_budget=_decimal_or_none(data.get("daily_budget")),
        total_budget=_decimal_or_default(data.get("total_budget"), Decimal("100.00")),
        max_bid=_decimal_or_default(data.get("max_bid"), Decimal("0.50")),
        start_date=data.get("start_date") or timezone.now(),
        end_date=data.get("end_date") or None,
        targeting=str(data.get("targeting") or "all")[:20],
        geo_targeting=_list_value(data.get("geo_targeting")),
        device_targeting=_list_value(data.get("device_targeting")),
    )
    asset = CampaignAsset.objects.create(
        campaign=campaign,
        advertiser_identity=identity,
        asset_type=asset_type,
        content_type=asset_shell.content_type,
        object_id=asset_shell.object_id,
        product_video=asset_shell.product_video,
        title=str(data.get("asset_title") or getattr(obj, "name", "") or getattr(obj, "title", "") or "")[:200],
        metadata={"placements": _list_value(data.get("placements")), "internal_test": bool(data.get("internal_test"))},
    )
    AdChannelExecution.objects.get_or_create(
        campaign=campaign,
        advertiser_identity=identity,
        channel=AdChannelExecution.CHANNEL_INTERNAL,
        defaults={"status": AdChannelExecution.STATUS_READY if submit else AdChannelExecution.STATUS_DRAFT},
    )
    return campaign, asset


def update_campaign(identity, campaign_id, data):
    try:
        campaign = AdCampaign.objects.get(pk=campaign_id, advertiser_identity=identity)
    except AdCampaign.DoesNotExist as exc:
        raise AdvertiserAccessError("campaign_not_found") from exc
    allowed = {"draft", "pending", "paused", "scheduled"}
    if campaign.status not in allowed:
        raise AdvertiserValidationError("campaign_not_editable")
    if "name" in data:
        campaign.name = str(data["name"]).strip()[:200] or campaign.name
    if "objective" in data:
        if data["objective"] not in OBJECTIVES:
            raise AdvertiserValidationError("invalid_objective")
        campaign.objective = data["objective"]
    if "status" in data and data["status"] in {"draft", "pending", "paused"}:
        campaign.status = data["status"]
    campaign.save(update_fields=["name", "objective", "status", "updated_at"])
    return campaign


def creative_queryset(identity):
    return AdCreative.objects.filter(campaign__advertiser_identity=identity).order_by("-created_at")


def create_creative(identity, data):
    try:
        campaign = AdCampaign.objects.get(pk=data.get("campaign_id"), advertiser_identity=identity)
    except AdCampaign.DoesNotExist as exc:
        raise AdvertiserAccessError("campaign_not_found") from exc
    creative_type = str(data.get("creative_type") or "image")
    if creative_type not in {"image", "video", "native", "carousel"}:
        raise AdvertiserValidationError("unsupported_creative_type")
    headline = str(data.get("headline") or "").strip()[:100]
    if not headline:
        raise AdvertiserValidationError("headline_required")
    return AdCreative.objects.create(
        campaign=campaign,
        name=str(data.get("name") or headline)[:200],
        creative_type=creative_type,
        headline=headline,
        description=str(data.get("description") or "")[:1000],
        cta_text=str(data.get("cta_text") or "Learn More")[:50],
        clickthrough_url=str(data.get("clickthrough_url") or "https://arolana.com")[:200],
        video_url=str(data.get("video_url") or "")[:200],
    )


def connected_account_shells(identity):
    existing = {}
    for account in identity.external_accounts.exclude(status=ExternalAdvertisingAccount.STATUS_REVOKED):
        existing.setdefault(account.channel, []).append(account)
    labels = {
        "meta": "Meta / Facebook / Instagram",
        "google": "Google / YouTube",
        "tiktok": "TikTok",
        "linkedin": "LinkedIn",
    }
    return [
        {
            "channel": channel,
            "label": label,
            "status": existing[channel][0].status if existing.get(channel) else ExternalAdvertisingAccount.STATUS_NOT_CONNECTED,
            "accounts": [
                {
                    "id": account.pk,
                    "external_account_id": account.external_account_id,
                    "display_name": account.display_name,
                    "status": account.status,
                    "currency": (account.metadata or {}).get("currency", ""),
                    "timezone": (account.metadata or {}).get("timezone", ""),
                    "permission_summary": (account.metadata or {}).get("permission_summary", ""),
                    "meta_page_id": (account.metadata or {}).get("meta_page_id", ""),
                    "meta_page_name": (account.metadata or {}).get("meta_page_name", ""),
                }
                for account in existing.get(channel, [])
            ],
            "available": bool(getattr(settings, f"ADS_{channel.upper()}_CONNECTION_ENABLED", False)),
            "message": (
                "Ready to connect."
                if getattr(settings, f"ADS_{channel.upper()}_CONNECTION_ENABLED", False)
                else "Integration unavailable / setup required."
            ),
        }
        for channel, label in labels.items()
    ]


def _campaign_type_for_asset(asset_type):
    if asset_type == CampaignAsset.ASSET_PRODUCT_VIDEO:
        return "video"
    if asset_type in {CampaignAsset.ASSET_PRODUCT, CampaignAsset.ASSET_VENDOR_STORE}:
        return "sponsored"
    return "native"


def _decimal_or_none(value):
    if value in ("", None):
        return None
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _decimal_or_default(value, default):
    return _decimal_or_none(value) or default


def _list_value(value):
    if isinstance(value, list):
        return [str(item)[:80] for item in value if str(item).strip()]
    if value in ("", None):
        return []
    return [str(value)[:80]]
