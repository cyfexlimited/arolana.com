import re
import uuid

from django.core import signing


ADS_DELIVERY_MAX_AGE_SECONDS = 86400
ADS_DELIVERY_SIGNING_SALT = "ads.v2.delivery"
NATIVE_ADS_SESSION_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


def native_ads_session_id(value):
    """Accept only canonical random UUIDv4 native-session identifiers."""
    value = str(value or "").strip().lower()
    if len(value) > 36 or not NATIVE_ADS_SESSION_RE.fullmatch(value):
        return ""
    return value


class InvalidAdsDelivery(ValueError):
    pass


def verified_ads_delivery(delivery_token, delivery_id):
    """Resolve a signed delivery to its server-owned campaign asset."""
    from .models import CampaignAsset

    token = str(delivery_token or "").strip()
    if not token or len(token) > 1000:
        raise InvalidAdsDelivery("missing_delivery_token")
    try:
        issued = signing.loads(
            token,
            salt=ADS_DELIVERY_SIGNING_SALT,
            max_age=ADS_DELIVERY_MAX_AGE_SECONDS,
        )
        issued_delivery_id = uuid.UUID(str(issued.get("delivery_id") or ""))
        submitted_delivery_id = uuid.UUID(str(delivery_id or ""))
        if issued_delivery_id != submitted_delivery_id:
            raise InvalidAdsDelivery("delivery_mismatch")
        asset = CampaignAsset.objects.select_related(
            "campaign", "advertiser_identity", "content_type", "product_video"
        ).get(
            pk=int(issued.get("asset_id")),
            campaign_id=int(issued.get("campaign_id")),
        )
    except InvalidAdsDelivery:
        raise
    except (signing.BadSignature, signing.SignatureExpired, TypeError, ValueError, CampaignAsset.DoesNotExist) as exc:
        raise InvalidAdsDelivery("invalid_delivery") from exc
    return issued_delivery_id, asset


def campaign_asset_matches_product(asset, product):
    """Return whether an Ads asset represents the purchased product."""
    if not product:
        return False
    if asset.asset_type == asset.ASSET_PRODUCT:
        return asset.content_type.model_class() is product.__class__ and asset.object_id == product.pk
    if asset.asset_type == asset.ASSET_PRODUCT_VIDEO:
        video = asset.product_video or asset.content_object
        return getattr(video, "product_id", None) == product.pk
    return False
