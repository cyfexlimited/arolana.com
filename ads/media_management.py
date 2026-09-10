"""Advertiser-scoped, mock-only media preparation helpers.

M7 intentionally accepts only server-owned campaign assets.  It neither accepts
client file paths nor imports an HTTP client, so selecting and preparing media
cannot become a provider upload path by accident.
"""

from dataclasses import dataclass

from django.db import transaction

from .media_assets import MediaAssetError, advertising_media_asset_service, source_fingerprint
from .models import AdvertisingMediaAsset, CampaignAsset, ExternalAdvertisingAccount


@dataclass(frozen=True)
class CreativeMediaSource:
    asset_id: int
    media_type: str
    source_type: str
    source_identity: str
    summary: str

    def payload(self):
        return {
            "asset_id": self.asset_id,
            "media_type": self.media_type,
            "source_type": self.source_type,
            "summary": self.summary,
        }


def _safe_summary(value):
    return str(value or "Campaign media").strip()[:200] or "Campaign media"


def _source_from_campaign_asset(asset):
    """Return a usable public source only after rechecking its current state."""
    if not asset.is_active:
        return None
    if asset.asset_type == CampaignAsset.ASSET_PRODUCT:
        product = asset.content_object
        image_name = str(getattr(getattr(product, "main_image", None), "name", "") or "").strip()
        if not (
            product
            and getattr(product, "is_active", False)
            and getattr(product, "approval_status", "") == "approved"
            and image_name
        ):
            return None
        return CreativeMediaSource(
            asset_id=asset.pk,
            media_type=AdvertisingMediaAsset.MEDIA_IMAGE,
            source_type="product_image",
            source_identity=image_name,
            summary=_safe_summary(asset.title or getattr(product, "name", "")),
        )

    if asset.asset_type == CampaignAsset.ASSET_PRODUCT_VIDEO:
        video = asset.product_video or asset.content_object
        product = getattr(video, "product", None)
        public_url = str(
            getattr(video, "youtube_url", "") or getattr(video, "vimeo_url", "") or ""
        ).strip()
        if not (
            video
            and getattr(video, "moderation_status", "") == "approved"
            and product
            and getattr(product, "is_active", False)
            and getattr(product, "approval_status", "") == "approved"
            and public_url.startswith(("https://", "http://"))
        ):
            return None
        return CreativeMediaSource(
            asset_id=asset.pk,
            media_type=AdvertisingMediaAsset.MEDIA_VIDEO,
            source_type="product_video",
            source_identity=public_url,
            summary=_safe_summary(asset.title or getattr(video, "title", "") or getattr(product, "name", "")),
        )
    return None


def available_creative_media_sources(identity, creative):
    if creative.campaign.advertiser_identity_id != identity.pk:
        raise MediaAssetError("creative_not_found")
    sources = []
    for asset in creative.campaign.assets.select_related("product_video", "content_type").all():
        if asset.advertiser_identity_id != identity.pk:
            continue
        source = _source_from_campaign_asset(asset)
        if source:
            sources.append(source)
    return sources


def connected_meta_accounts(identity):
    return list(
        identity.external_accounts.filter(
            channel=ExternalAdvertisingAccount.CHANNEL_META,
            status=ExternalAdvertisingAccount.STATUS_CONNECTED,
        ).order_by("display_name", "pk")
    )


def get_meta_account(identity, account_id):
    try:
        return identity.external_accounts.get(
            pk=account_id,
            channel=ExternalAdvertisingAccount.CHANNEL_META,
            status=ExternalAdvertisingAccount.STATUS_CONNECTED,
        )
    except (ExternalAdvertisingAccount.DoesNotExist, TypeError, ValueError) as exc:
        raise MediaAssetError("external_account_not_found") from exc


def _creative_source_identity(creative):
    if creative.creative_type == "image":
        return AdvertisingMediaAsset.MEDIA_IMAGE, str(getattr(creative.image, "name", "") or "").strip()
    if creative.creative_type == "video":
        return AdvertisingMediaAsset.MEDIA_VIDEO, str(creative.video_url or "").strip()
    raise MediaAssetError("media_creative_type_unsupported")


def attach_creative_media_source(identity, creative, *, account_id, asset_id):
    if creative.campaign.advertiser_identity_id != identity.pk:
        raise MediaAssetError("creative_not_found")
    account = get_meta_account(identity, account_id)
    source = next(
        (candidate for candidate in available_creative_media_sources(identity, creative) if candidate.asset_id == asset_id),
        None,
    )
    if not source:
        raise MediaAssetError("media_source_not_found")
    creative_media_type, _current_source = _creative_source_identity(creative)
    if creative_media_type != source.media_type:
        raise MediaAssetError("media_type_incompatible")

    # The creative retains the server-owned canonical source reference. The
    # provider asset is still account-scoped through AdvertisingMediaAsset.
    with transaction.atomic():
        if source.media_type == AdvertisingMediaAsset.MEDIA_IMAGE:
            creative.image.name = source.source_identity
            creative.save(update_fields=["image", "updated_at"])
        else:
            creative.video_url = source.source_identity
            creative.save(update_fields=["video_url", "updated_at"])
        media = advertising_media_asset_service.get_or_create(
            external_account=account,
            provider=ExternalAdvertisingAccount.CHANNEL_META,
            media_type=source.media_type,
            source_identity=source.source_identity,
        )
    return media, source


def media_for_creative(identity, creative, *, account_id=None):
    if creative.campaign.advertiser_identity_id != identity.pk:
        raise MediaAssetError("creative_not_found")
    sources = available_creative_media_sources(identity, creative)
    accounts = connected_meta_accounts(identity)
    media = None
    if account_id not in (None, ""):
        account = get_meta_account(identity, account_id)
        media_type, source = _creative_source_identity(creative)
        if source:
            media = AdvertisingMediaAsset.objects.filter(
                external_account=account,
                provider=ExternalAdvertisingAccount.CHANNEL_META,
                media_type=media_type,
                source_fingerprint=source_fingerprint(source),
            ).first()
    return accounts, sources, media


def prepare_creative_media(identity, creative, media_id, *, retry=False):
    try:
        media = AdvertisingMediaAsset.objects.select_related("external_account").get(pk=media_id)
    except (AdvertisingMediaAsset.DoesNotExist, TypeError, ValueError) as exc:
        raise MediaAssetError("media_not_found") from exc
    if (
        media.external_account.advertiser_identity_id != identity.pk
        or media.provider != ExternalAdvertisingAccount.CHANNEL_META
        or media.external_account.channel != ExternalAdvertisingAccount.CHANNEL_META
        or media.external_account.status != ExternalAdvertisingAccount.STATUS_CONNECTED
    ):
        raise MediaAssetError("media_not_found")
    media_type, source = _creative_source_identity(creative)
    if not source or media.media_type != media_type or media.source_fingerprint != source_fingerprint(source):
        raise MediaAssetError("media_creative_mismatch")
    if retry and media.status != AdvertisingMediaAsset.STATUS_FAILED:
        raise MediaAssetError("media_retry_not_allowed")
    if not retry and media.status not in {
        AdvertisingMediaAsset.STATUS_PENDING,
        AdvertisingMediaAsset.STATUS_READY,
    }:
        raise MediaAssetError("media_prepare_not_allowed")
    # This is intentionally the deterministic M6 mock adapter. It imports no
    # provider client and performs no network operation.
    return advertising_media_asset_service.mock_upload_meta_image(media)
