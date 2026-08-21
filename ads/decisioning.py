from dataclasses import dataclass, field
from decimal import Decimal
from uuid import uuid4

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from installers.models import ProviderService, ServiceProviderProfile
from products.models import Product, ProductVideo
from products.services.recommendation_engine import RecommendationEngine
from vendors.models import VendorProfile

from .models import AdEvent, CampaignAsset
from .ownership import ownership_resolver


@dataclass
class DecisionContext:
    placement: str = "default"
    surface: str = ""
    page: str = ""
    product_id: int | None = None
    category_id: int | None = None
    brand_id: int | None = None
    vendor_id: int | None = None
    provider_id: int | None = None
    service_id: int | None = None
    search_query: str = ""
    device: str = ""
    country: str = ""
    session_id: str = ""
    user: object = None


@dataclass
class PlacementPolicy:
    max_sponsored_items: int = 1
    minimum_organic_items: int = 2
    sponsored_interval: int = 3
    maximum_consecutive_sponsored: int = 1


@dataclass
class DecisionCandidate:
    type: str
    object: object
    score: float
    reasons: list[str] = field(default_factory=list)
    sponsored: bool = False
    label: str = ""
    sponsor: dict | None = None
    asset: CampaignAsset | None = None
    delivery_id: str = ""
    score_components: dict = field(default_factory=dict)

    @property
    def id(self):
        return getattr(self.object, "pk", None)


class UnifiedRecommendationDecisioningService:
    """Unifies organic candidates with eligible sponsored assets."""

    DEFAULT_POLICY = PlacementPolicy()
    PLACEMENT_POLICIES = {
        "homepage": PlacementPolicy(max_sponsored_items=2, minimum_organic_items=3, sponsored_interval=4),
        "search": PlacementPolicy(max_sponsored_items=1, minimum_organic_items=3, sponsored_interval=4),
        "category": PlacementPolicy(max_sponsored_items=1, minimum_organic_items=2, sponsored_interval=3),
        "product_recommendations": PlacementPolicy(max_sponsored_items=1, minimum_organic_items=3, sponsored_interval=4),
        "video": PlacementPolicy(max_sponsored_items=1, minimum_organic_items=2, sponsored_interval=3),
        "service": PlacementPolicy(max_sponsored_items=1, minimum_organic_items=2, sponsored_interval=3),
        "provider": PlacementPolicy(max_sponsored_items=1, minimum_organic_items=2, sponsored_interval=3),
        "store": PlacementPolicy(max_sponsored_items=1, minimum_organic_items=2, sponsored_interval=3),
    }

    def context_from_request(self, request):
        def int_param(name):
            try:
                value = int(request.GET.get(name) or 0)
            except (TypeError, ValueError):
                return None
            return value or None

        return DecisionContext(
            placement=(request.GET.get("placement") or request.GET.get("surface") or "default")[:80],
            surface=(request.GET.get("surface") or "")[:80],
            page=(request.GET.get("page") or "")[:80],
            product_id=int_param("product_id"),
            category_id=int_param("category_id"),
            brand_id=int_param("brand_id"),
            vendor_id=int_param("vendor_id"),
            provider_id=int_param("provider_id"),
            service_id=int_param("service_id"),
            search_query=(request.GET.get("q") or request.GET.get("query") or "")[:160],
            device=(request.GET.get("device") or self._request_device(request))[:30],
            country=(request.GET.get("country") or "")[:2].upper(),
            session_id=getattr(request, "session", None).session_key if getattr(request, "session", None) else "",
            user=request.user if getattr(request, "user", None) and request.user.is_authenticated else None,
        )

    def recommendations_for_request(self, request, limit=10, context=None):
        context = context or self.context_from_request(request)
        if isinstance(context, dict):
            context = DecisionContext(
                **{key: value for key, value in context.items() if key in DecisionContext.__dataclass_fields__}
            )

        organic = self._organic_candidates(request, context, limit)
        sponsored = []
        if self._sponsored_allowed(request):
            sponsored = self._eligible_sponsored_candidates(context)

        mixed = self._mix_candidates(organic, sponsored, context, limit)
        return [self._candidate_to_dict(candidate) for candidate in mixed[:limit]]

    def _organic_candidates(self, request, context, limit):
        candidates = []
        product_results = RecommendationEngine.for_user_with_reasons(
            request=request,
            limit=max(limit, 10),
            exclude_ids=[context.product_id] if context.product_id else None,
            exclude_purchased=False,
        )
        for item in product_results:
            product = item["product"]
            candidates.append(
                DecisionCandidate(
                    type="product",
                    object=product,
                    score=float(item.get("score") or 0.0),
                    reasons=item.get("reasons", []),
                    score_components={"organic_relevance": float(item.get("score") or 0.0)},
                )
            )

        candidates.extend(self._organic_video_candidates(context, limit=3))
        candidates.extend(self._organic_service_candidates(context, limit=3))
        candidates.extend(self._organic_provider_candidates(context, limit=3))
        candidates.extend(self._organic_store_candidates(context, limit=3))
        candidates.sort(key=lambda candidate: candidate.score, reverse=True)
        return candidates[: max(limit * 2, limit)]

    def _eligible_sponsored_candidates(self, context):
        now = timezone.now()
        assets = (
            CampaignAsset.objects.filter(
                is_active=True,
                campaign__status="active",
                campaign__approved=True,
                campaign__start_date__lte=now,
                advertiser_identity__is_active=True,
            )
            .exclude(campaign__end_date__isnull=False, campaign__end_date__lt=now)
            .select_related(
                "campaign",
                "advertiser_identity",
                "advertiser_identity__vendor",
                "advertiser_identity__provider",
                "content_type",
                "product_video",
            )
        )

        candidates = []
        for asset in assets:
            eligible, reasons = self._asset_is_eligible(asset, context)
            if not eligible:
                continue
            obj = self._asset_object(asset)
            score_components = self._score_sponsored_asset(asset, obj, context)
            if score_components["organic_relevance"] <= 0:
                continue
            score = sum(score_components.values())
            candidates.append(
                DecisionCandidate(
                    type=asset.asset_type,
                    object=obj,
                    score=score,
                    reasons=reasons,
                    sponsored=True,
                    label="Sponsored",
                    sponsor=self._sponsor_payload(asset.advertiser_identity),
                    asset=asset,
                    delivery_id=str(uuid4()),
                    score_components=score_components,
                )
            )
        candidates.sort(key=lambda candidate: candidate.score, reverse=True)
        return candidates

    def _asset_is_eligible(self, asset, context):
        campaign = asset.campaign
        metadata = asset.metadata or {}
        campaign_metadata = getattr(campaign, "custom_segments", None) or []

        if campaign.total_budget and campaign.spent >= campaign.total_budget:
            return False, ["budget_exhausted"]
        if not self._metadata_allows(metadata, "placements", context.placement):
            return False, ["wrong_placement"]
        if campaign.device_targeting and context.device and context.device not in campaign.device_targeting:
            return False, ["wrong_device"]
        if not self._metadata_allows(metadata, "devices", context.device):
            return False, ["wrong_device"]
        if campaign.geo_targeting and context.country and context.country not in campaign.geo_targeting:
            return False, ["wrong_country"]
        if not self._metadata_allows(metadata, "countries", context.country):
            return False, ["wrong_country"]
        if metadata.get("policy_blocked") or "policy_blocked" in campaign_metadata:
            return False, ["policy_blocked"]
        if float(metadata.get("quality_score", 0.5) or 0.5) < 0.25:
            return False, ["poor_quality"]
        if not self._under_frequency_limit(asset, campaign, context):
            return False, ["frequency_limited"]

        ownership = ownership_resolver.resolve_asset_owner(asset)
        if not ownership.is_resolved:
            return False, [ownership.reason]

        obj = self._asset_object(asset)
        if not self._object_is_available(asset, obj):
            return False, ["asset_unavailable"]

        return True, ["eligible_sponsored_asset"]

    def _score_sponsored_asset(self, asset, obj, context):
        metadata = asset.metadata or {}
        relevance = self._context_relevance(asset, obj, context)
        quality = min(float(metadata.get("quality_score", 0.5) or 0.5), 1.0) * 12.0
        business = 6.0 if getattr(asset.advertiser_identity, "is_active", False) else -100.0
        sponsored_value = min(float(asset.campaign.max_bid or Decimal("0")), 10.0)
        historical = self._historical_performance(asset)
        frequency_penalty = self._frequency_penalty(asset, context)
        poor_quality_penalty = 8.0 if float(metadata.get("quality_score", 0.5) or 0.5) < 0.25 else 0.0
        repetition_penalty = 4.0 if self._recently_delivered(asset, context) else 0.0

        return {
            "organic_relevance": relevance,
            "content_quality": quality,
            "business_eligibility": business,
            "sponsored_value": sponsored_value,
            "historical_performance": historical,
            "frequency_penalty": -frequency_penalty,
            "poor_quality_penalty": -poor_quality_penalty,
            "repetition_penalty": -repetition_penalty,
        }

    def _mix_candidates(self, organic, sponsored, context, limit):
        if not sponsored:
            return organic[:limit]

        policy = self.PLACEMENT_POLICIES.get(context.placement, self.DEFAULT_POLICY)
        max_sponsored = min(policy.max_sponsored_items, max(limit - policy.minimum_organic_items, 0))
        sponsored = sponsored[:max_sponsored]
        if not sponsored:
            return organic[:limit]

        result = []
        sponsored_used = 0
        consecutive_sponsored = 0
        organic_iter = iter(organic)
        sponsored_iter = iter(sponsored)

        while len(result) < limit:
            should_insert_sponsored = (
                sponsored_used < max_sponsored
                and len(result) >= policy.minimum_organic_items
                and (len(result) + 1) % policy.sponsored_interval == 0
                and consecutive_sponsored < policy.maximum_consecutive_sponsored
            )
            if should_insert_sponsored:
                try:
                    result.append(next(sponsored_iter))
                    sponsored_used += 1
                    consecutive_sponsored += 1
                    continue
                except StopIteration:
                    pass
            try:
                result.append(next(organic_iter))
                consecutive_sponsored = 0
            except StopIteration:
                break

        return result

    def _candidate_to_dict(self, candidate):
        payload = {
            "type": candidate.type,
            "id": candidate.id,
            "score": round(candidate.score, 4),
            "reasons": candidate.reasons,
            "sponsored": candidate.sponsored,
            "label": candidate.label if candidate.sponsored else "",
            "sponsor": candidate.sponsor if candidate.sponsored else None,
            "tracking": {
                "delivery_id": candidate.delivery_id,
                "asset_id": candidate.asset.pk if candidate.asset else None,
                "campaign_id": candidate.asset.campaign_id if candidate.asset else None,
            },
            "item": self._public_item_payload(candidate.type, candidate.object),
        }
        return payload

    def _public_item_payload(self, candidate_type, obj):
        if candidate_type == "product":
            return {
                "id": obj.pk,
                "name": getattr(obj, "name", ""),
                "slug": getattr(obj, "slug", ""),
                "price": str(getattr(obj, "price", "")),
                "url": obj.get_absolute_url() if hasattr(obj, "get_absolute_url") else "",
            }
        if candidate_type == "product_video":
            return {
                "id": obj.pk,
                "title": getattr(obj, "title", ""),
                "product_id": getattr(obj, "product_id", None),
                "source": getattr(obj, "source", ""),
            }
        if candidate_type == "service":
            return {
                "id": obj.pk,
                "name": getattr(obj, "service_name", ""),
                "provider_id": getattr(obj, "provider_id", None),
            }
        if candidate_type == "provider":
            return {
                "id": obj.pk,
                "name": getattr(obj, "business_name", ""),
                "slug": getattr(obj, "slug", ""),
            }
        if candidate_type == "store":
            return {
                "id": obj.pk,
                "name": getattr(obj, "display_name", "") or getattr(obj, "store_name", ""),
                "slug": getattr(obj, "store_slug", ""),
            }
        return {"id": getattr(obj, "pk", None)}

    def _organic_video_candidates(self, context, limit):
        qs = ProductVideo.objects.filter(is_active=True, moderation_status="approved").select_related("product")
        if context.product_id:
            qs = qs.filter(product_id=context.product_id)
        return [
            DecisionCandidate(
                type="product_video",
                object=video,
                score=20.0 + float(getattr(video, "views_count", 0) or 0) / 100.0,
                reasons=["Relevant product video"],
                score_components={"organic_relevance": 20.0},
            )
            for video in qs.order_by("-views_count", "-created_at")[:limit]
        ]

    def _organic_service_candidates(self, context, limit):
        qs = ProviderService.objects.filter(is_active=True, provider__verification_status__in=["approved", "verified"]).select_related("provider")
        if context.provider_id:
            qs = qs.filter(provider_id=context.provider_id)
        if context.service_id:
            qs = qs.filter(id=context.service_id)
        return [
            DecisionCandidate(
                type="service",
                object=service,
                score=18.0,
                reasons=["Relevant service"],
                score_components={"organic_relevance": 18.0},
            )
            for service in qs.order_by("-created_at")[:limit]
        ]

    def _organic_provider_candidates(self, context, limit):
        qs = ServiceProviderProfile.objects.filter(is_active=True, verification_status__in=["approved", "verified"])
        if context.provider_id:
            qs = qs.filter(id=context.provider_id)
        return [
            DecisionCandidate(
                type="provider",
                object=provider,
                score=16.0 + (2.0 if getattr(provider, "is_verified", False) else 0.0),
                reasons=["Relevant provider"],
                score_components={"organic_relevance": 16.0},
            )
            for provider in qs.order_by("-is_verified", "-created_at")[:limit]
        ]

    def _organic_store_candidates(self, context, limit):
        qs = VendorProfile.objects.filter(is_active=True, approval_status="approved")
        if context.vendor_id:
            qs = qs.filter(id=context.vendor_id)
        return [
            DecisionCandidate(
                type="store",
                object=vendor,
                score=15.0 + float(getattr(vendor, "rating_avg", 0) or 0),
                reasons=["Relevant store"],
                score_components={"organic_relevance": 15.0},
            )
            for vendor in qs.order_by("-priority_score", "-rating_avg", "-created_at")[:limit]
        ]

    def _context_relevance(self, asset, obj, context):
        metadata = asset.metadata or {}
        keywords = [str(item).lower() for item in metadata.get("keywords", [])]
        score = 0.0
        if context.search_query and any(keyword in context.search_query.lower() for keyword in keywords):
            score += 25.0
        if asset.asset_type == CampaignAsset.ASSET_PRODUCT:
            score += self._product_relevance(obj, context)
        elif asset.asset_type == CampaignAsset.ASSET_PRODUCT_VIDEO:
            score += self._product_relevance(getattr(obj, "product", None), context) + 10.0
        elif asset.asset_type == CampaignAsset.ASSET_PROVIDER_SERVICE:
            score += 25.0 if context.provider_id == getattr(obj, "provider_id", None) else 12.0
        elif asset.asset_type == CampaignAsset.ASSET_PROVIDER_PROFILE:
            score += 25.0 if context.provider_id == getattr(obj, "pk", None) else 12.0
        elif asset.asset_type == CampaignAsset.ASSET_VENDOR_STORE:
            score += 25.0 if context.vendor_id == getattr(obj, "pk", None) else 12.0
        return score

    def _product_relevance(self, product, context):
        if not product:
            return 0.0
        score = 8.0
        if context.product_id and product.pk == context.product_id:
            score += 28.0
        if context.category_id and getattr(product, "category_id", None) == context.category_id:
            score += 20.0
        if context.brand_id and getattr(product, "brand_id", None) == context.brand_id:
            score += 12.0
        if context.vendor_id:
            vendor_profile = getattr(getattr(product, "vendor", None), "vendor_profile", None)
            if vendor_profile and vendor_profile.pk == context.vendor_id:
                score += 16.0
        return score

    def _object_is_available(self, asset, obj):
        if not obj:
            return asset.asset_type == CampaignAsset.ASSET_EXTERNAL_URL and bool(asset.destination_url)
        if asset.asset_type == CampaignAsset.ASSET_PRODUCT:
            return bool(getattr(obj, "is_active", False) and getattr(obj, "approval_status", "approved") == "approved")
        if asset.asset_type == CampaignAsset.ASSET_PRODUCT_VIDEO:
            return bool(getattr(obj, "is_active", False) and getattr(obj, "moderation_status", "") == "approved")
        if asset.asset_type == CampaignAsset.ASSET_PROVIDER_SERVICE:
            return bool(getattr(obj, "is_active", False) and getattr(obj.provider, "verification_status", "") in {"approved", "verified"})
        if asset.asset_type == CampaignAsset.ASSET_PROVIDER_PROFILE:
            return bool(getattr(obj, "is_active", False) and getattr(obj, "verification_status", "") in {"approved", "verified"})
        if asset.asset_type == CampaignAsset.ASSET_VENDOR_STORE:
            return bool(getattr(obj, "is_active", False) and getattr(obj, "approval_status", "") == "approved")
        return False

    def _asset_object(self, asset):
        if asset.asset_type == CampaignAsset.ASSET_PRODUCT_VIDEO and asset.product_video_id:
            return asset.product_video
        return asset.content_object

    def _metadata_allows(self, metadata, key, value):
        allowed = metadata.get(key) or []
        return not allowed or not value or value in allowed

    def _under_frequency_limit(self, asset, campaign, context):
        limit = int((asset.metadata or {}).get("frequency_limit") or campaign.frequency_cap or 0)
        if not limit or not context.session_id:
            return True
        today = timezone.now().date()
        count = AdEvent.objects.filter(
            asset=asset,
            session_id=context.session_id,
            event_type=AdEvent.EVENT_IMPRESSION,
            occurred_at__date=today,
        ).count()
        return count < limit

    def _frequency_penalty(self, asset, context):
        if not context.session_id:
            return 0.0
        return float(
            AdEvent.objects.filter(
                asset=asset,
                session_id=context.session_id,
                event_type=AdEvent.EVENT_IMPRESSION,
            ).count()
        )

    def _recently_delivered(self, asset, context):
        if not context.session_id:
            return False
        return AdEvent.objects.filter(asset=asset, session_id=context.session_id).exists()

    def _historical_performance(self, asset):
        impressions = AdEvent.objects.filter(asset=asset, event_type=AdEvent.EVENT_IMPRESSION).count()
        clicks = AdEvent.objects.filter(asset=asset, event_type=AdEvent.EVENT_CLICK).count()
        if not impressions:
            return 0.0
        return min((clicks / impressions) * 20.0, 8.0)

    def _sponsor_payload(self, advertiser_identity):
        if advertiser_identity.owner_type == "vendor" and advertiser_identity.vendor:
            return {
                "type": "vendor",
                "id": advertiser_identity.vendor_id,
                "name": advertiser_identity.vendor.display_name,
            }
        if advertiser_identity.owner_type == "provider" and advertiser_identity.provider:
            return {
                "type": "provider",
                "id": advertiser_identity.provider_id,
                "name": advertiser_identity.provider.business_name,
            }
        return {"type": advertiser_identity.owner_type, "id": advertiser_identity.pk, "name": advertiser_identity.display_name}

    def _sponsored_allowed(self, request):
        if getattr(settings, "ADS_RECOMMENDATION_V2_SPONSORED_ENABLED", False):
            return True
        if not getattr(settings, "ADS_RECOMMENDATION_V2_INTERNAL_TESTING_ENABLED", False):
            return False
        user = getattr(request, "user", None)
        return bool(
            user
            and user.is_authenticated
            and getattr(user, "is_staff", False)
            and getattr(request, "session", {}).get("ads_v2_internal_test") is True
        )

    def _request_device(self, request):
        user_agent = (request.META.get("HTTP_USER_AGENT") or "").lower()
        if "mobile" in user_agent or "android" in user_agent or "iphone" in user_agent:
            return "mobile"
        return "desktop" if user_agent else ""


decisioning_service = UnifiedRecommendationDecisioningService()
