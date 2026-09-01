import json
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from datetime import datetime, timedelta
from io import StringIO
from types import SimpleNamespace
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib import admin
from django.core.management import call_command
from django.contrib.contenttypes.models import ContentType
from django.contrib.sessions.backends.db import SessionStore
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import IntegrityError, close_old_connections, transaction
from django.template.loader import render_to_string
from django.test import Client, RequestFactory, TestCase, TransactionTestCase, override_settings, skipUnlessDBFeature
from django.urls import reverse
from django.utils import timezone
from unittest.mock import patch

from installers.models import ProviderService, ServiceCategory, ServiceProviderProfile, ServiceQuoteRequest
from orders.models import Order, OrderItem
from orders.services import attribute_paid_order_for_ads
from products.models import Category, Product, ProductVideo, VendorProductOffer, VideoCommerceEvent
from vendors.models import VendorProfile
from staff_mobile.models import StaffMobileToken

from .adapters import v2_recommendation_adapter
from .frontend import recommendation_shelf
from .models import (
    AdBanner,
    AdCampaign,
    AdClick,
    AdCreative,
    AdEvent,
    AdImpression,
    AdPlacement,
    AdAttribution,
    AdChannelExecution,
    AdChannelReportingSnapshot,
    AdvertisingConnectionAuditLog,
    AdvertisingCredential,
    AdvertisingOAuthState,
    AdvertiserIdentity,
    CampaignAsset,
    ExternalAdvertisingAccount,
)
from .credentials import CredentialEncryptionError, credential_encryption_service
from .execution import OBJECTIVE_MAPPING, external_campaign_execution_service
from .ownership import AdvertiserOwnershipResolver
from .providers import (
    ProviderAPIError,
    ProviderAuthorizationError,
    audit_connection,
    provider_for,
    save_credential_tokens,
    validate_oauth_state,
)
from .reporting import advertiser_reporting_service
from .services import AdService
from .attribution import commerce_attribution_service


class LegacyAdsCompatibilityTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = Client()
        self.placement = AdPlacement.objects.create(
            name="Sidebar",
            slug="sidebar",
            placement_type="sidebar",
        )
        self.campaign = AdCampaign.objects.create(
            name="Legacy CPC",
            campaign_type="cpc",
            status="active",
            approved=True,
            total_budget=Decimal("25.00"),
            spent=Decimal("0.00"),
            max_bid=Decimal("0.75"),
            start_date=timezone.now(),
        )
        self.creative = AdCreative.objects.create(
            campaign=self.campaign,
            name="Creative",
            headline="Install better AV",
            clickthrough_url="https://example.com/ads",
        )
        self.banner = AdBanner.objects.create(
            campaign=self.campaign,
            creative=self.creative,
            placement=self.placement,
            title="Legacy Banner",
            cta_url="https://example.com/ads",
        )

    def test_legacy_service_selects_banner_against_current_budget_fields(self):
        selected = AdService().get_ad("sidebar")

        self.assertEqual(selected, self.banner)

    def test_legacy_service_excludes_campaigns_without_remaining_budget(self):
        self.campaign.spent = self.campaign.total_budget
        self.campaign.save(update_fields=["spent", "updated_at"])

        selected = AdService().get_ad("sidebar")

        self.assertIsNone(selected)

    def test_track_click_uses_current_max_bid_for_legacy_cpc_spend(self):
        response = self.client.post(
            reverse("ads:track_click"),
            data={"ad_id": self.banner.id},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.campaign.refresh_from_db()
        self.banner.refresh_from_db()
        self.assertEqual(AdClick.objects.count(), 1)
        self.assertEqual(self.banner.clicks, 1)
        self.assertEqual(self.campaign.clicks, 1)
        self.assertEqual(self.campaign.spent, Decimal("0.75"))

    def test_track_view_does_not_invent_missing_cpm_cost(self):
        response = self.client.post(
            reverse("ads:track_view"),
            data={"ad_id": self.banner.id},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.campaign.refresh_from_db()
        self.banner.refresh_from_db()
        self.assertEqual(AdImpression.objects.count(), 1)
        self.assertEqual(self.banner.impressions, 1)
        self.assertEqual(self.campaign.impressions, 1)
        self.assertEqual(self.campaign.spent, Decimal("0.00"))


class AdsV2FoundationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = Client()
        self.factory = RequestFactory()
        self.resolver = AdvertiserOwnershipResolver()
        self.vendor_user = self._user("vendor-owner", "vendor")
        self.other_vendor_user = self._user("other-vendor", "vendor")
        self.provider_user = self._user("provider-owner", "service_provider")
        self.customer_user = self._user("customer", "customer")
        self.vendor = self._vendor(self.vendor_user, "Vendor One", "vendor-one")
        self.other_vendor = self._vendor(self.other_vendor_user, "Vendor Two", "vendor-two")
        self.category = Category.objects.create(name="Projectors", slug="projectors")
        self.product = self._product(self.vendor_user, "Projector", "projector-1")

    def _staff_request(self, path="/", user=None, mobile=False):
        request = self.factory.get(
            path,
            HTTP_USER_AGENT="Mozilla/5.0 iPhone Mobile" if mobile else "Mozilla/5.0 Desktop",
        )
        request.user = user or get_user_model().objects.create_user(
            username=f"staff-{uuid4()}",
            email="staff@example.com",
            password="testpass123",
            is_staff=True,
        )
        request.session = SessionStore()
        request.session["ads_v2_internal_test"] = True
        return request

    def _user(self, username, user_type):
        return get_user_model().objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password="testpass123",
            user_type=user_type,
        )

    def _vendor(self, user, name, slug, can_access_ads=True):
        return VendorProfile.objects.create(
            user=user,
            store_name=name,
            store_slug=slug,
            description=f"{name} description",
            address_line_1="1 Market Street",
            city="Ikeja",
            state="Lagos",
            country="Nigeria",
            approval_status="approved",
            can_access_ads=can_access_ads,
        )

    def _product(self, vendor_user, name, slug):
        return Product.objects.create(
            vendor=vendor_user,
            category=self.category,
            sku=slug.upper(),
            name=name,
            slug=slug,
            description=f"{name} description",
            price=Decimal("100.00"),
            approval_status="approved",
        )

    def _provider(self, user):
        return ServiceProviderProfile.objects.create(
            user=user,
            business_name="Provider One",
            contact_person="Provider Owner",
            provider_type="installer",
            phone_number="+2348012345678",
            email="provider@example.com",
            state="Lagos",
            city="Ikeja",
            address="1 Provider Street",
            description="Provider description",
            verification_status=ServiceProviderProfile.STATUS_APPROVED,
        )

    def test_resolves_valid_legacy_product_ownership(self):
        result = self.resolver.resolve_product_owner(self.product)

        self.assertTrue(result.is_resolved)
        self.assertEqual(result.vendor, self.vendor)

    def test_fails_closed_for_missing_product_ownership(self):
        product = self._product(self.customer_user, "Ownerless", "ownerless")

        result = self.resolver.resolve_product_owner(product)

        self.assertFalse(result.is_resolved)
        self.assertEqual(result.reason, "missing_product_owner")

    def test_fails_closed_for_conflicting_product_ownership(self):
        VendorProductOffer.objects.create(
            vendor=self.other_vendor,
            product=self.product,
            price=Decimal("95.00"),
            stock_quantity=3,
            approval_status=VendorProductOffer.STATUS_APPROVED,
        )

        result = self.resolver.resolve_product_owner(self.product)

        self.assertFalse(result.is_resolved)
        self.assertEqual(result.reason, "conflicting_product_ownership")

    def test_fails_closed_for_vendor_product_video_mismatch(self):
        video = ProductVideo.objects.create(
            product=self.product,
            vendor=self.other_vendor,
            title="Conflicting Video",
            source="youtube",
            youtube_url="https://example.com/video",
            moderation_status="approved",
        )

        result = self.resolver.resolve_product_video_owner(video)

        self.assertFalse(result.is_resolved)
        self.assertEqual(result.reason, "conflicting_video_product_owner")

    def test_rejects_unauthorized_campaign_ownership(self):
        identity = self.resolver.get_or_create_identity(
            self.resolver.resolve_product_owner(self.product)
        )

        self.assertTrue(self.resolver.can_user_manage_advertiser(self.vendor_user, identity))
        self.assertFalse(self.resolver.can_user_manage_advertiser(self.other_vendor_user, identity))

    def test_resolves_provider_service_ownership(self):
        provider = self._provider(self.provider_user)
        service_category = ServiceCategory.objects.create(name="Installation", slug="installation")
        service = ProviderService.objects.create(
            provider=provider,
            category=service_category,
            service_name="Projector Installation",
        )

        result = self.resolver.resolve_provider_service_owner(service)

        self.assertTrue(result.is_resolved)
        self.assertEqual(result.provider, provider)

    def test_campaign_asset_uses_ads_identity_without_changing_product_ownership(self):
        identity = self.resolver.get_or_create_identity(
            self.resolver.resolve_product_owner(self.product)
        )
        campaign = AdCampaign.objects.create(
            name="V2 Campaign",
            status="draft",
            advertiser_identity=identity,
        )
        asset = CampaignAsset.objects.create(
            campaign=campaign,
            advertiser_identity=identity,
            asset_type=CampaignAsset.ASSET_PRODUCT,
            content_type=ContentType.objects.get_for_model(self.product),
            object_id=self.product.pk,
        )

        self.assertEqual(asset.content_object, self.product)
        self.assertEqual(self.product.vendor, self.vendor_user)

    def test_advertiser_identity_requires_matching_owner_shape(self):
        identity = AdvertiserIdentity(
            owner_type=AdvertiserIdentity.OWNER_VENDOR,
            user=self.vendor_user,
            display_name="Invalid Vendor Identity",
        )

        with self.assertRaises(ValidationError):
            identity.full_clean()

    def test_duplicate_external_account_is_rejected(self):
        identity = self.resolver.get_or_create_identity(
            self.resolver.resolve_product_owner(self.product)
        )
        ExternalAdvertisingAccount.objects.create(
            advertiser_identity=identity,
            channel=ExternalAdvertisingAccount.CHANNEL_META,
            external_account_id="act_123",
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ExternalAdvertisingAccount.objects.create(
                    advertiser_identity=identity,
                    channel=ExternalAdvertisingAccount.CHANNEL_META,
                    external_account_id="act_123",
                )

    def test_external_account_rejects_credential_like_identifiers(self):
        identity = self.resolver.get_or_create_identity(
            self.resolver.resolve_product_owner(self.product)
        )
        account = ExternalAdvertisingAccount(
            advertiser_identity=identity,
            channel=ExternalAdvertisingAccount.CHANNEL_META,
            external_account_id="Bearer secret-token",
        )

        with self.assertRaises(ValidationError):
            account.full_clean()

    def test_duplicate_active_channel_execution_is_rejected(self):
        identity = self.resolver.get_or_create_identity(
            self.resolver.resolve_product_owner(self.product)
        )
        campaign = AdCampaign.objects.create(
            name="Channel Campaign",
            status="draft",
            advertiser_identity=identity,
        )
        AdChannelExecution.objects.create(
            campaign=campaign,
            advertiser_identity=identity,
            channel=AdChannelExecution.CHANNEL_INTERNAL,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AdChannelExecution.objects.create(
                    campaign=campaign,
                    advertiser_identity=identity,
                    channel=AdChannelExecution.CHANNEL_INTERNAL,
                )

    def test_channel_execution_rejects_campaign_advertiser_mismatch(self):
        identity = self.resolver.get_or_create_identity(
            self.resolver.resolve_product_owner(self.product)
        )
        other_identity = AdvertiserIdentity.objects.create(
            owner_type=AdvertiserIdentity.OWNER_VENDOR,
            vendor=self.other_vendor,
            user=self.other_vendor_user,
            display_name="Other Vendor",
        )
        campaign = AdCampaign.objects.create(
            name="Mismatched Channel Campaign",
            status="draft",
            advertiser_identity=identity,
        )
        execution = AdChannelExecution(
            campaign=campaign,
            advertiser_identity=other_identity,
            channel=AdChannelExecution.CHANNEL_INTERNAL,
        )

        with self.assertRaises(ValidationError):
            execution.full_clean()

    def test_campaign_asset_rejects_invalid_ownership(self):
        identity = self.resolver.get_or_create_identity(
            self.resolver.resolve_product_owner(self.product)
        )
        other_identity = AdvertiserIdentity.objects.create(
            owner_type=AdvertiserIdentity.OWNER_VENDOR,
            vendor=self.other_vendor,
            user=self.other_vendor_user,
            display_name="Other Vendor",
        )
        campaign = AdCampaign.objects.create(
            name="Invalid Asset Campaign",
            status="draft",
            advertiser_identity=other_identity,
        )
        asset = CampaignAsset(
            campaign=campaign,
            advertiser_identity=other_identity,
            asset_type=CampaignAsset.ASSET_PRODUCT,
            content_type=ContentType.objects.get_for_model(self.product),
            object_id=self.product.pk,
        )

        with self.assertRaises(ValidationError):
            asset.full_clean()

        self.assertEqual(identity.vendor, self.vendor)

    def test_ad_event_idempotency_key_is_unique(self):
        event_uuid = uuid4()
        AdEvent.objects.create(event_uuid=event_uuid, event_type=AdEvent.EVENT_IMPRESSION)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AdEvent.objects.create(event_uuid=event_uuid, event_type=AdEvent.EVENT_CLICK)

    def test_attribution_allows_nullable_revenue_for_non_financial_foundation(self):
        event = AdEvent.objects.create(event_type=AdEvent.EVENT_CLICK)
        attribution = AdAttribution.objects.create(
            source_event=event,
            attribution_type=AdAttribution.ATTR_CLICK_THROUGH,
        )

        self.assertIsNone(attribution.revenue_amount)

    def test_v2_api_is_disabled_by_default(self):
        response = self.client.get(reverse("ads_api:recommendations_v2"))

        self.assertEqual(response.status_code, 404)

    @override_settings(ADS_RECOMMENDATION_V2_API_ENABLED=True, ADS_RECOMMENDATION_V2_WEB_ENABLED=True)
    def test_v2_event_endpoint_is_idempotent_by_event_uuid(self):
        event_uuid = str(uuid4())

        first = self.client.post(
            reverse("ads_api:events_v2"),
            data={"event_uuid": event_uuid, "event_type": AdEvent.EVENT_IMPRESSION},
            content_type="application/json",
        )
        second = self.client.post(
            reverse("ads_api:events_v2"),
            data={"event_uuid": event_uuid, "event_type": AdEvent.EVENT_IMPRESSION},
            content_type="application/json",
        )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(AdEvent.objects.filter(event_uuid=event_uuid).count(), 1)

    @override_settings(ADS_RECOMMENDATION_V2_API_ENABLED=True, ADS_RECOMMENDATION_V2_WEB_ENABLED=True)
    def test_v2_event_endpoint_rejects_client_conversion_events(self):
        response = self.client.post(
            reverse("ads_api:events_v2"),
            data={"event_uuid": str(uuid4()), "event_type": AdEvent.EVENT_CONVERSION},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(AdEvent.objects.count(), 0)

    @override_settings(ADS_RECOMMENDATION_V2_API_ENABLED=True)
    def test_v2_event_endpoint_redacts_sensitive_metadata(self):
        response = self.client.post(
            reverse("ads_api:events_v2"),
            data={
                "event_uuid": str(uuid4()),
                "event_type": AdEvent.EVENT_CLICK,
                "metadata": {
                    "placement": "home",
                    "revenue": "999999",
                    "access_token": "secret",
                },
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        event = AdEvent.objects.get()
        self.assertEqual(event.metadata, {"placement": "home"})

    @override_settings(ADS_RECOMMENDATION_V2_API_ENABLED=True)
    def test_v2_event_endpoint_rejects_oversized_payloads(self):
        response = self.client.post(
            reverse("ads_api:events_v2"),
            data={
                "event_uuid": str(uuid4()),
                "event_type": AdEvent.EVENT_CLICK,
                "metadata": {"blob": "x" * 5000},
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 413)

    def _campaign_asset(self, product=None, metadata=None, campaign_kwargs=None, identity=None):
        product = product or self.product
        identity = identity or self.resolver.get_or_create_identity(
            self.resolver.resolve_product_owner(product)
        )
        campaign_defaults = {
            "name": f"Sponsored {product.slug}",
            "campaign_type": "sponsored",
            "status": "active",
            "approved": True,
            "start_date": timezone.now() - timedelta(days=1),
            "end_date": timezone.now() + timedelta(days=1),
            "total_budget": Decimal("100.00"),
            "spent": Decimal("0.00"),
            "max_bid": Decimal("1.00"),
            "advertiser_identity": identity,
        }
        campaign_defaults.update(campaign_kwargs or {})
        campaign = AdCampaign.objects.create(**campaign_defaults)
        return CampaignAsset.objects.create(
            campaign=campaign,
            advertiser_identity=identity,
            asset_type=CampaignAsset.ASSET_PRODUCT,
            content_type=ContentType.objects.get_for_model(product),
            object_id=product.pk,
            title=product.name,
            metadata={
                "placements": ["product_recommendations"],
                "devices": ["desktop"],
                "countries": ["NG"],
                "quality_score": 0.9,
                **(metadata or {}),
            },
        )

    @override_settings(
        ADS_RECOMMENDATION_V2_API_ENABLED=True,
        ADS_RECOMMENDATION_V2_WEB_ENABLED=True,
    )
    def test_organic_only_recommendations_when_sponsored_disabled(self):
        self._campaign_asset()

        response = self.client.get(
            reverse("ads_api:recommendations_v2"),
            {"placement": "product_recommendations", "device": "desktop", "country": "NG", "limit": 4},
        )

        self.assertEqual(response.status_code, 200)
        results = response.json()["results"]
        self.assertTrue(results)
        self.assertTrue(all(not item["sponsored"] for item in results))

    @override_settings(ADS_RECOMMENDATION_V2_API_ENABLED=True, ADS_RECOMMENDATION_V2_WEB_ENABLED=True, ADS_RECOMMENDATION_V2_SPONSORED_ENABLED=True)
    def test_sponsored_candidate_eligibility_label_and_delivery_id(self):
        self._campaign_asset()

        response = self.client.get(
            reverse("ads_api:recommendations_v2"),
            {"placement": "product_recommendations", "device": "desktop", "country": "NG", "limit": 5},
        )

        sponsored = [item for item in response.json()["results"] if item["sponsored"]]
        self.assertEqual(len(sponsored), 1)
        self.assertEqual(sponsored[0]["label"], "Sponsored")
        self.assertTrue(sponsored[0]["tracking"]["delivery_id"])
        self.assertEqual(sponsored[0]["sponsor"]["id"], self.vendor.id)

    @override_settings(ADS_RECOMMENDATION_V2_API_ENABLED=True, ADS_RECOMMENDATION_V2_WEB_ENABLED=True, ADS_RECOMMENDATION_V2_SPONSORED_ENABLED=True)
    def test_irrelevant_sponsored_candidate_cannot_override_organic(self):
        unrelated = self._product(self.vendor_user, "Cable", "cable-1")
        self._campaign_asset(product=unrelated, metadata={"placements": ["product_recommendations"]})

        response = self.client.get(
            reverse("ads_api:recommendations_v2"),
            {
                "placement": "product_recommendations",
                "product_id": self.product.id,
                "device": "desktop",
                "country": "NG",
                "limit": 4,
            },
        )

        results = response.json()["results"]
        self.assertFalse(results[0]["sponsored"])
        self.assertLessEqual(len([item for item in results if item["sponsored"]]), 1)

    @override_settings(ADS_RECOMMENDATION_V2_API_ENABLED=True, ADS_RECOMMENDATION_V2_WEB_ENABLED=True, ADS_RECOMMENDATION_V2_SPONSORED_ENABLED=True)
    def test_sponsored_candidate_fail_closed_filters(self):
        cases = [
            ({"status": "paused"}, {}, "inactive_campaign"),
            ({"approved": False}, {}, "unapproved_campaign"),
            ({"end_date": timezone.now() - timedelta(days=1)}, {}, "expired_campaign"),
            ({}, {"placements": ["search"]}, "wrong_placement"),
            ({}, {"devices": ["mobile"]}, "wrong_device"),
            ({}, {"countries": ["US"]}, "wrong_country"),
            ({"spent": Decimal("100.00"), "total_budget": Decimal("100.00")}, {}, "budget_limit"),
            ({}, {"quality_score": 0.1}, "quality_filter"),
            ({}, {"policy_blocked": True}, "policy_block"),
        ]

        for campaign_kwargs, metadata, _label in cases:
            CampaignAsset.objects.all().delete()
            AdCampaign.objects.all().delete()
            self._campaign_asset(campaign_kwargs=campaign_kwargs, metadata=metadata)
            response = self.client.get(
                reverse("ads_api:recommendations_v2"),
                {"placement": "product_recommendations", "device": "desktop", "country": "NG", "limit": 5},
            )

            self.assertFalse(any(item["sponsored"] for item in response.json()["results"]))

    @override_settings(ADS_RECOMMENDATION_V2_API_ENABLED=True, ADS_RECOMMENDATION_V2_WEB_ENABLED=True, ADS_RECOMMENDATION_V2_SPONSORED_ENABLED=True)
    def test_frequency_limit_blocks_repeated_sponsored_delivery(self):
        asset = self._campaign_asset(metadata={"frequency_limit": 1})
        session = self.client.session
        session.save()
        AdEvent.objects.create(
            event_type=AdEvent.EVENT_IMPRESSION,
            asset=asset,
            campaign=asset.campaign,
            advertiser_identity=asset.advertiser_identity,
            session_id=session.session_key,
        )

        response = self.client.get(
            reverse("ads_api:recommendations_v2"),
            {"placement": "product_recommendations", "device": "desktop", "country": "NG", "limit": 5},
        )

        self.assertFalse(any(item["sponsored"] for item in response.json()["results"]))

    @override_settings(ADS_RECOMMENDATION_V2_API_ENABLED=True, ADS_RECOMMENDATION_V2_WEB_ENABLED=True, ADS_RECOMMENDATION_V2_SPONSORED_ENABLED=True)
    def test_mixing_caps_sponsored_and_prevents_consecutive_ads(self):
        second_product = self._product(self.vendor_user, "Screen", "screen-1")
        self._campaign_asset(product=self.product)
        self._campaign_asset(product=second_product, metadata={"keywords": ["screen"]})

        response = self.client.get(
            reverse("ads_api:recommendations_v2"),
            {"placement": "product_recommendations", "device": "desktop", "country": "NG", "limit": 6},
        )

        results = response.json()["results"]
        sponsored_flags = [item["sponsored"] for item in results]
        self.assertLessEqual(sum(sponsored_flags), 1)
        self.assertNotIn([True, True], [sponsored_flags[index:index + 2] for index in range(len(sponsored_flags) - 1)])

    @override_settings(ADS_RECOMMENDATION_V2_API_ENABLED=True, ADS_RECOMMENDATION_V2_WEB_ENABLED=True)
    def test_api_returns_product_video_service_provider_and_store_candidates(self):
        provider = self._provider(self.provider_user)
        service_category = ServiceCategory.objects.create(name="Mounting", slug="mounting")
        ProviderService.objects.create(provider=provider, category=service_category, service_name="Mounting")
        ProductVideo.objects.create(
            product=self.product,
            vendor=self.vendor,
            title="Demo",
            source="youtube",
            youtube_url="https://example.com/demo",
            moderation_status="approved",
        )

        response = self.client.get(
            reverse("ads_api:recommendations_v2"),
            {"placement": "homepage", "limit": 20},
        )

        result_types = {item["type"] for item in response.json()["results"]}
        self.assertIn("product", result_types)
        self.assertIn("product_video", result_types)
        self.assertIn("service", result_types)
        self.assertIn("provider", result_types)
        self.assertIn("store", result_types)

    @override_settings(ADS_RECOMMENDATION_V2_API_ENABLED=True, ADS_RECOMMENDATION_V2_WEB_ENABLED=True, ADS_RECOMMENDATION_V2_SPONSORED_ENABLED=True)
    def test_events_reference_sponsored_delivery(self):
        self._campaign_asset()
        response = self.client.get(
            reverse("ads_api:recommendations_v2"),
            {"placement": "product_recommendations", "device": "desktop", "country": "NG", "limit": 5},
        )
        sponsored = [item for item in response.json()["results"] if item["sponsored"]][0]

        event_response = self.client.post(
            reverse("ads_api:events_v2"),
            data={
                "event_uuid": str(uuid4()),
                "event_type": AdEvent.EVENT_CLICK,
                "delivery_id": sponsored["tracking"]["delivery_id"],
                "asset_id": sponsored["tracking"]["asset_id"],
            },
            content_type="application/json",
        )

        self.assertEqual(event_response.status_code, 201)
        event = AdEvent.objects.get(event_uuid=event_response.json()["event_uuid"])
        self.assertEqual(str(event.delivery_id), sponsored["tracking"]["delivery_id"])
        self.assertEqual(event.asset_id, sponsored["tracking"]["asset_id"])

    @override_settings(
        ADS_RECOMMENDATION_V2_API_ENABLED=True,
        ADS_RECOMMENDATION_V2_SPONSORED_ENABLED=False,
        ADS_RECOMMENDATION_V2_INTERNAL_TESTING_ENABLED=True,
    )
    def test_staff_internal_test_mode_can_preview_sponsored_and_marks_context(self):
        self._campaign_asset()
        staff = self._user("ads-staff", "admin")
        staff.is_staff = True
        staff.save(update_fields=["is_staff"])
        self.client.force_login(staff)
        opt_in = self.client.post(reverse("ads_api:internal_test_session"))
        self.assertEqual(opt_in.status_code, 200)
        self.assertTrue(opt_in.json()["internal_test"])

        response = self.client.get(
            reverse("ads_api:recommendations_v2"),
            {"placement": "product_recommendations", "device": "desktop", "country": "NG", "limit": 5},
        )

        payload = response.json()
        self.assertTrue(payload["context"]["internal_test"])
        self.assertTrue(any(item["sponsored"] for item in payload["results"]))

    @override_settings(
        ADS_RECOMMENDATION_V2_API_ENABLED=True,
        ADS_RECOMMENDATION_V2_SPONSORED_ENABLED=False,
        ADS_RECOMMENDATION_V2_INTERNAL_TESTING_ENABLED=True,
        ADS_RECOMMENDATION_V2_WEB_ENABLED=True,
    )
    def test_non_staff_internal_test_mode_does_not_receive_sponsored(self):
        self._campaign_asset()
        self.client.force_login(self.customer_user)
        opt_in = self.client.post(reverse("ads_api:internal_test_session"))
        self.assertEqual(opt_in.status_code, 403)

        response = self.client.get(
            reverse("ads_api:recommendations_v2"),
            {"placement": "product_recommendations", "device": "desktop", "country": "NG", "limit": 5},
        )

        payload = response.json()
        self.assertFalse(payload["context"]["internal_test"])
        self.assertFalse(any(item["sponsored"] for item in payload["results"]))

    @override_settings(
        ADS_RECOMMENDATION_V2_API_ENABLED=True,
        ADS_RECOMMENDATION_V2_INTERNAL_TESTING_ENABLED=True,
    )
    def test_internal_test_event_metadata_is_marked_for_staff(self):
        staff = self._user("event-staff", "admin")
        staff.is_staff = True
        staff.save(update_fields=["is_staff"])
        self.client.force_login(staff)
        self.client.post(reverse("ads_api:internal_test_session"))

        response = self.client.post(
            reverse("ads_api:events_v2"),
            data={"event_uuid": str(uuid4()), "event_type": AdEvent.EVENT_CLICK},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(AdEvent.objects.get().metadata["internal_test"])

    @override_settings(
        ADS_RECOMMENDATION_V2_API_ENABLED=True,
        ADS_RECOMMENDATION_V2_INTERNAL_TESTING_ENABLED=True,
        ADS_RECOMMENDATION_V2_WEB_ENABLED=True,
    )
    def test_internal_test_query_or_header_alone_does_not_unlock_sponsored(self):
        self._campaign_asset()
        staff = self._user("ads-staff-no-session", "admin")
        staff.is_staff = True
        staff.save(update_fields=["is_staff"])
        self.client.force_login(staff)

        response = self.client.get(
            reverse("ads_api:recommendations_v2"),
            {
                "placement": "product_recommendations",
                "device": "desktop",
                "country": "NG",
                "limit": 5,
                "internal_test": "true",
            },
            HTTP_X_AROLANA_INTERNAL_TEST="true",
        )

        payload = response.json()
        self.assertFalse(payload["context"]["internal_test"])
        self.assertFalse(any(item["sponsored"] for item in payload["results"]))

    def test_server_purchase_attribution_uses_order_item_revenue(self):
        asset = self._campaign_asset()
        delivery_id = uuid4()
        click = AdEvent.objects.create(
            event_type=AdEvent.EVENT_CLICK,
            delivery_id=delivery_id,
            asset=asset,
            campaign=asset.campaign,
            advertiser_identity=asset.advertiser_identity,
            user=self.customer_user,
        )
        order = Order.objects.create(
            user=self.customer_user,
            subtotal=Decimal("200.00"),
            shipping_cost=Decimal("0.00"),
            tax=Decimal("0.00"),
            total=Decimal("200.00"),
            shipping_address="1 Customer Street",
            billing_address="1 Customer Street",
            payment_status="paid",
        )
        item = OrderItem.objects.create(
            order=order,
            product=self.product,
            quantity=2,
            price=Decimal("100.00"),
            subtotal=Decimal("200.00"),
            recommendation_section="product_recommendations",
            recommendation_algorithm="ads_v2",
        )

        attribution = commerce_attribution_service.attribute_order_item(item, source_event=click)
        duplicate = commerce_attribution_service.attribute_order_item(item, source_event=click)

        self.assertEqual(attribution.pk, duplicate.pk)
        self.assertEqual(attribution.revenue_amount, Decimal("200.00"))
        self.assertEqual(attribution.currency, "NGN")
        self.assertEqual(attribution.campaign, asset.campaign)
        self.assertEqual(attribution.advertiser_identity, asset.advertiser_identity)
        self.assertEqual(attribution.asset, asset)
        self.assertEqual(attribution.product, self.product)
        self.assertEqual(attribution.vendor, self.vendor)
        self.assertEqual(attribution.order, order)
        self.assertEqual(attribution.order_item, item)
        self.assertTrue(attribution.metadata["server_authoritative"])

    def test_paid_order_hook_attributes_once_and_skips_cancelled_orders(self):
        asset = self._campaign_asset()
        click = AdEvent.objects.create(
            event_type=AdEvent.EVENT_CLICK,
            asset=asset,
            campaign=asset.campaign,
            advertiser_identity=asset.advertiser_identity,
            user=self.customer_user,
        )
        order = Order.objects.create(
            user=self.customer_user,
            status="processing",
            subtotal=Decimal("100.00"),
            total=Decimal("100.00"),
            shipping_address="1 Customer Street",
            billing_address="1 Customer Street",
            payment_status="paid",
        )
        item = OrderItem.objects.create(
            order=order,
            product=self.product,
            quantity=1,
            price=Decimal("100.00"),
            subtotal=Decimal("100.00"),
        )

        first = attribute_paid_order_for_ads(order)
        second = attribute_paid_order_for_ads(order)

        self.assertEqual(len(first), 1)
        self.assertEqual(second[0].pk, first[0].pk)
        self.assertEqual(AdAttribution.objects.filter(order_item=item).count(), 1)

        cancelled = Order.objects.create(
            user=self.customer_user,
            status="cancelled",
            subtotal=Decimal("100.00"),
            total=Decimal("100.00"),
            shipping_address="1 Customer Street",
            billing_address="1 Customer Street",
            payment_status="paid",
        )
        OrderItem.objects.create(
            order=cancelled,
            product=self.product,
            quantity=1,
            price=Decimal("100.00"),
            subtotal=Decimal("100.00"),
        )

        self.assertEqual(attribute_paid_order_for_ads(cancelled), [])
        self.assertEqual(AdAttribution.objects.count(), 1)
        self.assertEqual(click.attributions.count(), 1)

    @override_settings(ADS_ATTRIBUTION_CLICK_LOOKBACK_DAYS=7, ADS_ATTRIBUTION_VIEW_LOOKBACK_DAYS=1)
    def test_attribution_lookback_expiration_respects_event_type_windows(self):
        asset = self._campaign_asset()
        expired_view = AdEvent.objects.create(
            event_type=AdEvent.EVENT_VIEW,
            asset=asset,
            campaign=asset.campaign,
            advertiser_identity=asset.advertiser_identity,
            user=self.customer_user,
            occurred_at=timezone.now() - timedelta(days=2),
        )
        active_click = AdEvent.objects.create(
            event_type=AdEvent.EVENT_CLICK,
            asset=asset,
            campaign=asset.campaign,
            advertiser_identity=asset.advertiser_identity,
            user=self.customer_user,
            occurred_at=timezone.now() - timedelta(days=6),
        )

        touch = commerce_attribution_service.find_last_touch(user=self.customer_user, product=self.product)

        self.assertEqual(touch, active_click)
        self.assertNotEqual(touch, expired_view)

    def test_purchase_attribution_rejects_asset_product_mismatch(self):
        asset = self._campaign_asset()
        other_product = self._product(self.vendor_user, "Speaker", "speaker-1")
        click = AdEvent.objects.create(
            event_type=AdEvent.EVENT_CLICK,
            asset=asset,
            campaign=asset.campaign,
            advertiser_identity=asset.advertiser_identity,
            user=self.customer_user,
        )
        order = Order.objects.create(
            user=self.customer_user,
            subtotal=Decimal("100.00"),
            total=Decimal("100.00"),
            shipping_address="1 Customer Street",
            billing_address="1 Customer Street",
        )
        item = OrderItem.objects.create(
            order=order,
            product=other_product,
            quantity=1,
            price=Decimal("100.00"),
            subtotal=Decimal("100.00"),
        )

        attribution = commerce_attribution_service.attribute_order_item(item, source_event=click)

        self.assertIsNone(attribution)
        self.assertEqual(AdAttribution.objects.count(), 0)

    @override_settings(ADS_RECOMMENDATION_V2_API_ENABLED=True)
    def test_client_event_cannot_create_purchase_revenue_or_conversion(self):
        response = self.client.post(
            reverse("ads_api:events_v2"),
            data={
                "event_uuid": str(uuid4()),
                "event_type": AdEvent.EVENT_CONVERSION,
                "metadata": {"revenue": "5000", "purchase": True},
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(AdAttribution.objects.count(), 0)

    def test_service_quote_attribution_records_lead_without_revenue(self):
        provider = self._provider(self.provider_user)
        service_category = ServiceCategory.objects.create(name="Install", slug="install")
        service = ProviderService.objects.create(
            provider=provider,
            category=service_category,
            service_name="Install projector",
        )
        identity = self.resolver.get_or_create_identity(
            self.resolver.resolve_provider_service_owner(service)
        )
        campaign = AdCampaign.objects.create(
            name="Provider Lead Campaign",
            status="active",
            approved=True,
            advertiser_identity=identity,
            start_date=timezone.now() - timedelta(days=1),
        )
        asset = CampaignAsset.objects.create(
            campaign=campaign,
            advertiser_identity=identity,
            asset_type=CampaignAsset.ASSET_PROVIDER_SERVICE,
            content_type=ContentType.objects.get_for_model(service),
            object_id=service.pk,
        )
        click = AdEvent.objects.create(
            event_type=AdEvent.EVENT_CLICK,
            asset=asset,
            campaign=campaign,
            advertiser_identity=identity,
            user=self.customer_user,
        )
        quote = ServiceQuoteRequest.objects.create(
            customer=self.customer_user,
            provider=provider,
            category=service_category,
            name="Customer",
            phone="+2348011111111",
            email="customer@example.com",
            state="Lagos",
            city="Ikeja",
            address="1 Customer Street",
            service_needed="Install projector",
        )

        attribution = commerce_attribution_service.attribute_service_quote(quote, source_event=click)

        self.assertIsNotNone(attribution)
        self.assertIsNone(attribution.revenue_amount)
        self.assertTrue(attribution.metadata["revenue_unavailable"])
        self.assertEqual(attribution.metadata["commerce_event"], "qualified_service_lead")

    def test_video_commerce_event_links_to_ads_attribution_without_replacing_video_event(self):
        video = ProductVideo.objects.create(
            product=self.product,
            vendor=self.vendor,
            title="Demo",
            source="youtube",
            youtube_url="https://example.com/demo",
            moderation_status="approved",
        )
        asset = self._campaign_asset()
        asset.asset_type = CampaignAsset.ASSET_PRODUCT_VIDEO
        asset.content_type = ContentType.objects.get_for_model(video)
        asset.object_id = video.pk
        asset.product_video = video
        asset.save(update_fields=["asset_type", "content_type", "object_id", "product_video", "updated_at"])
        click = AdEvent.objects.create(
            event_type=AdEvent.EVENT_CLICK,
            asset=asset,
            campaign=asset.campaign,
            advertiser_identity=asset.advertiser_identity,
            session_id="video-session",
        )
        video_event = VideoCommerceEvent.objects.create(
            content_type="sponsored",
            source_id=video.pk,
            event_type="video_cta_click",
            owner_type="vendor",
            owner_id=self.vendor.pk,
            campaign_id=asset.campaign_id,
            session_key="video-session",
            product=self.product,
            metadata={"asset_id": asset.pk},
            dedupe_key=f"video-{uuid4()}",
        )

        attribution = commerce_attribution_service.link_video_event(video_event, source_event=click)

        self.assertIsNotNone(attribution)
        self.assertEqual(attribution.target_object, video_event)
        self.assertEqual(attribution.product, self.product)
        self.assertIsNone(attribution.revenue_amount)
        self.assertEqual(VideoCommerceEvent.objects.count(), 1)

    @override_settings(
        ADS_RECOMMENDATION_V2_API_ENABLED=True,
        ADS_RECOMMENDATION_V2_APP_ENABLED=True,
        ADS_RECOMMENDATION_V2_SPONSORED_ENABLED=True,
    )
    def test_mobile_contract_exposes_safe_sponsored_payload_only(self):
        self._campaign_asset(metadata={"devices": ["mobile"]})

        response = self.client.get(
            reverse("ads_api:recommendations_v2"),
            {"placement": "product_recommendations", "device": "mobile", "limit": 5, "client": "app"},
            HTTP_USER_AGENT="ArolanaMobile/1.0",
        )

        sponsored = [item for item in response.json()["results"] if item["sponsored"]]
        self.assertTrue(sponsored)
        allowed_keys = {"type", "id", "score", "reasons", "sponsored", "label", "sponsor", "tracking", "item"}
        self.assertLessEqual(set(sponsored[0].keys()), allowed_keys)
        self.assertNotIn("score_components", sponsored[0])
        self.assertNotIn("max_bid", str(sponsored[0]))

        adapted = response.json()["adapter_results"]
        sponsored_adapted = [item for item in adapted if item["sponsored"]]
        self.assertTrue(sponsored_adapted)
        self.assertEqual(sponsored_adapted[0]["ui"]["badge"], "Sponsored")
        self.assertEqual(sponsored_adapted[0]["ui"]["client"], "app")
        self.assertTrue(sponsored_adapted[0]["tracking"]["delivery_id"])

    def test_v2_adapter_supports_all_initial_result_types(self):
        results = [
            {"type": "product", "id": 1, "item": {"name": "Product"}, "sponsored": False, "tracking": {}},
            {"type": "product_video", "id": 2, "item": {"title": "Video"}, "sponsored": True, "label": "Sponsored", "sponsor": {"name": "Vendor"}, "tracking": {"delivery_id": "d", "asset_id": 1, "campaign_id": 2}},
            {"type": "provider_service", "id": 3, "item": {"name": "Install"}, "sponsored": True, "label": "Sponsored", "tracking": {}},
            {"type": "provider_profile", "id": 4, "item": {"name": "Provider"}, "sponsored": False, "tracking": {}},
            {"type": "vendor_store", "id": 5, "item": {"name": "Store"}, "sponsored": False, "tracking": {}},
        ]

        adapted = v2_recommendation_adapter.adapt_results(results, surface="homepage", client="mobile_web")

        self.assertEqual([item["type"] for item in adapted], ["product", "product_video", "service", "provider", "store"])
        self.assertEqual(adapted[1]["ui"]["badge"], "Sponsored")
        self.assertEqual(adapted[2]["ui"]["component"], "service_card")

    def test_advertiser_reporting_is_aggregate_and_excludes_internal_test_traffic(self):
        asset = self._campaign_asset()
        AdEvent.objects.create(
            event_type=AdEvent.EVENT_IMPRESSION,
            asset=asset,
            campaign=asset.campaign,
            advertiser_identity=asset.advertiser_identity,
        )
        AdEvent.objects.create(
            event_type=AdEvent.EVENT_CLICK,
            asset=asset,
            campaign=asset.campaign,
            advertiser_identity=asset.advertiser_identity,
            metadata={"internal_test": True},
        )
        click = AdEvent.objects.create(
            event_type=AdEvent.EVENT_CLICK,
            asset=asset,
            campaign=asset.campaign,
            advertiser_identity=asset.advertiser_identity,
            user=self.customer_user,
        )
        order = Order.objects.create(
            user=self.customer_user,
            subtotal=Decimal("100.00"),
            total=Decimal("100.00"),
            shipping_address="1 Customer Street",
            billing_address="1 Customer Street",
            payment_status="paid",
        )
        OrderItem.objects.create(
            order=order,
            product=self.product,
            quantity=1,
            price=Decimal("100.00"),
            subtotal=Decimal("100.00"),
        )
        attribute_paid_order_for_ads(order)

        summary = advertiser_reporting_service.campaign_summary(asset.advertiser_identity)

        self.assertEqual(summary["impressions"], 1)
        self.assertEqual(summary["clicks"], 1)
        self.assertEqual(summary["orders"], 1)
        self.assertEqual(summary["attributed_revenue"], Decimal("100.00"))
        self.assertNotIn("customer_email", summary)
        self.assertNotIn("order_number", summary)
        self.assertNotIn("payment", summary)

    def test_attribution_lifecycle_reversal_is_history_preserving_and_idempotent(self):
        asset = self._campaign_asset()
        click = AdEvent.objects.create(
            event_type=AdEvent.EVENT_CLICK,
            asset=asset,
            campaign=asset.campaign,
            advertiser_identity=asset.advertiser_identity,
            user=self.customer_user,
        )
        order = Order.objects.create(
            user=self.customer_user,
            subtotal=Decimal("100.00"),
            total=Decimal("100.00"),
            shipping_address="1 Customer Street",
            billing_address="1 Customer Street",
            payment_status="paid",
        )
        item = OrderItem.objects.create(
            order=order,
            product=self.product,
            quantity=1,
            price=Decimal("100.00"),
            subtotal=Decimal("100.00"),
        )
        attribution = commerce_attribution_service.attribute_order_item(item, source_event=click)

        changed = commerce_attribution_service.reverse_order_attribution(
            order,
            reason="paypal_full_refund",
            reference="REFUND-1",
        )
        repeated = commerce_attribution_service.reverse_order_attribution(
            order,
            reason="paypal_full_refund",
            reference="REFUND-1",
        )
        attribution.refresh_from_db()

        self.assertEqual(len(changed), 1)
        self.assertEqual(repeated, [])
        self.assertEqual(AdAttribution.objects.count(), 1)
        self.assertEqual(attribution.lifecycle_status, AdAttribution.LIFECYCLE_REVERSED)
        self.assertEqual(attribution.gross_revenue_amount, Decimal("100.00"))
        self.assertEqual(attribution.net_revenue_amount, Decimal("0.00"))
        self.assertEqual(attribution.reversal_reference, "REFUND-1")
        self.assertIsNotNone(attribution.reversed_at)

    def test_reporting_uses_net_revenue_after_reversal(self):
        asset = self._campaign_asset()
        click = AdEvent.objects.create(
            event_type=AdEvent.EVENT_CLICK,
            asset=asset,
            campaign=asset.campaign,
            advertiser_identity=asset.advertiser_identity,
            user=self.customer_user,
        )
        order = Order.objects.create(
            user=self.customer_user,
            subtotal=Decimal("100.00"),
            total=Decimal("100.00"),
            shipping_address="1 Customer Street",
            billing_address="1 Customer Street",
            payment_status="paid",
        )
        item = OrderItem.objects.create(
            order=order,
            product=self.product,
            quantity=1,
            price=Decimal("100.00"),
            subtotal=Decimal("100.00"),
        )
        commerce_attribution_service.attribute_order_item(item, source_event=click)
        commerce_attribution_service.reverse_order_attribution(
            order,
            reason="paypal_full_refund",
            reference="REFUND-2",
        )

        summary = advertiser_reporting_service.campaign_summary(asset.advertiser_identity)

        self.assertEqual(summary["orders"], 0)
        self.assertEqual(summary["attributed_revenue"], Decimal("0.00"))

    @override_settings(ADS_ADVERTISER_DASHBOARD_ENABLED=False)
    def test_advertiser_dashboard_api_disabled_by_flag(self):
        self.client.force_login(self.vendor_user)

        response = self.client.get(reverse("ads_api:management_overview"))

        self.assertEqual(response.status_code, 404)

    @override_settings(ADS_ADVERTISER_DASHBOARD_ENABLED=True)
    def test_advertiser_dashboard_requires_authentication(self):
        response = self.client.get(reverse("ads_api:management_overview"))

        self.assertEqual(response.status_code, 401)

    @override_settings(ADS_ADVERTISER_DASHBOARD_ENABLED=True)
    def test_vendor_campaign_create_and_isolation(self):
        self.client.force_login(self.vendor_user)
        content_type = ContentType.objects.get_for_model(self.product)

        response = self.client.post(
            reverse("ads_api:management_campaigns"),
            data={
                "name": "Vendor product promo",
                "objective": AdCampaign.OBJECTIVE_SALES,
                "asset_type": CampaignAsset.ASSET_PRODUCT,
                "content_type_id": content_type.pk,
                "object_id": self.product.pk,
                "submit": True,
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        campaign = AdCampaign.objects.get(name="Vendor product promo")
        self.assertEqual(campaign.advertiser_identity.vendor, self.vendor)
        self.assertEqual(campaign.status, "pending")
        self.assertFalse(campaign.approved)

        self.client.force_login(self.other_vendor_user)
        detail = self.client.get(reverse("ads_api:management_campaign_detail", args=[campaign.pk]))
        self.assertEqual(detail.status_code, 404)

    @override_settings(ADS_ADVERTISER_DASHBOARD_ENABLED=True)
    def test_wrong_owner_asset_blocked(self):
        other_product = self._product(self.other_vendor_user, "Other Projector", "other-projector")
        content_type = ContentType.objects.get_for_model(other_product)
        self.client.force_login(self.vendor_user)

        response = self.client.post(
            reverse("ads_api:management_campaigns"),
            data={
                "name": "Wrong owner",
                "asset_type": CampaignAsset.ASSET_PRODUCT,
                "content_type_id": content_type.pk,
                "object_id": other_product.pk,
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("asset_vendor_mismatch", response.json()["error"])

    @override_settings(ADS_ADVERTISER_DASHBOARD_ENABLED=True)
    def test_campaign_create_supports_product_video_service_provider_and_store_assets(self):
        provider = self._provider(self.provider_user)
        service_category = ServiceCategory.objects.create(name="AV", slug="av")
        service = ProviderService.objects.create(
            provider=provider,
            category=service_category,
            service_name="Install AV",
        )
        video = ProductVideo.objects.create(
            product=self.product,
            vendor=self.vendor,
            title="Product demo",
            source="youtube",
            youtube_url="https://example.com/demo",
            moderation_status="approved",
        )

        cases = [
            (self.vendor_user, CampaignAsset.ASSET_PRODUCT_VIDEO, video),
            (self.vendor_user, CampaignAsset.ASSET_VENDOR_STORE, self.vendor),
            (self.provider_user, CampaignAsset.ASSET_PROVIDER_SERVICE, service),
            (self.provider_user, CampaignAsset.ASSET_PROVIDER_PROFILE, provider),
        ]

        for user, asset_type, obj in cases:
            self.client.force_login(user)
            response = self.client.post(
                reverse("ads_api:management_campaigns"),
                data={
                    "name": f"{asset_type} campaign",
                    "objective": AdCampaign.OBJECTIVE_PRODUCT_VISITS,
                    "asset_type": asset_type,
                    "content_type_id": ContentType.objects.get_for_model(obj).pk,
                    "object_id": obj.pk,
                    "submit": False,
                },
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 201, response.content)
            self.assertEqual(response.json()["campaign"]["status"], "draft")

    @override_settings(ADS_ADVERTISER_DASHBOARD_ENABLED=True)
    def test_creative_management_is_limited_to_owned_campaigns_and_safe_types(self):
        identity = self.resolver.get_or_create_identity(
            self.resolver.resolve_product_owner(self.product)
        )
        campaign = AdCampaign.objects.create(
            name="Creative Campaign",
            advertiser_identity=identity,
            start_date=timezone.now(),
        )
        self.client.force_login(self.vendor_user)

        response = self.client.post(
            reverse("ads_api:management_creatives"),
            data={
                "campaign_id": campaign.pk,
                "creative_type": "html5",
                "headline": "Unsafe HTML",
                "clickthrough_url": "https://arolana.com",
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

        response = self.client.post(
            reverse("ads_api:management_creatives"),
            data={
                "campaign_id": campaign.pk,
                "creative_type": "image",
                "headline": "Safe creative",
                "description": "Aggregate only",
                "clickthrough_url": "https://arolana.com",
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)

    @override_settings(
        ADS_ADVERTISER_DASHBOARD_ENABLED=True,
        ADS_META_CONNECTION_ENABLED=False,
        ADS_GOOGLE_CONNECTION_ENABLED=False,
        ADS_TIKTOK_CONNECTION_ENABLED=False,
        ADS_LINKEDIN_CONNECTION_ENABLED=False,
    )
    def test_connected_accounts_are_shell_only(self):
        self.client.force_login(self.vendor_user)

        response = self.client.get(reverse("ads_api:management_connected_accounts"))

        self.assertEqual(response.status_code, 200)
        accounts = response.json()["accounts"]
        self.assertEqual({item["channel"] for item in accounts}, {"meta", "google", "tiktok", "linkedin"})
        self.assertTrue(all(item["available"] is False for item in accounts))

    @override_settings(ADS_ADVERTISER_DASHBOARD_ENABLED=True)
    def test_connected_account_connect_requires_authentication(self):
        response = self.client.post(reverse("ads_api:management_connected_account_connect", args=["google"]))

        self.assertEqual(response.status_code, 401)

    @override_settings(ADS_ADVERTISER_DASHBOARD_ENABLED=True)
    def test_staff_mobile_bearer_can_read_only_its_owner_scoped_connected_accounts(self):
        identity = self.resolver.get_or_create_identity(self.resolver.resolve_product_owner(self.product))
        other_identity = AdvertiserIdentity.objects.create(
            owner_type=AdvertiserIdentity.OWNER_VENDOR,
            vendor=self.other_vendor,
            user=self.other_vendor_user,
            display_name="Other Vendor",
        )
        ExternalAdvertisingAccount.objects.create(
            advertiser_identity=other_identity,
            channel=ExternalAdvertisingAccount.CHANNEL_GOOGLE,
            external_account_id="other-customer",
            status=ExternalAdvertisingAccount.STATUS_CONNECTED,
        )
        session = StaffMobileToken.issue(role=StaffMobileToken.ROLE_VENDOR, user=self.vendor_user)

        response = self.client.get(
            reverse("ads_api:management_connected_accounts"),
            HTTP_AUTHORIZATION=f"Bearer {session.token}",
        )

        self.assertEqual(response.status_code, 200, response.content)
        account_ids = [
            account["external_account_id"]
            for shell in response.json()["accounts"]
            for account in shell["accounts"]
        ]
        self.assertNotIn("other-customer", account_ids)
        self.assertEqual(identity.owner_type, AdvertiserIdentity.OWNER_VENDOR)

    @override_settings(
        ADS_ADVERTISER_DASHBOARD_ENABLED=True,
        ADS_GOOGLE_CONNECTION_ENABLED=True,
        ADS_GOOGLE_CLIENT_ID="google-client",
        ADS_GOOGLE_CLIENT_SECRET="google-secret",
    )
    def test_staff_mobile_google_connect_creates_state_bound_to_mobile_session(self):
        session = StaffMobileToken.issue(role=StaffMobileToken.ROLE_VENDOR, user=self.vendor_user)

        response = self.client.post(
            reverse("ads_api:management_connected_account_connect", args=["google"]),
            data=json.dumps({"mobile_oauth": True}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {session.token}",
        )

        self.assertEqual(response.status_code, 200, response.content)
        state = AdvertisingOAuthState.objects.get()
        self.assertEqual(state.user_id, self.vendor_user.pk)
        self.assertEqual(state.session_key, "")
        self.assertEqual(state.metadata["mobile_staff_session_id"], session.pk)
        self.assertEqual(state.metadata["mobile_return_url"], "arolanastaffmobile://ads-connected-accounts")
        self.assertNotIn(session.token, response.content.decode("utf-8"))

    @override_settings(ADS_ADVERTISER_DASHBOARD_ENABLED=True)
    def test_staff_mobile_google_selection_is_owner_scoped_and_uses_existing_select_contract(self):
        identity = self.resolver.get_or_create_identity(self.resolver.resolve_product_owner(self.product))
        pending = ExternalAdvertisingAccount.objects.create(
            advertiser_identity=identity,
            channel=ExternalAdvertisingAccount.CHANNEL_GOOGLE,
            external_account_id="pending:staff-mobile-selection",
            status=ExternalAdvertisingAccount.STATUS_PENDING,
            metadata={"discovered_accounts": [{"external_account_id": "6711004233", "display_name": "Google Test"}]},
        )
        session = StaffMobileToken.issue(role=StaffMobileToken.ROLE_VENDOR, user=self.vendor_user)

        response = self.client.post(
            reverse("ads_api:management_connected_account_select", args=["google"]),
            data=json.dumps({"connection_id": pending.pk, "external_account_id": "6711004233"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {session.token}",
        )

        self.assertEqual(response.status_code, 200, response.content)
        pending.refresh_from_db()
        self.assertEqual(pending.status, ExternalAdvertisingAccount.STATUS_CONNECTED)
        self.assertEqual(pending.external_account_id, "6711004233")
        self.assertNotIn(session.token, response.content.decode("utf-8"))

    @override_settings(ADS_ADVERTISER_DASHBOARD_ENABLED=True, ADS_GOOGLE_CONNECTION_ENABLED=True)
    def test_staff_mobile_google_callback_failure_returns_safe_app_error_without_credentials(self):
        identity = self.resolver.get_or_create_identity(self.resolver.resolve_product_owner(self.product))
        session = StaffMobileToken.issue(role=StaffMobileToken.ROLE_VENDOR, user=self.vendor_user)
        state = AdvertisingOAuthState.objects.create(
            provider="google",
            state="mobile-state-without-code",
            user=self.vendor_user,
            advertiser_identity=identity,
            session_key="",
            expires_at=timezone.now() + timedelta(minutes=5),
            metadata={
                "mobile_staff_session_id": session.pk,
                "mobile_return_url": "arolanastaffmobile://ads-connected-accounts",
            },
        )

        response = self.client.get(
            reverse("ads_api:management_connected_account_callback", args=["google"]),
            {"state": state.state},
            HTTP_ACCEPT="text/html",
        )

        self.assertEqual(response.status_code, 302, response.content)
        self.assertEqual(
            response["Location"],
            "arolanastaffmobile://ads-connected-accounts?provider=google&oauth_error=connection_failed",
        )
        self.assertNotIn(session.token, response["Location"])

    @override_settings(
        ADS_ADVERTISER_DASHBOARD_ENABLED=True,
        ADS_GOOGLE_CONNECTION_ENABLED=True,
        ADS_GOOGLE_CLIENT_ID="google-client",
        ADS_GOOGLE_CLIENT_SECRET="google-secret",
        ADS_GOOGLE_DEVELOPER_TOKEN="developer-token",
        ADS_GOOGLE_LOGIN_CUSTOMER_ID="",
        ADS_CREDENTIAL_ENCRYPTION_KEY="test-credential-key",
    )
    @patch("ads.providers.requests.get")
    @patch("ads.providers.requests.post")
    def test_staff_mobile_google_callback_returns_to_fixed_app_scheme_with_pending_selection(self, mock_post, mock_get):
        class Response:
            status_code = 200

            def __init__(self, payload):
                self.payload = payload

            def json(self):
                return self.payload

        def google_post(url, **_kwargs):
            if url == "https://oauth2.googleapis.com/token":
                return Response({
                    "access_token": "access-secret-token",
                    "refresh_token": "refresh-secret-token",
                    "expires_in": 3600,
                    "scope": "https://www.googleapis.com/auth/adwords",
                })
            return Response({"results": [{"customerClient": {
                "clientCustomer": "customers/6711004233",
                "descriptiveName": "Arolana Ads Test Client",
                "manager": False,
                "status": "ENABLED",
                "level": 0,
            }}]})

        mock_post.side_effect = google_post
        mock_get.return_value = Response({"resourceNames": ["customers/6711004233"]})
        session = StaffMobileToken.issue(role=StaffMobileToken.ROLE_VENDOR, user=self.vendor_user)
        connect = self.client.post(
            reverse("ads_api:management_connected_account_connect", args=["google"]),
            data=json.dumps({"mobile_oauth": True}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {session.token}",
        )
        self.assertEqual(connect.status_code, 200, connect.content)
        state = AdvertisingOAuthState.objects.get()

        callback = self.client.get(
            reverse("ads_api:management_connected_account_callback", args=["google"]),
            {"state": state.state, "code": "oauth-code"},
            HTTP_ACCEPT="text/html",
        )

        self.assertEqual(callback.status_code, 302, callback.content)
        self.assertTrue(callback["Location"].startswith("arolanastaffmobile://ads-connected-accounts?"))
        self.assertIn("provider=google", callback["Location"])
        self.assertIn("connection_id=", callback["Location"])
        self.assertNotIn("access-secret-token", callback["Location"])
        self.assertNotIn("refresh-secret-token", callback["Location"])

    @override_settings(ADS_ADVERTISER_DASHBOARD_ENABLED=True, ADS_GOOGLE_CONNECTION_ENABLED=True)
    def test_staff_mobile_callback_rejects_expired_state_without_creating_or_updating_connection(self):
        identity = self.resolver.get_or_create_identity(self.resolver.resolve_product_owner(self.product))
        session = StaffMobileToken.issue(role=StaffMobileToken.ROLE_VENDOR, user=self.vendor_user)
        state = AdvertisingOAuthState.objects.create(
            provider="google",
            state="expired-mobile-oauth-state",
            user=self.vendor_user,
            advertiser_identity=identity,
            session_key="",
            expires_at=timezone.now() - timedelta(seconds=1),
            metadata={
                "mobile_staff_session_id": session.pk,
                "mobile_return_url": "arolanastaffmobile://ads-connected-accounts",
            },
        )
        before_count = ExternalAdvertisingAccount.objects.count()

        response = self.client.get(
            reverse("ads_api:management_connected_account_callback", args=["google"]),
            {"state": state.state, "code": "oauth-code"},
            HTTP_ACCEPT="text/html",
        )

        self.assertEqual(response.status_code, 302, response.content)
        self.assertIn("oauth_error=connection_failed", response["Location"])
        self.assertEqual(ExternalAdvertisingAccount.objects.count(), before_count)
        state.refresh_from_db()
        self.assertIsNone(state.used_at)

    @override_settings(ADS_ADVERTISER_DASHBOARD_ENABLED=True, ADS_GOOGLE_CONNECTION_ENABLED=True)
    def test_staff_mobile_callback_rejects_inactive_token_without_creating_or_updating_connection(self):
        identity = self.resolver.get_or_create_identity(self.resolver.resolve_product_owner(self.product))
        session = StaffMobileToken.issue(role=StaffMobileToken.ROLE_VENDOR, user=self.vendor_user)
        session.is_active = False
        session.save(update_fields=["is_active", "updated_at"])
        state = AdvertisingOAuthState.objects.create(
            provider="google",
            state="inactive-token-mobile-oauth-state",
            user=self.vendor_user,
            advertiser_identity=identity,
            session_key="",
            expires_at=timezone.now() + timedelta(minutes=5),
            metadata={
                "mobile_staff_session_id": session.pk,
                "mobile_return_url": "arolanastaffmobile://ads-connected-accounts",
            },
        )
        before_count = ExternalAdvertisingAccount.objects.count()

        response = self.client.get(
            reverse("ads_api:management_connected_account_callback", args=["google"]),
            {"state": state.state, "code": "oauth-code"},
            HTTP_ACCEPT="text/html",
        )

        self.assertEqual(response.status_code, 401, response.content)
        self.assertEqual(ExternalAdvertisingAccount.objects.count(), before_count)
        state.refresh_from_db()
        self.assertIsNone(state.used_at)

    @override_settings(ADS_ADVERTISER_DASHBOARD_ENABLED=True, ADS_GOOGLE_CONNECTION_ENABLED=True)
    def test_staff_mobile_callback_rejects_token_for_different_user_without_creating_connection(self):
        identity = self.resolver.get_or_create_identity(self.resolver.resolve_product_owner(self.product))
        other_session = StaffMobileToken.issue(
            role=StaffMobileToken.ROLE_VENDOR,
            user=self.other_vendor_user,
        )
        state = AdvertisingOAuthState.objects.create(
            provider="google",
            state="wrong-user-mobile-oauth-state",
            user=self.vendor_user,
            advertiser_identity=identity,
            session_key="",
            expires_at=timezone.now() + timedelta(minutes=5),
            metadata={
                "mobile_staff_session_id": other_session.pk,
                "mobile_return_url": "arolanastaffmobile://ads-connected-accounts",
            },
        )
        before_count = ExternalAdvertisingAccount.objects.count()

        response = self.client.get(
            reverse("ads_api:management_connected_account_callback", args=["google"]),
            {"state": state.state, "code": "oauth-code"},
            HTTP_ACCEPT="text/html",
        )

        self.assertEqual(response.status_code, 401, response.content)
        self.assertEqual(ExternalAdvertisingAccount.objects.count(), before_count)
        state.refresh_from_db()
        self.assertIsNone(state.used_at)

    @override_settings(
        ADS_ADVERTISER_DASHBOARD_ENABLED=True,
        ADS_GOOGLE_CONNECTION_ENABLED=True,
        ADS_GOOGLE_CLIENT_ID="google-client",
        ADS_GOOGLE_CLIENT_SECRET="google-secret",
        ADS_GOOGLE_DEVELOPER_TOKEN="developer-token",
        ADS_GOOGLE_LOGIN_CUSTOMER_ID="",
        ADS_CREDENTIAL_ENCRYPTION_KEY="test-credential-key",
    )
    @patch("ads.providers.requests.get")
    @patch("ads.providers.requests.post")
    def test_staff_mobile_callback_consumed_state_cannot_repeat_exchange_or_connection(self, mock_post, mock_get):
        class Response:
            status_code = 200

            def __init__(self, payload):
                self.payload = payload

            def json(self):
                return self.payload

        def google_post(url, **_kwargs):
            if url == "https://oauth2.googleapis.com/token":
                return Response({
                    "access_token": "access-secret-token",
                    "refresh_token": "refresh-secret-token",
                    "expires_in": 3600,
                    "scope": "https://www.googleapis.com/auth/adwords",
                })
            return Response({"results": [{"customerClient": {
                "clientCustomer": "customers/6711004233",
                "descriptiveName": "Arolana Ads Test Client",
                "manager": False,
                "status": "ENABLED",
                "level": 0,
            }}]})

        mock_post.side_effect = google_post
        mock_get.return_value = Response({"resourceNames": ["customers/6711004233"]})
        session = StaffMobileToken.issue(role=StaffMobileToken.ROLE_VENDOR, user=self.vendor_user)
        connect = self.client.post(
            reverse("ads_api:management_connected_account_connect", args=["google"]),
            data=json.dumps({"mobile_oauth": True}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {session.token}",
        )
        self.assertEqual(connect.status_code, 200, connect.content)
        state = AdvertisingOAuthState.objects.get()

        first_callback = self.client.get(
            reverse("ads_api:management_connected_account_callback", args=["google"]),
            {"state": state.state, "code": "oauth-code"},
            HTTP_ACCEPT="text/html",
        )
        self.assertEqual(first_callback.status_code, 302, first_callback.content)
        created_count = ExternalAdvertisingAccount.objects.count()
        provider_calls_after_first_callback = mock_post.call_count

        replay = self.client.get(
            reverse("ads_api:management_connected_account_callback", args=["google"]),
            {"state": state.state, "code": "oauth-code"},
            HTTP_ACCEPT="text/html",
        )

        self.assertEqual(replay.status_code, 302, replay.content)
        self.assertIn("oauth_error=connection_failed", replay["Location"])
        self.assertEqual(ExternalAdvertisingAccount.objects.count(), created_count)
        self.assertEqual(mock_post.call_count, provider_calls_after_first_callback)
        state.refresh_from_db()
        self.assertIsNotNone(state.used_at)

    @override_settings(
        ADS_ADVERTISER_DASHBOARD_ENABLED=True,
        ADS_GOOGLE_CONNECTION_ENABLED=True,
        ADS_GOOGLE_CLIENT_ID="google-client",
        ADS_GOOGLE_CLIENT_SECRET="google-secret",
        ADS_GOOGLE_DEVELOPER_TOKEN="developer-token",
        ADS_GOOGLE_LOGIN_CUSTOMER_ID="",
        ADS_CREDENTIAL_ENCRYPTION_KEY="test-credential-key",
    )
    def test_connected_account_connect_rejects_wrong_advertiser(self):
        identity = self.resolver.get_or_create_identity(self.resolver.resolve_product_owner(self.product))
        self.client.force_login(self.other_vendor_user)

        response = self.client.post(
            f"{reverse('ads_api:management_connected_account_connect', args=['google'])}?advertiser_id={identity.pk}"
        )

        self.assertEqual(response.status_code, 403)

    @override_settings(
        ADS_ADVERTISER_DASHBOARD_ENABLED=True,
        ADS_GOOGLE_CONNECTION_ENABLED=True,
        ADS_GOOGLE_CLIENT_ID="google-client",
        ADS_GOOGLE_CLIENT_SECRET="google-secret",
        ADS_GOOGLE_DEVELOPER_TOKEN="developer-token",
        ADS_GOOGLE_LOGIN_CUSTOMER_ID="",
        ADS_CREDENTIAL_ENCRYPTION_KEY="test-credential-key",
    )
    @patch("ads.providers.requests.get")
    @patch("ads.providers.requests.post")
    def test_oauth_callback_discovers_multiple_accounts_and_selects_one_without_exposing_credentials(self, mock_post, mock_get):
        class Response:
            status_code = 200

            def __init__(self, payload):
                self.payload = payload

            def json(self):
                return self.payload

        def google_post(url, **_kwargs):
            if url == "https://oauth2.googleapis.com/token":
                return Response({
                "access_token": "access-secret-token",
                "refresh_token": "refresh-secret-token",
                "expires_in": 3600,
                "scope": "https://www.googleapis.com/auth/adwords",
                })
            customer_id = url.split("/customers/")[-1].split("/")[0]
            return Response({"results": [{"customerClient": {
                "clientCustomer": f"customers/{customer_id}",
                "descriptiveName": f"Account {customer_id}",
                "manager": False,
                "status": "ENABLED",
                "level": 0,
            }}]})

        mock_post.side_effect = google_post
        mock_get.return_value = Response({"resourceNames": ["customers/111", "customers/222"]})
        self.client.force_login(self.vendor_user)

        connect_response = self.client.post(reverse("ads_api:management_connected_account_connect", args=["google"]))
        self.assertEqual(connect_response.status_code, 200, connect_response.content)
        state = AdvertisingOAuthState.objects.get()

        callback_response = self.client.get(
            reverse("ads_api:management_connected_account_callback", args=["google"]),
            {"state": state.state, "code": "oauth-code"},
        )
        self.assertEqual(callback_response.status_code, 200, callback_response.content)
        body = callback_response.json()
        self.assertEqual(len(body["accounts"]), 2)
        self.assertNotIn("access-secret-token", callback_response.content.decode("utf-8"))
        pending = ExternalAdvertisingAccount.objects.get(pk=body["connection_id"])
        credential = pending.credential
        self.assertNotEqual(bytes(credential.encrypted_access_token), b"access-secret-token")
        self.assertEqual(credential_encryption_service.decrypt(credential.encrypted_access_token), "access-secret-token")

        select_response = self.client.post(
            reverse("ads_api:management_connected_account_select", args=["google"]),
            data=json.dumps({"connection_id": pending.pk, "external_account_id": "222"}),
            content_type="application/json",
        )
        self.assertEqual(select_response.status_code, 200, select_response.content)
        pending.refresh_from_db()
        self.assertEqual(pending.status, ExternalAdvertisingAccount.STATUS_CONNECTED)
        self.assertEqual(pending.external_account_id, "222")
        self.assertNotIn("refresh-secret-token", select_response.content.decode("utf-8"))

    def _google_manager_discovery_response(self, payload):
        class Response:
            status_code = 200

            def json(self):
                return payload

        return Response()

    def _google_manager_discovery_post(self, url, **_kwargs):
        if url == "https://oauth2.googleapis.com/token":
            return self._google_manager_discovery_response({
                "access_token": "access-secret-token",
                "refresh_token": "refresh-secret-token",
                "expires_in": 3600,
                "scope": "https://www.googleapis.com/auth/adwords",
            })
        return self._google_manager_discovery_response({"results": [
            {"customerClient": {
                "clientCustomer": "customers/3594711127",
                "descriptiveName": "Arolana Test Manager",
                "manager": True,
                "status": "ENABLED",
                "level": 0,
            }},
            {"customerClient": {
                "clientCustomer": "customers/4228070397",
                "descriptiveName": "Arolana Google Test Client",
                "currencyCode": "NGN",
                "timeZone": "Africa/Lagos",
                "manager": False,
                "status": "ENABLED",
                "level": 1,
            }},
        ]})

    @override_settings(
        ADS_ADVERTISER_DASHBOARD_ENABLED=True,
        ADS_GOOGLE_CONNECTION_ENABLED=True,
        ADS_GOOGLE_CLIENT_ID="google-client",
        ADS_GOOGLE_CLIENT_SECRET="google-secret",
        ADS_GOOGLE_DEVELOPER_TOKEN="developer-token",
        ADS_GOOGLE_LOGIN_CUSTOMER_ID="3594711127",
        ADS_GOOGLE_TEST_ACCOUNT_ALLOWLIST=["4228070397"],
        ADS_CREDENTIAL_ENCRYPTION_KEY="test-credential-key",
    )
    @patch("ads.providers.requests.get")
    @patch("ads.providers.requests.post")
    def test_accessible_google_manager_discovers_verified_client_hierarchy(self, mock_post, mock_get):
        mock_get.return_value = self._google_manager_discovery_response({"resourceNames": ["customers/3594711127"]})
        mock_post.side_effect = self._google_manager_discovery_post
        self.client.force_login(self.vendor_user)
        self.client.post(reverse("ads_api:management_connected_account_connect", args=["google"]))
        state = AdvertisingOAuthState.objects.get()

        response = self.client.get(
            reverse("ads_api:management_connected_account_callback", args=["google"]),
            {"state": state.state, "code": "oauth-code"},
        )

        self.assertEqual(response.status_code, 200, response.content)
        state.refresh_from_db()
        self.assertIsNotNone(state.used_at)
        accounts = response.json()["accounts"]
        self.assertEqual([item["external_account_id"] for item in accounts], ["4228070397"])
        self.assertEqual(accounts[0]["permission_summary"], "manager_hierarchy_verified")

    @override_settings(
        ADS_ADVERTISER_DASHBOARD_ENABLED=True,
        ADS_GOOGLE_CONNECTION_ENABLED=True,
        ADS_GOOGLE_CLIENT_ID="google-client",
        ADS_GOOGLE_CLIENT_SECRET="google-secret",
        ADS_GOOGLE_DEVELOPER_TOKEN="developer-token",
        ADS_GOOGLE_LOGIN_CUSTOMER_ID="3594711127",
        ADS_GOOGLE_TEST_ACCOUNT_ALLOWLIST=["4228070397"],
        ADS_CREDENTIAL_ENCRYPTION_KEY="test-credential-key",
    )
    @patch("ads.providers.requests.get")
    @patch("ads.providers.requests.post")
    def test_verified_google_client_appears_on_browser_confirmation_page(self, mock_post, mock_get):
        mock_get.return_value = self._google_manager_discovery_response({"resourceNames": ["customers/3594711127"]})
        mock_post.side_effect = self._google_manager_discovery_post
        self.client.force_login(self.vendor_user)
        self.client.post(reverse("ads_api:management_connected_account_connect", args=["google"]))
        state = AdvertisingOAuthState.objects.get()

        callback = self.client.get(
            reverse("ads_api:management_connected_account_callback", args=["google"]),
            {"state": state.state, "code": "oauth-code"},
            HTTP_ACCEPT="text/html",
        )
        response = self.client.get(callback.url)

        self.assertContains(response, "Arolana Google Test Client")
        self.assertContains(response, "4228070397")

    @override_settings(
        ADS_ADVERTISER_DASHBOARD_ENABLED=True,
        ADS_GOOGLE_CONNECTION_ENABLED=True,
        ADS_GOOGLE_CLIENT_ID="google-client",
        ADS_GOOGLE_CLIENT_SECRET="google-secret",
        ADS_GOOGLE_DEVELOPER_TOKEN="developer-token",
        ADS_GOOGLE_LOGIN_CUSTOMER_ID="3594711127",
        ADS_CREDENTIAL_ENCRYPTION_KEY="test-credential-key",
    )
    @patch("ads.providers.requests.get")
    @patch("ads.providers.requests.post")
    def test_google_manager_is_not_selectable_when_verified_client_is_intended(self, mock_post, mock_get):
        mock_get.return_value = self._google_manager_discovery_response({"resourceNames": ["customers/3594711127"]})
        mock_post.side_effect = self._google_manager_discovery_post
        self.client.force_login(self.vendor_user)
        self.client.post(reverse("ads_api:management_connected_account_connect", args=["google"]))
        state = AdvertisingOAuthState.objects.get()
        response = self.client.get(
            reverse("ads_api:management_connected_account_callback", args=["google"]),
            {"state": state.state, "code": "oauth-code"},
        )

        account_ids = [item["external_account_id"] for item in response.json()["accounts"]]
        self.assertNotIn("3594711127", account_ids)
        self.assertIn("4228070397", account_ids)

    @override_settings(
        ADS_ADVERTISER_DASHBOARD_ENABLED=True,
        ADS_GOOGLE_TEST_ACCOUNT_ALLOWLIST=["4228070397"],
    )
    def test_allowlist_only_google_customer_cannot_be_selected(self):
        identity = self.resolver.get_or_create_identity(self.resolver.resolve_product_owner(self.product))
        pending = ExternalAdvertisingAccount.objects.create(
            advertiser_identity=identity,
            channel=ExternalAdvertisingAccount.CHANNEL_GOOGLE,
            external_account_id="pending:verified-only",
            display_name="Pending",
            status=ExternalAdvertisingAccount.STATUS_PENDING,
            metadata={"discovered_accounts": [{"external_account_id": "1111111111", "display_name": "Google verified"}]},
        )
        self.client.force_login(self.vendor_user)

        response = self.client.post(
            reverse("ads_api:management_connected_account_select", args=["google"]),
            data=json.dumps({"connection_id": pending.pk, "external_account_id": "4228070397"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "external_account_not_discovered")

    @override_settings(ADS_ADVERTISER_DASHBOARD_ENABLED=True)
    def test_google_pending_account_selection_preserves_cross_owner_isolation(self):
        identity = self.resolver.get_or_create_identity(self.resolver.resolve_product_owner(self.product))
        pending = ExternalAdvertisingAccount.objects.create(
            advertiser_identity=identity,
            channel=ExternalAdvertisingAccount.CHANNEL_GOOGLE,
            external_account_id="pending:owner-isolation",
            display_name="Pending",
            status=ExternalAdvertisingAccount.STATUS_PENDING,
            metadata={"discovered_accounts": [{"external_account_id": "4228070397", "display_name": "Verified client"}]},
        )
        self.client.force_login(self.other_vendor_user)

        response = self.client.post(
            reverse("ads_api:management_connected_account_select", args=["google"]),
            data=json.dumps({"connection_id": pending.pk, "external_account_id": "4228070397"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"], "pending_connection_not_found")

    @override_settings(
        ADS_ADVERTISER_DASHBOARD_ENABLED=True,
        ADS_GOOGLE_CONNECTION_ENABLED=True,
        ADS_GOOGLE_CLIENT_ID="google-client",
        ADS_GOOGLE_CLIENT_SECRET="google-secret",
        ADS_GOOGLE_DEVELOPER_TOKEN="developer-token",
    )
    def test_oauth_state_rejects_provider_mismatch_expiry_and_reuse(self):
        self.client.force_login(self.vendor_user)
        self.client.post(reverse("ads_api:management_connected_account_connect", args=["google"]))
        state = AdvertisingOAuthState.objects.get()

        mismatch = self.client.get(
            reverse("ads_api:management_connected_account_callback", args=["meta"]),
            {"state": state.state, "code": "oauth-code"},
        )
        self.assertEqual(mismatch.status_code, 400)

        state.expires_at = timezone.now() - timedelta(minutes=1)
        state.save(update_fields=["expires_at", "updated_at"])
        expired = self.client.get(
            reverse("ads_api:management_connected_account_callback", args=["google"]),
            {"state": state.state, "code": "oauth-code"},
        )
        self.assertEqual(expired.status_code, 400)

        state.expires_at = timezone.now() + timedelta(minutes=5)
        state.used_at = timezone.now()
        state.save(update_fields=["expires_at", "used_at", "updated_at"])
        reused = self.client.get(
            reverse("ads_api:management_connected_account_callback", args=["google"]),
            {"state": state.state, "code": "oauth-code"},
        )
        self.assertEqual(reused.status_code, 400)

    @override_settings(
        ADS_ADVERTISER_DASHBOARD_ENABLED=True,
        ADS_GOOGLE_CONNECTION_ENABLED=True,
        ADS_GOOGLE_CLIENT_ID="google-client",
        ADS_GOOGLE_CLIENT_SECRET="google-secret",
        ADS_GOOGLE_DEVELOPER_TOKEN="developer-token",
    )
    def test_oauth_state_rejects_session_mismatch(self):
        self.client.force_login(self.vendor_user)
        self.client.post(reverse("ads_api:management_connected_account_connect", args=["google"]))
        state = AdvertisingOAuthState.objects.get()

        other_client = Client()
        other_client.force_login(self.vendor_user)
        response = other_client.get(
            reverse("ads_api:management_connected_account_callback", args=["google"]),
            {"state": state.state, "code": "oauth-code"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "session_mismatch")

        state.refresh_from_db()
        self.assertIsNone(state.used_at)

        other_user = get_user_model().objects.create_user(
            username="oauth-wrong-user",
            email="oauth-wrong-user@example.com",
            password="testpass123",
        )
        wrong_user_client = Client()
        wrong_user_client.force_login(other_user)
        wrong_user = wrong_user_client.get(
            reverse("ads_api:management_connected_account_callback", args=["google"]),
            {"state": state.state, "code": "oauth-code"},
        )
        self.assertEqual(wrong_user.status_code, 400)
        self.assertEqual(wrong_user.json()["error"], "user_mismatch")
        state.refresh_from_db()
        self.assertIsNone(state.used_at)

    def test_credential_secrets_are_absent_from_admin_form(self):
        model_admin = admin.site._registry[AdvertisingCredential]

        self.assertIn("encrypted_access_token", model_admin.exclude)
        self.assertIn("encrypted_refresh_token", model_admin.exclude)

    @override_settings(ADS_ADVERTISER_DASHBOARD_ENABLED=True)
    def test_duplicate_external_account_cannot_be_selected_for_another_advertiser(self):
        identity = self.resolver.get_or_create_identity(self.resolver.resolve_product_owner(self.product))
        other_identity = AdvertiserIdentity.objects.create(
            owner_type=AdvertiserIdentity.OWNER_VENDOR,
            vendor=self.other_vendor,
            user=self.other_vendor_user,
            display_name="Other Vendor",
        )
        ExternalAdvertisingAccount.objects.create(
            advertiser_identity=other_identity,
            channel=ExternalAdvertisingAccount.CHANNEL_GOOGLE,
            external_account_id="customers-777",
            display_name="Existing Google Account",
            status=ExternalAdvertisingAccount.STATUS_CONNECTED,
        )
        pending = ExternalAdvertisingAccount.objects.create(
            advertiser_identity=identity,
            channel=ExternalAdvertisingAccount.CHANNEL_GOOGLE,
            external_account_id="pending:test",
            display_name="Pending",
            status=ExternalAdvertisingAccount.STATUS_PENDING,
            metadata={"discovered_accounts": [{"external_account_id": "customers-777", "display_name": "Duplicate"}]},
        )
        self.client.force_login(self.vendor_user)

        response = self.client.post(
            reverse("ads_api:management_connected_account_select", args=["google"]),
            data=json.dumps({"connection_id": pending.pk, "external_account_id": "customers-777"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "duplicate_external_account")

    @override_settings(ADS_ADVERTISER_DASHBOARD_ENABLED=True, ADS_CREDENTIAL_ENCRYPTION_KEY="test-credential-key")
    def test_google_reconnect_merges_pending_credential_into_existing_same_advertiser_account(self):
        identity = self.resolver.get_or_create_identity(self.resolver.resolve_product_owner(self.product))
        existing = ExternalAdvertisingAccount.objects.create(
            advertiser_identity=identity,
            channel=ExternalAdvertisingAccount.CHANNEL_GOOGLE,
            external_account_id="6711004233",
            display_name="Old Google Account",
            status=ExternalAdvertisingAccount.STATUS_REAUTHORIZATION_REQUIRED,
        )
        existing_account_id = existing.pk
        save_credential_tokens(
            existing,
            ExternalAdvertisingAccount.CHANNEL_GOOGLE,
            {"access_token": "stale-access-token", "refresh_token": "existing-refresh-token", "expires_in": 3600},
        )
        pending = ExternalAdvertisingAccount.objects.create(
            advertiser_identity=identity,
            channel=ExternalAdvertisingAccount.CHANNEL_GOOGLE,
            external_account_id="pending:reconnect",
            display_name="Google pending account selection",
            status=ExternalAdvertisingAccount.STATUS_PENDING,
            metadata={
                "discovered_accounts": [
                    {
                        "external_account_id": "6711004233",
                        "display_name": "Arolana Ads Test Client",
                        "currency": "USD",
                        "timezone": "Africa/Lagos",
                    }
                ]
            },
        )
        save_credential_tokens(
            pending,
            ExternalAdvertisingAccount.CHANNEL_GOOGLE,
            {"access_token": "fresh-access-token", "refresh_token": "fresh-refresh-token", "expires_in": 3600},
        )
        self.client.force_login(self.vendor_user)

        response = self.client.post(
            reverse("ads_api:management_connected_account_select", args=["google"]),
            data=json.dumps({"connection_id": pending.pk, "external_account_id": "6711004233"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["account"]["id"], existing_account_id)
        existing.refresh_from_db()
        self.assertEqual(existing.pk, existing_account_id)
        self.assertEqual(existing.status, ExternalAdvertisingAccount.STATUS_CONNECTED)
        self.assertEqual(existing.display_name, "Arolana Ads Test Client")
        self.assertEqual(existing.metadata["currency"], "USD")
        credential = existing.credential
        self.assertEqual(credential_encryption_service.decrypt(credential.encrypted_access_token), "fresh-access-token")
        self.assertEqual(credential_encryption_service.decrypt(credential.encrypted_refresh_token), "fresh-refresh-token")
        self.assertFalse(ExternalAdvertisingAccount.objects.filter(pk=pending.pk).exists())
        self.assertNotIn("fresh-access-token", response.content.decode("utf-8"))
        self.assertNotIn("fresh-refresh-token", response.content.decode("utf-8"))

    @override_settings(ADS_ADVERTISER_DASHBOARD_ENABLED=True, ADS_CREDENTIAL_ENCRYPTION_KEY="test-credential-key")
    def test_google_reconnect_preserves_existing_refresh_token_when_pending_connection_has_none(self):
        identity = self.resolver.get_or_create_identity(self.resolver.resolve_product_owner(self.product))
        existing = ExternalAdvertisingAccount.objects.create(
            advertiser_identity=identity,
            channel=ExternalAdvertisingAccount.CHANNEL_GOOGLE,
            external_account_id="6711004233",
            status=ExternalAdvertisingAccount.STATUS_CONNECTED,
        )
        save_credential_tokens(
            existing,
            ExternalAdvertisingAccount.CHANNEL_GOOGLE,
            {"access_token": "old-access-token", "refresh_token": "existing-refresh-token", "expires_in": 3600},
        )
        pending = ExternalAdvertisingAccount.objects.create(
            advertiser_identity=identity,
            channel=ExternalAdvertisingAccount.CHANNEL_GOOGLE,
            external_account_id="pending:refresh-preservation",
            status=ExternalAdvertisingAccount.STATUS_PENDING,
            metadata={"discovered_accounts": [{"external_account_id": "6711004233", "display_name": "Google Test"}]},
        )
        save_credential_tokens(
            pending,
            ExternalAdvertisingAccount.CHANNEL_GOOGLE,
            {"access_token": "fresh-access-token", "expires_in": 3600},
        )
        self.client.force_login(self.vendor_user)

        response = self.client.post(
            reverse("ads_api:management_connected_account_select", args=["google"]),
            data=json.dumps({"connection_id": pending.pk, "external_account_id": "6711004233"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        existing.refresh_from_db()
        self.assertEqual(credential_encryption_service.decrypt(existing.credential.encrypted_access_token), "fresh-access-token")
        self.assertEqual(
            credential_encryption_service.decrypt(existing.credential.encrypted_refresh_token),
            "existing-refresh-token",
        )
        self.assertFalse(ExternalAdvertisingAccount.objects.filter(pk=pending.pk).exists())

    @override_settings(ADS_ADVERTISER_DASHBOARD_ENABLED=True, ADS_CREDENTIAL_ENCRYPTION_KEY="test-credential-key")
    def test_google_reconnect_repeat_returns_safe_pending_not_found_instead_of_integrity_error(self):
        identity = self.resolver.get_or_create_identity(self.resolver.resolve_product_owner(self.product))
        existing = ExternalAdvertisingAccount.objects.create(
            advertiser_identity=identity,
            channel=ExternalAdvertisingAccount.CHANNEL_GOOGLE,
            external_account_id="6711004233",
            status=ExternalAdvertisingAccount.STATUS_CONNECTED,
        )
        pending = ExternalAdvertisingAccount.objects.create(
            advertiser_identity=identity,
            channel=ExternalAdvertisingAccount.CHANNEL_GOOGLE,
            external_account_id="pending:repeat",
            status=ExternalAdvertisingAccount.STATUS_PENDING,
            metadata={"discovered_accounts": [{"external_account_id": "6711004233", "display_name": "Google Test"}]},
        )
        save_credential_tokens(
            pending,
            ExternalAdvertisingAccount.CHANNEL_GOOGLE,
            {"access_token": "fresh-access-token", "refresh_token": "fresh-refresh-token", "expires_in": 3600},
        )
        self.client.force_login(self.vendor_user)
        payload = json.dumps({"connection_id": pending.pk, "external_account_id": "6711004233"})

        first = self.client.post(
            reverse("ads_api:management_connected_account_select", args=["google"]),
            data=payload,
            content_type="application/json",
        )
        second = self.client.post(
            reverse("ads_api:management_connected_account_select", args=["google"]),
            data=payload,
            content_type="application/json",
        )

        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(first.json()["account"]["id"], existing.pk)
        self.assertEqual(second.status_code, 404, second.content)
        self.assertEqual(second.json()["error"], "pending_connection_not_found")

    @override_settings(ADS_ADVERTISER_DASHBOARD_ENABLED=True, ADS_CREDENTIAL_ENCRYPTION_KEY="test-credential-key")
    def test_disconnect_revokes_credential_usability_and_retains_audit(self):
        identity = self.resolver.get_or_create_identity(self.resolver.resolve_product_owner(self.product))
        account = ExternalAdvertisingAccount.objects.create(
            advertiser_identity=identity,
            channel=ExternalAdvertisingAccount.CHANNEL_GOOGLE,
            external_account_id="123",
            display_name="Google Ads",
            status=ExternalAdvertisingAccount.STATUS_CONNECTED,
        )
        AdvertisingCredential.objects.create(
            external_account=account,
            provider="google",
            encrypted_access_token=credential_encryption_service.encrypt("access"),
            encrypted_refresh_token=credential_encryption_service.encrypt("refresh"),
        )
        self.client.force_login(self.vendor_user)

        response = self.client.post(
            reverse("ads_api:management_connected_account_disconnect", args=["google"]),
            data=json.dumps({"account_id": account.pk}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        account.refresh_from_db()
        credential = account.credential
        credential.refresh_from_db()
        self.assertEqual(account.status, ExternalAdvertisingAccount.STATUS_REVOKED)
        self.assertIsNone(credential.encrypted_access_token)
        self.assertIsNone(credential.encrypted_refresh_token)
        self.assertTrue(AdvertisingConnectionAuditLog.objects.filter(event_type=AdvertisingConnectionAuditLog.EVENT_CONNECTION_REVOKED).exists())

    @override_settings(
        ADS_GOOGLE_CONNECTION_ENABLED=True,
        ADS_GOOGLE_CLIENT_ID="google-client",
        ADS_GOOGLE_CLIENT_SECRET="google-secret",
        ADS_GOOGLE_DEVELOPER_TOKEN="developer-token",
        ADS_CREDENTIAL_ENCRYPTION_KEY="test-credential-key",
    )
    @patch("ads.providers.requests.post")
    def test_token_refresh_success_and_failure_are_server_side_and_fail_closed(self, mock_post):
        class Response:
            def __init__(self, status_code, payload):
                self.status_code = status_code
                self.payload = payload

            def json(self):
                return self.payload

        identity = self.resolver.get_or_create_identity(self.resolver.resolve_product_owner(self.product))
        account = ExternalAdvertisingAccount.objects.create(
            advertiser_identity=identity,
            channel=ExternalAdvertisingAccount.CHANNEL_GOOGLE,
            external_account_id="123",
            display_name="Google Ads",
            status=ExternalAdvertisingAccount.STATUS_CONNECTED,
        )
        credential = AdvertisingCredential.objects.create(
            external_account=account,
            provider="google",
            encrypted_access_token=credential_encryption_service.encrypt("old-access"),
            encrypted_refresh_token=credential_encryption_service.encrypt("old-refresh"),
        )
        mock_post.return_value = Response(200, {"access_token": "new-access", "expires_in": 60})

        refreshed = provider_for("google").refresh_credentials(credential)

        self.assertEqual(credential_encryption_service.decrypt(refreshed.encrypted_access_token), "new-access")
        mock_post.return_value = Response(401, {})
        with self.assertRaises(ProviderAuthorizationError):
            provider_for("google").refresh_credentials(refreshed)
        account.refresh_from_db()
        self.assertEqual(account.status, ExternalAdvertisingAccount.STATUS_REAUTHORIZATION_REQUIRED)

    @override_settings(
        ADS_GOOGLE_CONNECTION_ENABLED=True,
        ADS_GOOGLE_CLIENT_ID="google-client",
        ADS_GOOGLE_CLIENT_SECRET="google-secret",
        ADS_GOOGLE_DEVELOPER_TOKEN="developer-token",
        ADS_CREDENTIAL_ENCRYPTION_KEY="test-credential-key",
    )
    @patch("ads.providers.requests.post")
    def test_expired_google_access_token_is_refreshable_and_auto_refreshed(self, mock_post):
        class Response:
            status_code = 200

            @staticmethod
            def json():
                return {"access_token": "refreshed-access", "expires_in": 3600}

        _, _, account = self._execution_campaign()
        credential = account.credential
        credential.access_token_expires_at = timezone.now() - timedelta(minutes=1)
        credential.refresh_token_expires_at = timezone.now() + timedelta(days=30)
        credential.save(
            update_fields=[
                "access_token_expires_at",
                "refresh_token_expires_at",
                "updated_at",
            ]
        )
        expected_refresh_expiry = credential.refresh_token_expires_at
        mock_post.return_value = Response()

        provider = provider_for("google")
        self.assertEqual(
            provider.get_connection_status(account),
            ExternalAdvertisingAccount.STATUS_CONNECTED,
        )

        refreshed = provider._credential(SimpleNamespace(external_account=account))

        self.assertEqual(
            credential_encryption_service.decrypt(refreshed.encrypted_access_token),
            "refreshed-access",
        )
        self.assertEqual(
            credential_encryption_service.decrypt(refreshed.encrypted_refresh_token),
            "refresh",
        )
        self.assertEqual(refreshed.refresh_token_expires_at, expected_refresh_expiry)
        mock_post.assert_called_once()

    @override_settings(ADS_CREDENTIAL_ENCRYPTION_KEY="test-credential-key")
    def test_expired_google_access_token_without_refresh_token_remains_expired(self):
        _, _, account = self._execution_campaign()
        credential = account.credential
        credential.encrypted_refresh_token = None
        credential.access_token_expires_at = timezone.now() - timedelta(minutes=1)
        credential.save(update_fields=["encrypted_refresh_token", "access_token_expires_at", "updated_at"])

        provider = provider_for("google")
        self.assertEqual(
            provider.get_connection_status(account),
            ExternalAdvertisingAccount.STATUS_EXPIRED,
        )
        with self.assertRaisesMessage(ProviderAuthorizationError, "credential_expired"):
            provider._credential(SimpleNamespace(external_account=account))

    @override_settings(ADS_CREDENTIAL_ENCRYPTION_KEY="test-credential-key")
    @patch("ads.providers.requests.post")
    def test_expired_google_refresh_token_requires_reauthorization_without_refresh_attempt(self, mock_post):
        _, _, account = self._execution_campaign()
        credential = account.credential
        credential.refresh_token_expires_at = timezone.now() - timedelta(minutes=1)
        credential.save(update_fields=["refresh_token_expires_at", "updated_at"])

        provider = provider_for("google")
        self.assertEqual(
            provider.get_connection_status(account),
            ExternalAdvertisingAccount.STATUS_REAUTHORIZATION_REQUIRED,
        )
        with self.assertRaisesMessage(ProviderAuthorizationError, "refresh_token_expired"):
            provider._credential(SimpleNamespace(external_account=account))
        mock_post.assert_not_called()
        account.refresh_from_db()
        self.assertEqual(account.status, ExternalAdvertisingAccount.STATUS_REAUTHORIZATION_REQUIRED)

    @override_settings(ADS_CREDENTIAL_ENCRYPTION_KEY="test-credential-key")
    def test_revoked_google_credential_is_not_refreshable(self):
        _, _, account = self._execution_campaign()
        credential = account.credential
        credential.revoked_at = timezone.now()
        credential.save(update_fields=["revoked_at", "updated_at"])

        provider = provider_for("google")
        self.assertEqual(
            provider.get_connection_status(account),
            ExternalAdvertisingAccount.STATUS_REVOKED,
        )
        with self.assertRaisesMessage(ProviderAuthorizationError, "credential_revoked"):
            provider._credential(SimpleNamespace(external_account=account))

    @override_settings(
        ADS_GOOGLE_CONNECTION_ENABLED=True,
        ADS_GOOGLE_CLIENT_ID="google-client",
        ADS_GOOGLE_CLIENT_SECRET="google-secret",
        ADS_GOOGLE_DEVELOPER_TOKEN="developer-token",
        ADS_CREDENTIAL_ENCRYPTION_KEY="test-credential-key",
    )
    @patch("ads.providers.requests.post")
    def test_refresh_failure_is_safe_and_requires_reauthorization(self, mock_post):
        class Response:
            status_code = 400

            @staticmethod
            def json():
                return {"error": "invalid_grant", "access_token": "must-not-leak"}

        _, _, account = self._execution_campaign()
        credential = account.credential
        credential.access_token_expires_at = timezone.now() - timedelta(minutes=1)
        credential.save(update_fields=["access_token_expires_at", "updated_at"])
        mock_post.return_value = Response()

        with self.assertRaises(ProviderAuthorizationError) as raised:
            provider_for("google")._credential(SimpleNamespace(external_account=account))

        self.assertEqual(str(raised.exception), "refresh_failed")
        self.assertNotIn("invalid_grant", str(raised.exception))
        self.assertNotIn("must-not-leak", str(raised.exception))
        account.refresh_from_db()
        self.assertEqual(account.status, ExternalAdvertisingAccount.STATUS_REAUTHORIZATION_REQUIRED)

    def test_connection_audit_redacts_secret_metadata(self):
        event = audit_connection(
            "google",
            AdvertisingConnectionAuditLog.EVENT_AUTHORIZATION_FAILED,
            metadata={"access_token": "secret", "authorization_code": "code", "safe": "kept"},
        )

        self.assertEqual(event.metadata, {"safe": "kept"})

    def _execution_campaign(self, objective=AdCampaign.OBJECTIVE_PRODUCT_VISITS, approved=True):
        identity = self.resolver.get_or_create_identity(self.resolver.resolve_product_owner(self.product))
        campaign = AdCampaign.objects.create(
            name=f"Execution {uuid4()}",
            advertiser_identity=identity,
            objective=objective,
            total_budget=Decimal("100000.00"),
            approved=approved,
            status="active" if approved else "draft",
            start_date=timezone.now() + timedelta(days=1),
            end_date=timezone.now() + timedelta(days=10),
        )
        CampaignAsset.objects.create(
            campaign=campaign,
            advertiser_identity=identity,
            asset_type=CampaignAsset.ASSET_PRODUCT,
            content_type=ContentType.objects.get_for_model(self.product),
            object_id=self.product.pk,
            title=self.product.name,
        )
        AdCreative.objects.create(
            campaign=campaign,
            name="Execution Creative",
            creative_type="image",
            headline="Install better projectors",
            description="A safe creative for external preview",
            cta_text="Shop Now",
            clickthrough_url="https://arolana.com/products/projector-1/",
        )
        account = ExternalAdvertisingAccount.objects.create(
            advertiser_identity=identity,
            channel=ExternalAdvertisingAccount.CHANNEL_GOOGLE,
            external_account_id=f"customers-{uuid4().hex[:8]}",
            display_name="Google Ads Account",
            status=ExternalAdvertisingAccount.STATUS_CONNECTED,
            metadata={"currency": "NGN"},
        )
        AdvertisingCredential.objects.create(
            external_account=account,
            provider="google",
            encrypted_access_token=credential_encryption_service.encrypt("access"),
            encrypted_refresh_token=credential_encryption_service.encrypt("refresh"),
            access_token_expires_at=timezone.now() + timedelta(hours=1),
        )
        return identity, campaign, account

    @override_settings(ADS_CREDENTIAL_ENCRYPTION_KEY="test-credential-key")
    def test_external_objective_mapping_is_explicit_and_unsupported_returns_review_error(self):
        identity, campaign, account = self._execution_campaign(objective=AdCampaign.OBJECTIVE_MESSAGES)

        self.assertEqual(OBJECTIVE_MAPPING["google"][AdCampaign.OBJECTIVE_MESSAGES], None)
        result = external_campaign_execution_service.preview(campaign, "google", account)

        self.assertFalse(result.valid)
        self.assertIn("unsupported_objective", result.errors)

    @override_settings(ADS_CREDENTIAL_ENCRYPTION_KEY="test-credential-key")
    def test_external_dry_run_payload_validates_creative_budget_and_does_not_publish(self):
        identity, campaign, account = self._execution_campaign()

        execution, result = external_campaign_execution_service.create_execution(
            campaign,
            "google",
            account,
            dry_run=True,
            user=self.vendor_user,
        )

        self.assertTrue(result.valid)
        self.assertEqual(execution.status, AdChannelExecution.STATUS_DRAFT)
        self.assertEqual(execution.external_campaign_id, "")
        self.assertEqual(result.payload["campaign"]["campaign_type"], "DEMAND_GEN")
        self.assertEqual(result.payload["budget"]["amount"], "100000.00")

    @override_settings(ADS_CREDENTIAL_ENCRYPTION_KEY="test-credential-key")
    def test_external_validation_fails_for_disconnected_expired_wrong_advertiser_and_bad_budget(self):
        identity, campaign, account = self._execution_campaign()
        account.status = ExternalAdvertisingAccount.STATUS_DISCONNECTED
        account.save(update_fields=["status", "updated_at"])
        disconnected = external_campaign_execution_service.validate_campaign(campaign, "google", account, require_publish_ready=True)
        self.assertIn("account_disconnected", disconnected.errors)

        account.status = ExternalAdvertisingAccount.STATUS_CONNECTED
        account.save(update_fields=["status", "updated_at"])
        credential = account.credential
        credential.access_token_expires_at = timezone.now() - timedelta(minutes=1)
        credential.save(update_fields=["access_token_expires_at", "updated_at"])
        refreshable = external_campaign_execution_service.validate_campaign(campaign, "google", account, require_publish_ready=True)
        self.assertNotIn("credential_expired", refreshable.errors)

        credential.encrypted_refresh_token = None
        credential.save(update_fields=["encrypted_refresh_token", "updated_at"])
        expired = external_campaign_execution_service.validate_campaign(campaign, "google", account, require_publish_ready=True)
        self.assertIn("credential_expired", expired.errors)

        other_identity = AdvertiserIdentity.objects.create(
            owner_type=AdvertiserIdentity.OWNER_VENDOR,
            vendor=self.other_vendor,
            user=self.other_vendor_user,
            display_name="Other Vendor",
        )
        account.advertiser_identity = other_identity
        mismatch = external_campaign_execution_service.validate_campaign(campaign, "google", account, require_publish_ready=True)
        self.assertIn("external_account_advertiser_mismatch", mismatch.errors)

        campaign.channel_budget_allocations = {"google": "0"}
        campaign.save(update_fields=["channel_budget_allocations", "updated_at"])
        account.advertiser_identity = identity
        bad_budget = external_campaign_execution_service.validate_campaign(campaign, "google", account, require_publish_ready=True)
        self.assertIn("invalid_budget", bad_budget.errors)

    @override_settings(
        ADS_CREDENTIAL_ENCRYPTION_KEY="test-credential-key",
        ADS_EXTERNAL_CAMPAIGN_PUBLISHING_ENABLED=False,
        ADS_EXTERNAL_CHANNEL_SYNC_ENABLED=True,
    )
    def test_external_create_is_idempotent_and_flag_off_prevents_mutation(self):
        identity, campaign, account = self._execution_campaign()

        first, first_result = external_campaign_execution_service.create_execution(campaign, "google", account)
        second, second_result = external_campaign_execution_service.create_execution(campaign, "google", account)

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(AdChannelExecution.objects.filter(campaign=campaign, channel="google").count(), 1)
        self.assertFalse(first_result.valid)
        self.assertFalse(second_result.valid)
        self.assertEqual(first_result.errors, ["external_campaign_publishing_disabled"])

    @override_settings(
        ADS_CREDENTIAL_ENCRYPTION_KEY="test-credential-key",
        ADS_EXTERNAL_CAMPAIGN_PUBLISHING_ENABLED=True,
        ADS_EXTERNAL_CHANNEL_SYNC_ENABLED=True,
        ADS_GOOGLE_CONNECTION_ENABLED=False,
    )
    @patch("ads.providers.GoogleAdsProvider.create_campaign")
    def test_external_create_blocks_when_connection_flag_off(self, mock_create):
        identity, campaign, account = self._execution_campaign()

        execution, result = external_campaign_execution_service.create_execution(campaign, "google", account)

        self.assertFalse(result.valid)
        self.assertIn("provider_not_configured", result.errors)
        self.assertFalse(mock_create.called)

    @override_settings(
        ADS_CREDENTIAL_ENCRYPTION_KEY="test-credential-key",
        ADS_EXTERNAL_CAMPAIGN_PUBLISHING_ENABLED=True,
        ADS_EXTERNAL_CHANNEL_SYNC_ENABLED=True,
        ADS_EXTERNAL_CAMPAIGN_TEST_MODE_ENABLED=True,
        ADS_GOOGLE_CONNECTION_ENABLED=True,
        ADS_GOOGLE_CLIENT_ID="google-client",
        ADS_GOOGLE_CLIENT_SECRET="google-secret",
        ADS_GOOGLE_DEVELOPER_TOKEN="developer-token",
        ADS_GOOGLE_TEST_ACCOUNT_ALLOWLIST=["customers-allowlisted"],
    )
    @patch("ads.providers.GoogleAdsProvider.create_campaign", side_effect=ProviderAPIError("provider_api_error"))
    def test_external_provider_api_error_is_channel_isolated(self, mock_create):
        identity, campaign, account = self._execution_campaign()
        account.external_account_id = "customers-allowlisted"
        account.save(update_fields=["external_account_id", "updated_at"])
        internal = AdChannelExecution.objects.create(
            campaign=campaign,
            advertiser_identity=identity,
            channel=AdChannelExecution.CHANNEL_INTERNAL,
            status=AdChannelExecution.STATUS_ACTIVE,
        )

        self.vendor_user.is_staff = True
        self.vendor_user.save(update_fields=["is_staff"])

        external, result = external_campaign_execution_service.create_execution(campaign, "google", account, user=self.vendor_user)

        internal.refresh_from_db()
        self.assertEqual(internal.status, AdChannelExecution.STATUS_ACTIVE)
        self.assertEqual(external.status, AdChannelExecution.STATUS_FAILED)
        self.assertIn("provider_api_error", result.errors)
        audit_events = set(
            AdvertisingConnectionAuditLog.objects.filter(
                external_account=account,
                advertiser_identity=identity,
            ).values_list("event_type", flat=True)
        )
        self.assertIn(AdvertisingConnectionAuditLog.EVENT_TEST_PUBLICATION_REQUESTED, audit_events)
        self.assertIn(AdvertisingConnectionAuditLog.EVENT_TEST_PUBLICATION_APPROVED, audit_events)
        self.assertIn(AdvertisingConnectionAuditLog.EVENT_EXTERNAL_CREATE_ATTEMPTED, audit_events)
        self.assertIn(AdvertisingConnectionAuditLog.EVENT_EXTERNAL_CREATE_FAILED, audit_events)

    @override_settings(ADS_CREDENTIAL_ENCRYPTION_KEY="test-credential-key")
    @patch("ads.providers.GoogleAdsProvider.fetch_campaign_by_id", return_value={"status": "PAUSED"})
    @patch("ads.providers.GoogleAdsProvider._post_google")
    def test_google_create_campaign_assigns_budget_create_and_readback_stages(self, mock_post, mock_readback):
        identity, campaign, account = self._execution_campaign()
        campaign.start_date = timezone.make_aware(datetime(2026, 9, 1, 9, 30, 0))
        campaign.end_date = timezone.make_aware(datetime(2026, 9, 30, 18, 45, 0))
        campaign.save(update_fields=["start_date", "end_date", "updated_at"])
        account.metadata = {**account.metadata, "timezone": "Africa/Lagos"}
        account.save(update_fields=["metadata", "updated_at"])
        execution = AdChannelExecution.objects.create(
            campaign=campaign,
            advertiser_identity=identity,
            channel="google",
            external_account=account,
            idempotency_key="stage-test",
            budget_allocation=Decimal("25000.00"),
        )
        payload = external_campaign_execution_service.build_external_payload(campaign, "google", account)
        mock_post.side_effect = [
            {"results": [{"resourceName": "customers/1/campaignBudgets/2"}]},
            {"results": [{"resourceName": "customers/1/campaigns/3"}]},
        ]

        provider_for("google").create_campaign(execution, payload, idempotency_key="stage-test")

        self.assertEqual(mock_post.call_args_list[0].kwargs["stage"], "campaign_budget_create")
        self.assertEqual(mock_post.call_args_list[1].kwargs["stage"], "campaign_create")
        self.assertEqual(mock_readback.call_args.kwargs["stage"], "campaign_readback")
        create_payload = mock_post.call_args_list[1].args[2]["operations"][0]["create"]
        self.assertEqual(create_payload["startDateTime"], "2026-09-01 00:00:00")
        self.assertEqual(create_payload["endDateTime"], "2026-09-30 23:59:59")
        self.assertNotIn("startDate", create_payload)
        self.assertNotIn("endDate", create_payload)
        self.assertEqual(create_payload["status"], "PAUSED")
        self.assertEqual(create_payload["advertisingChannelType"], "DEMAND_GEN")
        self.assertEqual(
            create_payload["containsEuPoliticalAdvertising"],
            "DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING",
        )

    @override_settings(ADS_CREDENTIAL_ENCRYPTION_KEY="test-credential-key")
    @patch("ads.providers.GoogleAdsProvider.fetch_campaign_by_id", return_value={"status": "PAUSED"})
    @patch("ads.providers.GoogleAdsProvider._post_google")
    def test_google_demand_gen_campaign_omits_none_date_times(self, mock_post, _mock_readback):
        identity, campaign, account = self._execution_campaign()
        campaign.start_date = None
        campaign.end_date = None
        mock_post.side_effect = [
            {"results": [{"resourceName": "customers/1/campaignBudgets/2"}]},
            {"results": [{"resourceName": "customers/1/campaigns/3"}]},
        ]
        execution = AdChannelExecution.objects.create(
            campaign=campaign,
            advertiser_identity=identity,
            channel="google",
            external_account=account,
            idempotency_key="no-date-test",
            budget_allocation=Decimal("25000.00"),
        )
        payload = external_campaign_execution_service.build_external_payload(campaign, "google", account)

        provider_for("google").create_campaign(execution, payload, idempotency_key="no-date-test")

        create_payload = mock_post.call_args_list[1].args[2]["operations"][0]["create"]
        self.assertNotIn("startDateTime", create_payload)
        self.assertNotIn("endDateTime", create_payload)
        self.assertNotIn("startDate", create_payload)
        self.assertNotIn("endDate", create_payload)
        self.assertEqual(create_payload["status"], "PAUSED")
        self.assertEqual(create_payload["advertisingChannelType"], "DEMAND_GEN")
        self.assertEqual(
            create_payload["containsEuPoliticalAdvertising"],
            "DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING",
        )

    @override_settings(ADS_CREDENTIAL_ENCRYPTION_KEY="test-credential-key")
    @patch("ads.providers.requests.post")
    def test_google_mutation_error_retains_only_sanitized_diagnostics(self, mock_post):
        class Response:
            status_code = 400
            headers = {"request-id": "safe-request-id"}
            def json(self):
                return {"error": {
                    "status": "INVALID_ARGUMENT",
                    "message": "access_token=raw-secret must not appear",
                    "details": [{
                        "requestId": "safe-detail-request-id",
                        "errors": [{
                            "errorCode": {"fieldError": "REQUIRED"},
                            "message": "client_secret=raw-client-secret field is required",
                            "location": {"fieldPathElements": [
                                {"fieldName": "operations", "index": 0},
                                {"fieldName": "create"},
                                {"fieldName": "campaignBudget"},
                            ]},
                        }],
                    }],
                }}
        mock_post.return_value = Response()
        credential = type("Credential", (), {"encrypted_access_token": "encrypted"})()

        with patch("ads.providers.credential_encryption_service.decrypt", return_value="access-secret"):
            with self.assertRaises(ProviderAPIError) as raised:
                provider_for("google")._post_google(
                    "/customers/1/campaignBudgets:mutate",
                    credential,
                    {},
                    stage="campaign_budget_create",
                )

        exc = raised.exception
        self.assertEqual(exc.stage, "campaign_budget_create")
        self.assertEqual(exc.http_status, 400)
        self.assertEqual(exc.safe_details["google_ads_request_id"], "safe-request-id")
        self.assertEqual(exc.safe_details["google_error_status"], "INVALID_ARGUMENT")
        self.assertEqual(exc.safe_details["google_ads_error_code"], "fieldError:REQUIRED")
        self.assertEqual(exc.safe_details["google_field_path"], "operations[0].create.campaignBudget")
        serialized = str(exc.safe_details)
        self.assertNotIn("raw-secret", serialized)
        self.assertNotIn("raw-client-secret", serialized)

    @override_settings(
        ADS_CREDENTIAL_ENCRYPTION_KEY="test-credential-key",
        ADS_EXTERNAL_CAMPAIGN_PUBLISHING_ENABLED=True,
        ADS_EXTERNAL_CHANNEL_SYNC_ENABLED=True,
        ADS_EXTERNAL_CAMPAIGN_TEST_MODE_ENABLED=True,
        ADS_GOOGLE_CONNECTION_ENABLED=True,
        ADS_GOOGLE_CLIENT_ID="google-client",
        ADS_GOOGLE_CLIENT_SECRET="google-secret",
        ADS_GOOGLE_DEVELOPER_TOKEN="developer-token",
        ADS_GOOGLE_TEST_ACCOUNT_ALLOWLIST=["customers-allowlisted"],
    )
    @patch("ads.execution.logger.warning")
    @patch("ads.providers.GoogleAdsProvider.create_campaign")
    def test_external_execution_logs_and_audits_sanitized_provider_diagnostics(self, mock_create, mock_warning):
        mock_create.side_effect = ProviderAPIError(
            "google_api_error",
            stage="campaign_create",
            http_status=400,
            safe_details={
                "google_ads_request_id": "safe-request-id",
                "google_error_status": "INVALID_ARGUMENT",
                "google_ads_error_code": "fieldError:REQUIRED",
                "google_field_path": "operations[0].create.name",
                "google_message": "Required field is missing.",
                "access_token": "must-never-be-copied",
            },
        )
        identity, campaign, account = self._execution_campaign()
        account.external_account_id = "customers-allowlisted"
        account.save(update_fields=["external_account_id", "updated_at"])
        self.vendor_user.is_staff = True
        self.vendor_user.save(update_fields=["is_staff"])

        execution, result = external_campaign_execution_service.create_execution(
            campaign, "google", account, user=self.vendor_user
        )

        self.assertEqual(execution.last_error, "google_api_error")
        self.assertEqual(result.errors, ["google_api_error"])
        audit = AdvertisingConnectionAuditLog.objects.filter(
            event_type=AdvertisingConnectionAuditLog.EVENT_EXTERNAL_CREATE_FAILED,
            external_account=account,
        ).latest("id")
        self.assertEqual(audit.metadata["stage"], "campaign_create")
        self.assertEqual(audit.metadata["google_ads_error_code"], "fieldError:REQUIRED")
        combined = str(audit.metadata) + str(mock_warning.call_args)
        for secret in ("must-never-be-copied", "google-secret", "developer-token"):
            self.assertNotIn(secret, combined)

    @override_settings(ADS_CREDENTIAL_ENCRYPTION_KEY="test-credential-key")
    @patch("ads.providers.GoogleAdsProvider.sync_status", return_value={"status": AdChannelExecution.STATUS_PAUSED, "external_status": "PAUSED"})
    def test_external_status_sync_updates_only_channel_execution(self, mock_sync):
        identity, campaign, account = self._execution_campaign()
        execution = AdChannelExecution.objects.create(
            campaign=campaign,
            advertiser_identity=identity,
            channel="google",
            external_account=account,
            external_campaign_id="external-123",
            status=AdChannelExecution.STATUS_ACTIVE,
        )

        synced = external_campaign_execution_service.sync_status(execution)
        campaign.refresh_from_db()

        self.assertEqual(synced.status, AdChannelExecution.STATUS_PAUSED)
        self.assertEqual(synced.external_status, "PAUSED")
        self.assertEqual(campaign.status, "active")

    @override_settings(ADS_CREDENTIAL_ENCRYPTION_KEY="test-credential-key")
    def test_external_reporting_normalizes_provider_metrics_without_revenue(self):
        identity, campaign, account = self._execution_campaign()
        execution = AdChannelExecution.objects.create(
            campaign=campaign,
            advertiser_identity=identity,
            channel="google",
            external_account=account,
            status=AdChannelExecution.STATUS_ACTIVE,
            currency="NGN",
        )

        snapshot = external_campaign_execution_service.normalize_reporting(
            execution,
            {
                "metrics": {"impressions": 100, "clicks": 7, "spend": "1234.56", "video_views": 11, "conversions": 2, "currency": "NGN"},
                "metadata": {"access_token": "secret", "safe": "kept"},
            },
            timezone.now().date(),
            timezone.now().date(),
        )

        self.assertEqual(snapshot.impressions, 100)
        self.assertEqual(snapshot.clicks, 7)
        self.assertEqual(snapshot.spend, Decimal("1234.56"))
        self.assertEqual(snapshot.provider_conversions, 2)
        self.assertFalse(hasattr(snapshot, "revenue"))
        self.assertEqual(snapshot.metadata, {"safe": "kept"})

    @override_settings(ADS_ADVERTISER_DASHBOARD_ENABLED=True, ADS_CREDENTIAL_ENCRYPTION_KEY="test-credential-key")
    def test_staff_external_preview_api_requires_staff_and_returns_payload(self):
        identity, campaign, account = self._execution_campaign()
        self.client.force_login(self.vendor_user)
        non_staff = self.client.post(
            reverse("ads_api:management_campaign_external_preview", args=[campaign.pk]),
            data=json.dumps({"channel": "google", "external_account_id": account.pk}),
            content_type="application/json",
        )
        self.assertEqual(non_staff.status_code, 403)

        staff = get_user_model().objects.create_user(
            username="ads-staff",
            email="ads-staff@example.com",
            password="testpass123",
            is_staff=True,
        )
        self.client.force_login(staff)
        response = self.client.post(
            f"{reverse('ads_api:management_campaign_external_preview', args=[campaign.pk])}?advertiser_id={identity.pk}",
            data=json.dumps({"channel": "google", "external_account_id": account.pk}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertTrue(body["dry_run"])
        self.assertEqual(body["provider"], "google")
        self.assertEqual(body["payload"]["campaign"]["campaign_type"], "DEMAND_GEN")

    @override_settings(
        ADS_CREDENTIAL_ENCRYPTION_KEY="test-credential-key",
        ADS_GOOGLE_CONNECTION_ENABLED=True,
        ADS_GOOGLE_CLIENT_ID="google-client",
        ADS_GOOGLE_CLIENT_SECRET="google-secret",
        ADS_GOOGLE_DEVELOPER_TOKEN="developer-token",
        ADS_GOOGLE_LOGIN_CUSTOMER_ID="999-000-1111",
    )
    @patch("ads.providers.requests.post")
    def test_google_create_campaign_creates_paused_and_reads_back(self, mock_post):
        class Response:
            status_code = 200

            def __init__(self, payload):
                self.payload = payload

            def json(self):
                return self.payload

        identity, campaign, account = self._execution_campaign()
        execution = AdChannelExecution.objects.create(
            campaign=campaign,
            advertiser_identity=identity,
            channel="google",
            external_account=account,
            idempotency_key="google-idempotency",
            budget_allocation=Decimal("25000.00"),
            currency="NGN",
        )
        payload = external_campaign_execution_service.build_external_payload(campaign, "google", account)
        mock_post.side_effect = [
            Response({"results": [{"resourceName": "customers/123/campaignBudgets/456"}]}),
            Response({"results": [{"resourceName": "customers/123/campaigns/789"}]}),
            Response(
                {
                    "results": [
                        {
                            "campaign": {
                                "id": "789",
                                "name": "Created",
                                "status": "PAUSED",
                                "advertisingChannelType": "DEMAND_GEN",
                            },
                            "customer": {"currencyCode": "NGN", "timeZone": "Africa/Lagos"},
                        }
                    ]
                }
            ),
        ]

        result = provider_for("google").create_campaign(execution, payload, idempotency_key=execution.idempotency_key)

        self.assertEqual(result["external_campaign_id"], "789")
        self.assertEqual(result["external_status"], "PAUSED")
        budget_payload = mock_post.call_args_list[0].kwargs["json"]
        campaign_payload = mock_post.call_args_list[1].kwargs["json"]
        self.assertEqual(campaign_payload["operations"][0]["create"]["status"], "PAUSED")
        self.assertEqual(campaign_payload["operations"][0]["create"]["advertisingChannelType"], "DEMAND_GEN")
        self.assertEqual(budget_payload["operations"][0]["create"]["amountMicros"], 25000000000)
        self.assertEqual(mock_post.call_args_list[0].kwargs["headers"]["login-customer-id"], "9990001111")
        self.assertEqual(mock_post.call_args_list[1].kwargs["headers"]["request-id"], "google-idempotency")

    @override_settings(ADS_CREDENTIAL_ENCRYPTION_KEY="test-credential-key")
    @patch("ads.providers.requests.post")
    def test_google_pause_resume_and_reporting_are_mocked_and_normalized(self, mock_post):
        class Response:
            status_code = 200

            def __init__(self, payload):
                self.payload = payload

            def json(self):
                return self.payload

        identity, campaign, account = self._execution_campaign()
        execution = AdChannelExecution.objects.create(
            campaign=campaign,
            advertiser_identity=identity,
            channel="google",
            external_account=account,
            external_campaign_id="789",
            idempotency_key="google-idempotency",
            status=AdChannelExecution.STATUS_PAUSED,
            currency="NGN",
        )
        mock_post.side_effect = [
            Response({"results": [{"resourceName": "customers/123/campaigns/789"}]}),
            Response({"results": [{"resourceName": "customers/123/campaigns/789"}]}),
            Response(
                {
                    "results": [
                        {
                            "metrics": {
                                "impressions": 9,
                                "clicks": 3,
                                "costMicros": 1200000,
                                "videoTrueviewViews": 4,
                                "conversions": 1,
                            },
                            "customer": {"currencyCode": "NGN"},
                        }
                    ]
                }
            ),
        ]

        provider_for("google").pause_campaign(execution)
        provider_for("google").resume_campaign(execution)
        reporting = provider_for("google").fetch_reporting(execution, timezone.now().date(), timezone.now().date())
        snapshot = external_campaign_execution_service.normalize_reporting(
            execution,
            reporting,
            timezone.now().date(),
            timezone.now().date(),
        )

        self.assertEqual(snapshot.impressions, 9)
        self.assertEqual(snapshot.clicks, 3)
        self.assertEqual(snapshot.video_views, 4)
        self.assertEqual(snapshot.spend, Decimal("1.2"))
        self.assertEqual(mock_post.call_args_list[0].kwargs["json"]["operations"][0]["update"]["status"], "PAUSED")
        self.assertEqual(mock_post.call_args_list[1].kwargs["json"]["operations"][0]["update"]["status"], "ENABLED")

    @override_settings(ADS_CREDENTIAL_ENCRYPTION_KEY="test-credential-key")
    @patch("ads.providers.GoogleAdsProvider._search_google")
    def test_google_reporting_uses_current_gaql_fields_and_normalizes(self, mock_search):
        identity, campaign, account = self._execution_campaign()
        execution = AdChannelExecution.objects.create(
            campaign=campaign,
            advertiser_identity=identity,
            channel="google",
            external_account=account,
            external_campaign_id="24158739327",
            currency="NGN",
        )
        mock_search.return_value = {"results": [{
            "metrics": {
                "impressions": "12",
                "clicks": "3",
                "costMicros": "2500000",
                "videoTrueviewViews": "4",
                "conversions": 2.0,
            },
            "customer": {"currencyCode": "NGN"},
        }]}

        payload = provider_for("google").fetch_reporting(execution, "2026-08-22", "2026-08-31")
        snapshot = external_campaign_execution_service.normalize_reporting(
            execution, payload, "2026-08-22", "2026-08-31"
        )

        query = mock_search.call_args.args[2]
        self.assertIn("metrics.video_trueview_views", query)
        self.assertNotIn("metrics.video_views", query)
        for field in (
            "metrics.impressions", "metrics.clicks", "metrics.cost_micros",
            "metrics.conversions", "customer.currency_code", "segments.date",
        ):
            self.assertIn(field, query)
        self.assertEqual(mock_search.call_args.kwargs["stage"], "reporting_fetch")
        self.assertEqual(snapshot.impressions, 12)
        self.assertEqual(snapshot.clicks, 3)
        self.assertEqual(snapshot.spend, Decimal("2.5"))
        self.assertEqual(snapshot.video_views, 4)
        self.assertEqual(snapshot.provider_conversions, 2)
        self.assertEqual(snapshot.currency, "NGN")
        self.assertEqual(str(snapshot.reporting_start), "2026-08-22")
        self.assertEqual(str(snapshot.reporting_end), "2026-08-31")

    @override_settings(ADS_CREDENTIAL_ENCRYPTION_KEY="test-credential-key")
    @patch("ads.providers.GoogleAdsProvider._search_google")
    def test_google_reporting_zero_activity_and_empty_results_normalize_to_zero(self, mock_search):
        identity, campaign, account = self._execution_campaign()
        execution = AdChannelExecution.objects.create(
            campaign=campaign,
            advertiser_identity=identity,
            channel="google",
            external_account=account,
            external_campaign_id="24158739327",
            currency="NGN",
        )
        cases = (
            {"results": [{"metrics": {}, "customer": {"currencyCode": "NGN"}}]},
            {"results": []},
        )
        for index, result in enumerate(cases, start=1):
            with self.subTest(result=result):
                mock_search.return_value = result
                day = f"2026-08-{20 + index:02d}"
                payload = provider_for("google").fetch_reporting(execution, day, day)
                snapshot = external_campaign_execution_service.normalize_reporting(execution, payload, day, day)
                self.assertEqual(snapshot.impressions, 0)
                self.assertEqual(snapshot.clicks, 0)
                self.assertEqual(snapshot.spend, Decimal("0"))
                self.assertEqual(snapshot.video_views, 0)
                self.assertEqual(snapshot.provider_conversions, 0)
                self.assertEqual(snapshot.currency, "NGN")

    @override_settings(ADS_CREDENTIAL_ENCRYPTION_KEY="test-credential-key")
    @patch("ads.providers.logger.warning")
    @patch("ads.providers.credential_encryption_service.decrypt", return_value="access-secret")
    @patch("ads.providers.requests.post")
    def test_google_reporting_error_observability_is_sanitized(self, mock_post, _mock_decrypt, mock_warning):
        class Response:
            status_code = 400
            headers = {"request-id": "safe-report-request"}
            def json(self):
                return {"error": {
                    "status": "INVALID_ARGUMENT",
                    "message": "access_token=raw-secret invalid reporting query",
                    "details": [{"errors": [{
                        "errorCode": {"queryError": "UNRECOGNIZED_FIELD"},
                        "message": "client_secret=raw-client-secret unrecognized field",
                        "location": {"fieldPathElements": [{"fieldName": "query"}]},
                    }]}],
                }}
        mock_post.return_value = Response()
        identity, campaign, account = self._execution_campaign()
        execution = AdChannelExecution.objects.create(
            campaign=campaign,
            advertiser_identity=identity,
            channel="google",
            external_account=account,
            external_campaign_id="24158739327",
        )

        with self.assertRaises(ProviderAPIError) as raised:
            provider_for("google").fetch_reporting(execution, "2026-08-22", "2026-08-31")

        self.assertEqual(raised.exception.stage, "reporting_fetch")
        self.assertEqual(raised.exception.http_status, 400)
        rendered_lines = []
        for call in mock_warning.call_args_list:
            log_format, *log_args = call.args
            rendered_lines.append(log_format % tuple(log_args))
        rendered = "\n".join(rendered_lines)
        self.assertIn("stage=reporting_fetch", rendered)
        self.assertIn("google_ads_request_id=safe-report-request", rendered)
        self.assertIn("google_error_status=INVALID_ARGUMENT", rendered)
        self.assertIn("google_ads_error_code=queryError:UNRECOGNIZED_FIELD", rendered)
        self.assertIn("google_field_path=query", rendered)
        for secret in ("raw-secret", "raw-client-secret", "access-secret"):
            self.assertNotIn(secret, rendered)

    @override_settings(ADS_CREDENTIAL_ENCRYPTION_KEY="test-credential-key")
    @patch("ads.providers.requests.post")
    def test_google_api_rate_and_partial_failures_fail_closed(self, mock_post):
        class Response:
            def __init__(self, status_code, payload):
                self.status_code = status_code
                self.payload = payload

            def json(self):
                return self.payload

        identity, campaign, account = self._execution_campaign()
        execution = AdChannelExecution.objects.create(
            campaign=campaign,
            advertiser_identity=identity,
            channel="google",
            external_account=account,
            idempotency_key="google-idempotency",
            budget_allocation=Decimal("25000.00"),
        )
        payload = external_campaign_execution_service.build_external_payload(campaign, "google", account)
        mock_post.return_value = Response(429, {})
        with self.assertRaises(ProviderAPIError):
            provider_for("google").create_campaign(execution, payload, idempotency_key=execution.idempotency_key)

        mock_post.return_value = Response(200, {"partialFailureError": {"message": "bad mutate"}})
        with self.assertRaises(ProviderAPIError):
            provider_for("google").create_campaign(execution, payload, idempotency_key=execution.idempotency_key)

    @override_settings(ADS_CREDENTIAL_ENCRYPTION_KEY="test-credential-key")
    @patch("ads.providers.GoogleAdsProvider._search_google")
    def test_google_campaign_readback_uses_current_datetime_fields(self, mock_search):
        identity, campaign, account = self._execution_campaign()
        execution = AdChannelExecution.objects.create(
            campaign=campaign,
            advertiser_identity=identity,
            channel="google",
            external_account=account,
            external_campaign_id="123456789",
        )
        mock_search.return_value = {"results": [{"campaign": {
            "id": "123456789",
            "name": "Readback campaign",
            "status": "PAUSED",
            "advertisingChannelType": "DEMAND_GEN",
            "startDateTime": "2026-08-22 00:00:00",
            "endDateTime": "2026-08-31 23:59:59",
            "campaignBudget": "customers/6711004233/campaignBudgets/55",
        }}]}

        readback = provider_for("google").fetch_campaign_by_id(execution, "123456789")

        query = mock_search.call_args.args[2]
        self.assertIn("campaign.start_date_time", query)
        self.assertIn("campaign.end_date_time", query)
        self.assertNotIn("campaign.start_date,", query)
        self.assertNotIn("campaign.end_date,", query)
        self.assertEqual(readback["start_date_time"], "2026-08-22 00:00:00")
        self.assertEqual(readback["end_date_time"], "2026-08-31 23:59:59")
        self.assertEqual(readback["campaign_type"], "DEMAND_GEN")
        self.assertEqual(readback["budget_resource_name"], "customers/6711004233/campaignBudgets/55")

    @override_settings(ADS_CREDENTIAL_ENCRYPTION_KEY="test-credential-key")
    @patch("ads.providers.credential_encryption_service.decrypt", return_value="access-secret")
    @patch("ads.providers.requests.post")
    def test_google_campaign_recovery_lookup_is_read_only(self, mock_post, _mock_decrypt):
        class Response:
            status_code = 200
            def json(self):
                return {"results": [{"campaign": {
                    "id": "987654321",
                    "name": "Arolana Google Ads API Test [Arolana Test 1]",
                    "status": "PAUSED",
                    "advertisingChannelType": "DEMAND_GEN",
                    "startDateTime": "2026-08-22 00:00:00",
                    "endDateTime": "2026-08-31 23:59:59",
                    "campaignBudget": "customers/6711004233/campaignBudgets/66",
                }}]}
        mock_post.return_value = Response()
        identity, campaign, account = self._execution_campaign()
        execution = AdChannelExecution.objects.create(
            campaign=campaign,
            advertiser_identity=identity,
            channel="google",
            external_account=account,
        )

        matches = provider_for("google").find_campaign_by_name(
            execution,
            "Arolana Google Ads API Test [Arolana Test 1]",
        )

        self.assertEqual([item["external_campaign_id"] for item in matches], ["987654321"])
        request_url = mock_post.call_args.args[0]
        self.assertTrue(request_url.endswith("/googleAds:search"))
        self.assertNotIn(":mutate", request_url)
        query = mock_post.call_args.kwargs["json"]["query"]
        self.assertIn("campaign.start_date_time", query)
        self.assertIn("campaign.end_date_time", query)
        self.assertNotIn("campaign.start_date,", query)
        self.assertNotIn("campaign.end_date,", query)

    @override_settings(
        ADS_CREDENTIAL_ENCRYPTION_KEY="test-credential-key",
        ADS_EXTERNAL_CAMPAIGN_TEST_MODE_ENABLED=True,
        ADS_EXTERNAL_CAMPAIGN_PUBLISHING_ENABLED=True,
        ADS_EXTERNAL_CHANNEL_SYNC_ENABLED=True,
        ADS_GOOGLE_TEST_ACCOUNT_ALLOWLIST=["allowlisted-customer"],
    )
    def test_google_manual_validation_command_refuses_non_allowlisted_account(self):
        identity, campaign, account = self._execution_campaign()
        staff = get_user_model().objects.create_user(
            username="validation-staff",
            email="validation-staff@example.com",
            password="testpass123",
            is_staff=True,
        )

        with self.assertRaisesMessage(Exception, "not allowlisted"):
            call_command(
                "validate_google_ads_execution",
                campaign_id=campaign.pk,
                external_account_id=account.pk,
                staff_user_id=staff.pk,
                confirm_test_mode=True,
                stdout=StringIO(),
            )

    @override_settings(ADS_ADVERTISER_DASHBOARD_ENABLED=False)
    def test_vendor_and_provider_navigation_hide_ads_when_dashboard_disabled(self):
        self.client.force_login(self.vendor_user)
        vendor_response = self.client.get(reverse("dashboard:vendor_home"))
        self.assertEqual(vendor_response.status_code, 200)
        self.assertNotContains(vendor_response, reverse("ads:marketing_overview"))
        self.assertNotContains(vendor_response, "Arolana Ads")

        provider = self._provider(self.provider_user)
        self.client.force_login(self.provider_user)
        provider_response = self.client.get(reverse("provider_workspace:dashboard"))
        self.assertEqual(provider_response.status_code, 200)
        self.assertContains(provider_response, provider.business_name)
        self.assertNotContains(provider_response, reverse("ads:marketing_overview"))
        self.assertNotContains(provider_response, "Arolana Ads")

    @override_settings(ADS_ADVERTISER_DASHBOARD_ENABLED=True)
    def test_vendor_and_provider_navigation_expose_shared_ads_dashboard(self):
        self.client.force_login(self.vendor_user)
        vendor_response = self.client.get(reverse("dashboard:vendor_home"))
        self.assertEqual(vendor_response.status_code, 200)
        self.assertContains(vendor_response, reverse("ads:marketing_overview"))
        self.assertContains(vendor_response, "Arolana Ads")

        provider = self._provider(self.provider_user)
        self.client.force_login(self.provider_user)
        provider_response = self.client.get(
            reverse("provider_workspace:dashboard"),
            HTTP_USER_AGENT="Mozilla/5.0 iPhone Mobile",
        )
        self.assertEqual(provider_response.status_code, 200)
        self.assertContains(provider_response, provider.business_name)
        self.assertContains(provider_response, reverse("ads:marketing_overview"))
        self.assertContains(provider_response, "Arolana Ads")

    @override_settings(ADS_ADVERTISER_DASHBOARD_ENABLED=True)
    def test_ads_dashboard_resolves_vendor_and_provider_identities_without_cross_access(self):
        vendor_identity = self.resolver.get_or_create_identity(
            self.resolver.resolve_product_owner(self.product)
        )
        vendor_asset = self._campaign_asset(
            identity=vendor_identity,
            campaign_kwargs={"name": "Vendor Only Ads Campaign"},
        )
        other_product = self._product(self.other_vendor_user, "Other Projector", "other-projector")
        other_vendor_identity = self.resolver.get_or_create_identity(
            self.resolver.resolve_product_owner(other_product)
        )
        self._campaign_asset(
            product=other_product,
            identity=other_vendor_identity,
            campaign_kwargs={"name": "Other Vendor Ads Campaign"},
        )

        provider = self._provider(self.provider_user)
        provider_identity = self.resolver.get_or_create_identity(
            self.resolver.resolve_provider_owner(provider)
        )
        provider_campaign = AdCampaign.objects.create(
            name="Provider Only Ads Campaign",
            campaign_type="sponsored",
            status="active",
            approved=True,
            start_date=timezone.now() - timedelta(days=1),
            end_date=timezone.now() + timedelta(days=1),
            total_budget=Decimal("100.00"),
            spent=Decimal("0.00"),
            max_bid=Decimal("1.00"),
            advertiser_identity=provider_identity,
        )
        CampaignAsset.objects.create(
            campaign=provider_campaign,
            advertiser_identity=provider_identity,
            asset_type=CampaignAsset.ASSET_PROVIDER_PROFILE,
            content_type=ContentType.objects.get_for_model(provider),
            object_id=provider.pk,
            title=provider.business_name,
        )

        self.client.force_login(self.vendor_user)
        vendor_response = self.client.get(reverse("ads:marketing_campaigns"))
        self.assertEqual(vendor_response.status_code, 200)
        self.assertContains(vendor_response, "Vendor Only Ads Campaign")
        self.assertContains(vendor_response, vendor_asset.title)
        self.assertNotContains(vendor_response, "Other Vendor Ads Campaign")
        self.assertNotContains(vendor_response, "Provider Only Ads Campaign")

        provider_response_as_vendor = self.client.get(
            reverse("ads:marketing_campaign_detail", args=[provider_campaign.pk])
        )
        self.assertEqual(provider_response_as_vendor.status_code, 404)

        self.client.force_login(self.provider_user)
        provider_response = self.client.get(reverse("ads:marketing_campaigns"))
        self.assertEqual(provider_response.status_code, 200)
        self.assertContains(provider_response, "Provider Only Ads Campaign")
        self.assertNotContains(provider_response, "Vendor Only Ads Campaign")
        self.assertNotContains(provider_response, "Other Vendor Ads Campaign")

        vendor_response_as_provider = self.client.get(
            reverse("ads:marketing_campaign_detail", args=[vendor_asset.campaign_id])
        )
        self.assertEqual(vendor_response_as_provider.status_code, 404)

    @override_settings(ADS_ADVERTISER_DASHBOARD_ENABLED=True)
    def test_staff_ads_dashboard_can_select_authorized_advertiser_identity(self):
        vendor_identity = self.resolver.get_or_create_identity(
            self.resolver.resolve_product_owner(self.product)
        )
        self._campaign_asset(
            identity=vendor_identity,
            campaign_kwargs={"name": "Staff Selected Vendor Campaign"},
        )
        provider = self._provider(self.provider_user)
        provider_identity = self.resolver.get_or_create_identity(
            self.resolver.resolve_provider_owner(provider)
        )
        AdCampaign.objects.create(
            name="Staff Hidden Provider Campaign",
            campaign_type="sponsored",
            status="active",
            approved=True,
            start_date=timezone.now() - timedelta(days=1),
            end_date=timezone.now() + timedelta(days=1),
            total_budget=Decimal("100.00"),
            spent=Decimal("0.00"),
            max_bid=Decimal("1.00"),
            advertiser_identity=provider_identity,
        )
        staff = get_user_model().objects.create_user(
            username="ads-dashboard-staff",
            email="ads-dashboard-staff@example.com",
            password="testpass123",
            is_staff=True,
        )

        self.client.force_login(staff)
        response = self.client.get(
            reverse("ads:marketing_campaigns"),
            {"advertiser_id": vendor_identity.pk},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Staff Selected Vendor Campaign")
        self.assertNotContains(response, "Staff Hidden Provider Campaign")

    @override_settings(ADS_ADVERTISER_DASHBOARD_ENABLED=True)
    def test_mobile_web_dashboard_template_uses_card_layout(self):
        self.client.force_login(self.vendor_user)

        response = self.client.get(
            reverse("ads:marketing_overview"),
            HTTP_USER_AGENT="Mozilla/5.0 iPhone Mobile",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ads-mkt-grid")
        self.assertContains(response, "Create Campaign")

    @override_settings(
        ADS_RECOMMENDATION_V2_API_ENABLED=True,
        ADS_RECOMMENDATION_V2_WEB_ENABLED=True,
        ADS_RECOMMENDATION_V2_MOBILE_WEB_ENABLED=True,
        ADS_RECOMMENDATION_V2_INTERNAL_TESTING_ENABLED=True,
        ADS_RECOMMENDATION_V2_SPONSORED_ENABLED=False,
    )
    def test_staff_internal_web_shelf_renders_tracking_and_supported_surfaces(self):
        request = self._staff_request()
        sample_results = [
            {
                "type": "product",
                "id": self.product.pk,
                "item": {"name": self.product.name, "url": self.product.get_absolute_url()},
                "sponsored": False,
                "tracking": {},
            },
            {
                "type": "product_video",
                "id": 44,
                "item": {"title": "Demo Video", "url": "/videos/demo/"},
                "sponsored": True,
                "label": "Sponsored",
                "sponsor": {"name": "Vendor One"},
                "tracking": {"delivery_id": str(uuid4()), "asset_id": 1, "campaign_id": 2},
            },
        ]
        surfaces = ["homepage", "search", "category", "product_recommendations", "video", "service", "provider", "store"]

        with patch("ads.frontend.decisioning_service.recommendations_for_request", return_value=sample_results):
            for surface in surfaces:
                shelf = recommendation_shelf(request, placement=surface, limit=2)
                html = render_to_string("ads/partials/v2_recommendation_shelf.html", shelf, request=request)
                self.assertIn('data-ads-v2-shelf', html)
                self.assertIn('data-ads-v2-card', html)
                self.assertIn("Sponsored", html)
                self.assertIn("product_video", html)
                self.assertIn(reverse("ads_api:events_v2"), html)

    @override_settings(
        ADS_RECOMMENDATION_V2_API_ENABLED=True,
        ADS_RECOMMENDATION_V2_WEB_ENABLED=True,
        ADS_RECOMMENDATION_V2_INTERNAL_TESTING_ENABLED=True,
    )
    def test_v2_web_shelf_fails_closed_for_normal_customer_and_decisioning_errors(self):
        normal_request = self.factory.get("/")
        normal_request.user = self.customer_user
        normal_request.session = {}

        self.assertEqual(
            recommendation_shelf(normal_request, placement="homepage")["results"],
            [],
        )

        staff_request = self._staff_request()
        with patch("ads.frontend.decisioning_service.recommendations_for_request", side_effect=RuntimeError("boom")):
            shelf = recommendation_shelf(staff_request, placement="homepage")

        self.assertTrue(shelf["fallback"])
        self.assertEqual(shelf["results"], [])

    @override_settings(
        ADS_RECOMMENDATION_V2_API_ENABLED=True,
        ADS_RECOMMENDATION_V2_MOBILE_WEB_ENABLED=True,
        ADS_RECOMMENDATION_V2_INTERNAL_TESTING_ENABLED=True,
    )
    def test_mobile_web_shelf_uses_mobile_client_gate(self):
        request = self._staff_request(mobile=True)
        with patch("ads.frontend.decisioning_service.recommendations_for_request", return_value=[]):
            shelf = recommendation_shelf(request, placement="homepage")

        self.assertTrue(shelf["enabled"])
        self.assertEqual(shelf["client"], "mobile_web")
    @override_settings(
        ADS_ADVERTISER_DASHBOARD_ENABLED=True,
        ADS_GOOGLE_CONNECTION_ENABLED=True,
        ADS_GOOGLE_CLIENT_ID="google-client",
        ADS_GOOGLE_CLIENT_SECRET="google-secret",
        ADS_GOOGLE_DEVELOPER_TOKEN="developer-token",
        ADS_CREDENTIAL_ENCRYPTION_KEY="test-credential-key",
    )
    def test_browser_connected_accounts_starts_oauth_with_authorization_redirect(self):
        self.client.force_login(self.vendor_user)
        response = self.client.get(reverse("ads:marketing_connected_accounts"))
        body = response.content.decode("utf-8")
        self.assertEqual(response.status_code, 200)
        self.assertIn(reverse("ads_api:management_connected_account_connect", args=["google"]), body)
        self.assertIn("payload.authorization_url", body)
        self.assertIn("window.location.assign(payload.authorization_url)", body)

    @override_settings(ADS_ADVERTISER_DASHBOARD_ENABLED=True)
    def test_browser_multiple_account_selection_requires_explicit_choice(self):
        identity = self.resolver.get_or_create_identity(self.resolver.resolve_product_owner(self.product))
        pending = ExternalAdvertisingAccount.objects.create(
            advertiser_identity=identity,
            channel="google",
            external_account_id="pending:browser",
            display_name="Google pending account selection",
            status=ExternalAdvertisingAccount.STATUS_PENDING,
            metadata={"discovered_accounts": [
                {"external_account_id": "1111111111", "display_name": "Test account one"},
                {"external_account_id": "2222222222", "display_name": "Test account two"},
            ]},
        )
        self.client.force_login(self.vendor_user)
        session = self.client.session
        session["ads_pending_account_selection"] = {"provider": "google", "connection_id": pending.pk}
        session.save()
        response = self.client.get(reverse("ads:marketing_connected_account_select", args=["google"]))
        body = response.content.decode("utf-8")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Test account one")
        self.assertContains(response, "Test account two")
        self.assertEqual(body.count('type="radio" name="external_account_id"'), 2)
        self.assertNotIn(" checked", body)
        self.assertIn("Confirm account", body)

    @override_settings(ADS_ADVERTISER_DASHBOARD_ENABLED=True)
    def test_browser_successful_selection_redirects_back_without_credentials(self):
        identity = self.resolver.get_or_create_identity(self.resolver.resolve_product_owner(self.product))
        pending = ExternalAdvertisingAccount.objects.create(
            advertiser_identity=identity,
            channel="google",
            external_account_id="pending:browser-success",
            display_name="Google pending account selection",
            status=ExternalAdvertisingAccount.STATUS_PENDING,
            metadata={"discovered_accounts": [{"external_account_id": "1111111111", "display_name": "Safe test account"}]},
        )
        self.client.force_login(self.vendor_user)
        session = self.client.session
        session["ads_pending_account_selection"] = {"provider": "google", "connection_id": pending.pk}
        session.save()
        response = self.client.get(reverse("ads:marketing_connected_account_select", args=["google"]))
        body = response.content.decode("utf-8")
        self.assertIn(f'{reverse("ads:marketing_connected_accounts")}?oauth=connected', body)
        self.assertIn("window.location.assign(selectionForm.dataset.returnUrl)", body)
        for secret in ("access_token", "refresh_token", "oauth-code", "developer-token", "google-secret"):
            self.assertNotIn(secret, body)

    @override_settings(ADS_ADVERTISER_DASHBOARD_ENABLED=True)
    def test_browser_account_selection_rejects_unauthorized_user(self):
        response = self.client.get(reverse("ads:marketing_connected_account_select", args=["google"]))
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response.url)

    @override_settings(ADS_ADVERTISER_DASHBOARD_ENABLED=True)
    def test_browser_oauth_state_failure_returns_safe_error_without_query_secrets(self):
        self.client.force_login(self.vendor_user)
        response = self.client.get(
            reverse("ads_api:management_connected_account_callback", args=["google"]),
            {"state": "invalid-state", "code": "sensitive-oauth-code"},
            HTTP_ACCEPT="text/html",
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/ads/marketing/connected-accounts/?oauth_error=connection_failed")
        self.assertNotIn("sensitive-oauth-code", response.url)

    @override_settings(ADS_ADVERTISER_DASHBOARD_ENABLED=True)
    def test_browser_connected_state_shows_customer_and_reauthorization_status(self):
        identity = self.resolver.get_or_create_identity(self.resolver.resolve_product_owner(self.product))
        ExternalAdvertisingAccount.objects.create(
            advertiser_identity=identity,
            channel="google",
            external_account_id="1111111111",
            display_name="Founder Google test account",
            status=ExternalAdvertisingAccount.STATUS_REAUTHORIZATION_REQUIRED,
        )
        self.client.force_login(self.vendor_user)
        response = self.client.get(reverse("ads:marketing_connected_accounts"))
        self.assertContains(response, "Founder Google test account")
        self.assertContains(response, "1111111111")
        self.assertContains(response, ExternalAdvertisingAccount.STATUS_REAUTHORIZATION_REQUIRED)

    @override_settings(
        ADS_ADVERTISER_DASHBOARD_ENABLED=True,
        ADS_GOOGLE_CONNECTION_ENABLED=True,
        ADS_GOOGLE_CLIENT_ID="google-client",
        ADS_GOOGLE_CLIENT_SECRET="google-secret",
        ADS_GOOGLE_DEVELOPER_TOKEN="developer-token",
        ADS_CREDENTIAL_ENCRYPTION_KEY="test-credential-key",
    )
    @patch("ads.providers.requests.post")
    def test_google_callback_missing_access_token_fails_before_persistence_with_safe_stage(self, mock_post):
        class Response:
            status_code = 200
            headers = {}
            def json(self): return {"refresh_token": "refresh-secret", "expires_in": 3600, "scope": "https://www.googleapis.com/auth/adwords", "token_type": "Bearer"}
        mock_post.return_value = Response()
        self.client.force_login(self.vendor_user)
        self.client.post(reverse("ads_api:management_connected_account_connect", args=["google"]))
        state = AdvertisingOAuthState.objects.get()
        before = ExternalAdvertisingAccount.objects.count()

        response = self.client.get(reverse("ads_api:management_connected_account_callback", args=["google"]), {"state": state.state, "code": "oauth-code-secret"})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "missing_access_token")
        self.assertEqual(ExternalAdvertisingAccount.objects.count(), before)
        audit = AdvertisingConnectionAuditLog.objects.filter(event_type=AdvertisingConnectionAuditLog.EVENT_AUTHORIZATION_FAILED).latest("id")
        self.assertEqual(audit.metadata["stage"], "token_response_validation")
        self.assertEqual(audit.metadata["access_credential_present"], "False")
        self.assertNotIn("oauth-code-secret", response.content.decode("utf-8") + str(audit.metadata))

    @override_settings(
        ADS_ADVERTISER_DASHBOARD_ENABLED=True,
        ADS_GOOGLE_CONNECTION_ENABLED=True,
        ADS_GOOGLE_CLIENT_ID="google-client",
        ADS_GOOGLE_CLIENT_SECRET="google-secret",
        ADS_GOOGLE_DEVELOPER_TOKEN="developer-token",
        ADS_GOOGLE_LOGIN_CUSTOMER_ID="6225356762",
        ADS_CREDENTIAL_ENCRYPTION_KEY="test-credential-key",
    )
    @patch("ads.providers.requests.get")
    @patch("ads.providers.requests.post")
    def test_google_callback_missing_refresh_token_is_not_fatal(self, mock_post, mock_get):
        class Response:
            status_code = 200
            headers = {}
            def __init__(self, payload): self.payload = payload
            def json(self): return self.payload
        def post(url, **_kwargs):
            if url == "https://oauth2.googleapis.com/token":
                return Response({"access_token": "access-secret", "expires_in": 3600, "scope": "https://www.googleapis.com/auth/adwords", "token_type": "Bearer"})
            return Response({"results": [{"customerClient": {"clientCustomer": "customers/4495492748", "descriptiveName": "Test client", "manager": False, "status": "ENABLED", "level": 1}}]})
        mock_post.side_effect = post
        mock_get.return_value = Response({"resourceNames": ["customers/6225356762"]})
        self.client.force_login(self.vendor_user)
        self.client.post(reverse("ads_api:management_connected_account_connect", args=["google"]))
        state = AdvertisingOAuthState.objects.get()

        response = self.client.get(reverse("ads_api:management_connected_account_callback", args=["google"]), {"state": state.state, "code": "oauth-code"})

        self.assertEqual(response.status_code, 200, response.content)
        pending = ExternalAdvertisingAccount.objects.get(pk=response.json()["connection_id"])
        self.assertFalse(bool(pending.credential.encrypted_refresh_token))

    @override_settings(
        ADS_ADVERTISER_DASHBOARD_ENABLED=True,
        ADS_GOOGLE_CONNECTION_ENABLED=True,
        ADS_GOOGLE_CLIENT_ID="google-client",
        ADS_GOOGLE_CLIENT_SECRET="google-secret",
        ADS_GOOGLE_DEVELOPER_TOKEN="developer-token",
    )
    @patch("ads.providers.requests.post")
    def test_google_callback_token_exchange_error_records_sanitized_status(self, mock_post):
        class Response:
            status_code = 400
            headers = {}
            def json(self): return {"error": "invalid_grant", "error_description": "sensitive detail must not be persisted"}
        mock_post.return_value = Response()
        self.client.force_login(self.vendor_user)
        self.client.post(reverse("ads_api:management_connected_account_connect", args=["google"]))
        state = AdvertisingOAuthState.objects.get()

        response = self.client.get(reverse("ads_api:management_connected_account_callback", args=["google"]), {"state": state.state, "code": "oauth-code-secret"})

        self.assertEqual(response.status_code, 400)
        audit = AdvertisingConnectionAuditLog.objects.filter(event_type=AdvertisingConnectionAuditLog.EVENT_AUTHORIZATION_FAILED).latest("id")
        self.assertEqual(audit.metadata["stage"], "code_exchange")
        self.assertEqual(audit.metadata["http_status"], "400")
        self.assertNotIn("sensitive detail", str(audit.metadata))
        self.assertNotIn("oauth-code-secret", response.content.decode("utf-8") + str(audit.metadata))

    @override_settings(
        ADS_ADVERTISER_DASHBOARD_ENABLED=True,
        ADS_GOOGLE_CONNECTION_ENABLED=True,
        ADS_GOOGLE_CLIENT_ID="google-client",
        ADS_GOOGLE_CLIENT_SECRET="google-secret",
        ADS_GOOGLE_DEVELOPER_TOKEN="developer-token",
        ADS_CREDENTIAL_ENCRYPTION_KEY="test-credential-key",
    )
    @patch("ads.providers.credential_encryption_service.encrypt", side_effect=CredentialEncryptionError("credential_encryption_failed"))
    @patch("ads.providers.requests.post")
    def test_google_callback_credential_encryption_failure_is_safely_staged(self, mock_post, _mock_encrypt):
        class Response:
            status_code = 200
            headers = {}
            def json(self): return {"access_token": "access-secret", "refresh_token": "refresh-secret", "expires_in": 3600}
        mock_post.return_value = Response()
        self.client.force_login(self.vendor_user)
        self.client.post(reverse("ads_api:management_connected_account_connect", args=["google"]))
        state = AdvertisingOAuthState.objects.get()

        response = self.client.get(reverse("ads_api:management_connected_account_callback", args=["google"]), {"state": state.state, "code": "oauth-code"})

        self.assertEqual(response.status_code, 400)
        audit = AdvertisingConnectionAuditLog.objects.filter(event_type=AdvertisingConnectionAuditLog.EVENT_AUTHORIZATION_FAILED).latest("id")
        self.assertEqual(audit.metadata["stage"], "credential_encryption")
        self.assertEqual(audit.metadata["exception_class"], "CredentialEncryptionError")

    @override_settings(
        ADS_ADVERTISER_DASHBOARD_ENABLED=True,
        ADS_GOOGLE_CONNECTION_ENABLED=True,
        ADS_GOOGLE_CLIENT_ID="google-client",
        ADS_GOOGLE_CLIENT_SECRET="google-secret",
        ADS_GOOGLE_DEVELOPER_TOKEN="developer-token",
        ADS_CREDENTIAL_ENCRYPTION_KEY="test-credential-key",
    )
    @patch("ads.providers.requests.get")
    @patch("ads.providers.requests.post")
    def test_google_callback_discovery_failure_records_http_status_and_rolls_back(self, mock_post, mock_get):
        class Response:
            headers = {"request-id": "safe-request-id"}
            def __init__(self, status_code, payload): self.status_code, self.payload = status_code, payload
            def json(self): return self.payload
        mock_post.return_value = Response(200, {"access_token": "access-secret", "refresh_token": "refresh-secret", "expires_in": 3600})
        mock_get.return_value = Response(403, {"error": {"code": 403, "status": "PERMISSION_DENIED", "message": "Customer is not enabled for this credential."}})
        self.client.force_login(self.vendor_user)
        self.client.post(reverse("ads_api:management_connected_account_connect", args=["google"]))
        state = AdvertisingOAuthState.objects.get()
        before = ExternalAdvertisingAccount.objects.count()

        response = self.client.get(reverse("ads_api:management_connected_account_callback", args=["google"]), {"state": state.state, "code": "oauth-code"})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(ExternalAdvertisingAccount.objects.count(), before)
        audit = AdvertisingConnectionAuditLog.objects.filter(event_type=AdvertisingConnectionAuditLog.EVENT_AUTHORIZATION_FAILED).latest("id")
        self.assertEqual(audit.metadata["stage"], "list_accessible_customers")
        self.assertEqual(audit.metadata["http_status"], "403")
        self.assertEqual(audit.metadata["reason"], "google_account_discovery_failed")

    @override_settings(
        ADS_ADVERTISER_DASHBOARD_ENABLED=True,
        ADS_GOOGLE_CONNECTION_ENABLED=True,
        ADS_GOOGLE_CLIENT_ID="google-client",
        ADS_GOOGLE_CLIENT_SECRET="google-secret",
        ADS_GOOGLE_DEVELOPER_TOKEN="developer-token",
        ADS_CREDENTIAL_ENCRYPTION_KEY="test-credential-key",
    )
    @patch("ads.providers.requests.get")
    @patch("ads.providers.requests.post")
    def test_google_discovery_failure_rolls_back_account_but_not_consumed_state(self, mock_post, mock_get):
        class Response:
            headers = {}
            def __init__(self, status_code, payload):
                self.status_code = status_code
                self.payload = payload
            def json(self):
                return self.payload
        mock_post.return_value = Response(200, {
            "access_token": "access-secret",
            "refresh_token": "refresh-secret",
            "expires_in": 3600,
        })
        mock_get.return_value = Response(403, {
            "error": {"status": "PERMISSION_DENIED", "message": "Discovery denied."}
        })
        self.client.force_login(self.vendor_user)
        self.client.post(reverse("ads_api:management_connected_account_connect", args=["google"]))
        state = AdvertisingOAuthState.objects.get()
        account_count = ExternalAdvertisingAccount.objects.count()

        first = self.client.get(
            reverse("ads_api:management_connected_account_callback", args=["google"]),
            {"state": state.state, "code": "first-oauth-code-secret"},
        )

        self.assertEqual(first.status_code, 400)
        state.refresh_from_db()
        self.assertIsNotNone(state.used_at)
        self.assertEqual(ExternalAdvertisingAccount.objects.count(), account_count)
        self.assertEqual(AdvertisingCredential.objects.count(), 0)

        second = self.client.get(
            reverse("ads_api:management_connected_account_callback", args=["google"]),
            {"state": state.state, "code": "second-oauth-code-secret"},
        )
        self.assertEqual(second.status_code, 400)
        self.assertEqual(second.json()["error"], "state_reused")
        self.assertEqual(mock_post.call_count, 1)
        audit_text = str(list(
            AdvertisingConnectionAuditLog.objects.filter(
                event_type=AdvertisingConnectionAuditLog.EVENT_AUTHORIZATION_FAILED
            ).values_list("message", "metadata")
        ))
        for secret in (
            "first-oauth-code-secret", "second-oauth-code-secret",
            "access-secret", "refresh-secret", "google-secret", "developer-token",
        ):
            self.assertNotIn(secret, audit_text + first.content.decode("utf-8") + second.content.decode("utf-8"))

    @override_settings(
        ADS_ADVERTISER_DASHBOARD_ENABLED=True,
        ADS_GOOGLE_CONNECTION_ENABLED=True,
        ADS_GOOGLE_CLIENT_ID="google-client",
        ADS_GOOGLE_CLIENT_SECRET="google-secret",
        ADS_GOOGLE_DEVELOPER_TOKEN="developer-token",
        ADS_CREDENTIAL_ENCRYPTION_KEY="test-credential-key",
    )
    @patch("ads.api_views.logger.warning")
    @patch("ads.providers.requests.get")
    @patch("ads.providers.requests.post")
    def test_google_callback_log_line_contains_sanitized_failure_fields(self, mock_post, mock_get, mock_warning):
        class Response:
            headers = {}
            def __init__(self, status_code, payload): self.status_code, self.payload = status_code, payload
            def json(self): return self.payload
        mock_post.return_value = Response(200, {"access_token": "access-secret", "refresh_token": "refresh-secret", "expires_in": 3600})
        mock_get.return_value = Response(403, {"error": {"status": "PERMISSION_DENIED", "details": [{"errors": [{"errorCode": {"authorizationError": "USER_PERMISSION_DENIED"}}]}]}})
        self.client.force_login(self.vendor_user)
        self.client.post(reverse("ads_api:management_connected_account_connect", args=["google"]))
        state = AdvertisingOAuthState.objects.get()

        self.client.get(reverse("ads_api:management_connected_account_callback", args=["google"]), {"state": state.state, "code": "oauth-code-secret"})

        log_format, *log_args = mock_warning.call_args.args
        rendered = log_format % tuple(log_args)
        self.assertIn("failure_stage=list_accessible_customers", rendered)
        self.assertIn("exception_class=ProviderAPIError", rendered)
        self.assertIn("reason=google_account_discovery_failed", rendered)
        self.assertIn("http_status=403", rendered)
        self.assertIn("google_ads_error_code=authorizationError:USER_PERMISSION_DENIED", rendered)
        for secret in ("oauth-code-secret", "access-secret", "refresh-secret", "google-secret", "developer-token"):
            self.assertNotIn(secret, rendered)

    @override_settings(
        ADS_GOOGLE_LOGIN_CUSTOMER_ID="7973229750",
        ADS_GOOGLE_DEVELOPER_TOKEN="developer-token",
    )
    @patch("ads.providers.credential_encryption_service.decrypt", return_value="access-secret")
    @patch("ads.providers.logger.warning")
    @patch("ads.providers.GoogleAdsProvider._search_google", return_value={"results": []})
    @patch("ads.providers.requests.get")
    def test_google_discovery_logs_only_safe_accessible_customer_names_before_gaql(
        self, mock_get, mock_search, mock_warning, _mock_decrypt
    ):
        class Response:
            status_code = 200
            def json(self):
                return {
                    "resourceNames": [
                        "customers/7973229750",
                        "customers/6711004233",
                        "unsafe-resource\naccess_token=secret",
                    ]
                }
        mock_get.return_value = Response()
        credential = type("Credential", (), {"encrypted_access_token": "encrypted"})()

        provider_for("google").list_ad_accounts(credential)

        rendered_lines = []
        for call in mock_warning.call_args_list:
            log_format, *log_args = call.args
            rendered_lines.append(log_format % tuple(log_args))
        rendered = "\n".join(rendered_lines)
        self.assertIn("Google Ads discovery entering listAccessibleCustomers", rendered)
        self.assertIn("customers/7973229750", rendered)
        self.assertIn("customers/6711004233", rendered)
        self.assertIn("includes_login_customer=True", rendered)
        self.assertIn("Google Ads manager hierarchy target login_customer_id=7973229750", rendered)
        self.assertNotIn("access_token", rendered)
        mock_search.assert_called()

    @override_settings(ADS_GOOGLE_DEVELOPER_TOKEN="developer-token")
    @patch("ads.providers.credential_encryption_service.decrypt", return_value="access-secret")
    @patch("ads.providers.logger.warning")
    @patch("ads.providers.requests.get")
    def test_google_discovery_logs_sanitized_list_accessible_failure(
        self, mock_get, mock_warning, _mock_decrypt
    ):
        class Response:
            status_code = 403
            headers = {}
            def json(self):
                return {"error": {"status": "PERMISSION_DENIED", "details": [{"errors": [{"errorCode": {"authorizationError": "USER_PERMISSION_DENIED"}}]}]}}
        mock_get.return_value = Response()
        credential = type("Credential", (), {"encrypted_access_token": "encrypted"})()

        with self.assertRaises(ProviderAPIError):
            provider_for("google").list_ad_accounts(credential)

        rendered_lines = []
        for call in mock_warning.call_args_list:
            log_format, *log_args = call.args
            rendered_lines.append(log_format % tuple(log_args))
        rendered = "\n".join(rendered_lines)
        self.assertIn("Google Ads discovery entering listAccessibleCustomers", rendered)
        self.assertIn("http_status=403", rendered)
        self.assertIn("google_ads_error_code=authorizationError:USER_PERMISSION_DENIED", rendered)
        for secret in ("access-secret", "developer-token"):
            self.assertNotIn(secret, rendered)

    @override_settings(
        ADS_GOOGLE_LOGIN_CUSTOMER_ID="7973229750",
        ADS_GOOGLE_DEVELOPER_TOKEN="developer-token",
    )
    @patch("ads.providers.credential_encryption_service.decrypt", return_value="access-secret")
    @patch("ads.providers.requests.post")
    @patch("ads.providers.requests.get")
    def test_google_discovery_uses_only_configured_manager_when_two_roots_are_accessible(
        self, mock_get, mock_post, _mock_decrypt
    ):
        mock_get.return_value = self._google_manager_discovery_response({
            "resourceNames": ["customers/6225356762", "customers/7973229750"]
        })
        mock_post.return_value = self._google_manager_discovery_response({"results": []})
        credential = type("Credential", (), {"encrypted_access_token": "encrypted"})()

        provider_for("google").list_ad_accounts(credential)

        self.assertEqual(mock_post.call_count, 1)
        self.assertIn("/customers/7973229750/googleAds:search", mock_post.call_args.args[0])
        self.assertNotIn("6225356762", mock_post.call_args.args[0])

    @override_settings(
        ADS_GOOGLE_LOGIN_CUSTOMER_ID="7973229750",
        ADS_GOOGLE_DEVELOPER_TOKEN="developer-token",
    )
    @patch("ads.providers.credential_encryption_service.decrypt", return_value="access-secret")
    @patch("ads.providers.requests.post")
    @patch("ads.providers.requests.get")
    def test_google_discovery_fails_closed_when_configured_manager_is_missing(
        self, mock_get, mock_post, _mock_decrypt
    ):
        mock_get.return_value = self._google_manager_discovery_response({
            "resourceNames": ["customers/6225356762"]
        })
        credential = type("Credential", (), {"encrypted_access_token": "encrypted"})()

        with self.assertRaisesRegex(ProviderAuthorizationError, "configured_login_customer_not_accessible"):
            provider_for("google").list_ad_accounts(credential)

        mock_post.assert_not_called()

    @override_settings(
        ADS_GOOGLE_LOGIN_CUSTOMER_ID="7973229750",
        ADS_GOOGLE_DEVELOPER_TOKEN="developer-token",
        ADS_EXTERNAL_CAMPAIGN_TEST_MODE_ENABLED=True,
        ADS_GOOGLE_TEST_ACCOUNT_ALLOWLIST=["6711004233"],
    )
    @patch("ads.providers.credential_encryption_service.decrypt", return_value="access-secret")
    @patch("ads.providers.requests.post")
    @patch("ads.providers.requests.get")
    def test_closed_google_test_client_is_eligible_only_with_all_test_gates(
        self, mock_get, mock_post, _mock_decrypt
    ):
        mock_get.return_value = self._google_manager_discovery_response({
            "resourceNames": ["customers/7973229750"]
        })
        mock_post.return_value = self._google_manager_discovery_response({"results": [{"customerClient": {
            "clientCustomer": "customers/6711004233",
            "descriptiveName": "Controlled test client",
            "manager": False,
            "level": 1,
            "status": "CLOSED",
            "testAccount": True,
        }}]})
        credential = type("Credential", (), {"encrypted_access_token": "encrypted"})()

        accounts = provider_for("google").list_ad_accounts(credential)

        self.assertEqual([account.external_account_id for account in accounts], ["6711004233"])
        self.assertTrue(accounts[0].metadata["test_account"])

        gate_variants = (
            {"ADS_EXTERNAL_CAMPAIGN_TEST_MODE_ENABLED": False, "ADS_GOOGLE_TEST_ACCOUNT_ALLOWLIST": ["6711004233"]},
            {"ADS_EXTERNAL_CAMPAIGN_TEST_MODE_ENABLED": True, "ADS_GOOGLE_TEST_ACCOUNT_ALLOWLIST": []},
        )
        for variant in gate_variants:
            with self.subTest(variant=variant), override_settings(**variant):
                self.assertEqual(provider_for("google").list_ad_accounts(credential), [])

    @override_settings(
        ADS_GOOGLE_LOGIN_CUSTOMER_ID="7973229750",
        ADS_GOOGLE_DEVELOPER_TOKEN="developer-token",
        ADS_EXTERNAL_CAMPAIGN_TEST_MODE_ENABLED=True,
        ADS_GOOGLE_TEST_ACCOUNT_ALLOWLIST=["6711004233"],
    )
    @patch("ads.providers.credential_encryption_service.decrypt", return_value="access-secret")
    @patch("ads.providers.requests.post")
    @patch("ads.providers.requests.get")
    def test_closed_non_test_google_client_remains_rejected(
        self, mock_get, mock_post, _mock_decrypt
    ):
        mock_get.return_value = self._google_manager_discovery_response({"resourceNames": ["customers/7973229750"]})
        mock_post.return_value = self._google_manager_discovery_response({"results": [{"customerClient": {
            "clientCustomer": "customers/6711004233",
            "manager": False,
            "status": "CLOSED",
            "testAccount": False,
        }}]})
        credential = type("Credential", (), {"encrypted_access_token": "encrypted"})()

        self.assertEqual(provider_for("google").list_ad_accounts(credential), [])

    @override_settings(
        ADS_GOOGLE_LOGIN_CUSTOMER_ID="7973229750",
        ADS_GOOGLE_DEVELOPER_TOKEN="developer-token",
        ADS_EXTERNAL_CAMPAIGN_TEST_MODE_ENABLED=True,
        ADS_GOOGLE_TEST_ACCOUNT_ALLOWLIST=["6711004233"],
    )
    @patch("ads.providers.credential_encryption_service.decrypt", return_value="access-secret")
    @patch("ads.providers.requests.post")
    @patch("ads.providers.requests.get")
    def test_allowlist_only_google_client_is_not_invented_by_discovery(
        self, mock_get, mock_post, _mock_decrypt
    ):
        mock_get.return_value = self._google_manager_discovery_response({"resourceNames": ["customers/7973229750"]})
        mock_post.return_value = self._google_manager_discovery_response({"results": []})
        credential = type("Credential", (), {"encrypted_access_token": "encrypted"})()

        self.assertEqual(provider_for("google").list_ad_accounts(credential), [])


@skipUnlessDBFeature("has_select_for_update")
class OAuthStateConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def test_concurrent_duplicate_callback_consumes_state_once(self):
        user = get_user_model().objects.create_user(
            username="oauth-concurrency-user",
            email="oauth-concurrency@example.com",
            password="testpass123",
        )
        identity = AdvertiserIdentity.objects.create(
            owner_type=AdvertiserIdentity.OWNER_PLATFORM,
            user=user,
            display_name="OAuth concurrency advertiser",
        )
        oauth_state = AdvertisingOAuthState.objects.create(
            provider="google",
            state="concurrent-state-value",
            user=user,
            advertiser_identity=identity,
            session_key="",
            expires_at=timezone.now() + timedelta(minutes=5),
            redirect_uri="https://example.test/callback/",
        )
        barrier = __import__("threading").Barrier(2)

        def consume():
            close_old_connections()
            try:
                thread_user = get_user_model().objects.get(pk=user.pk)
                request = SimpleNamespace(
                    user=thread_user,
                    session=SimpleNamespace(session_key=""),
                )
                barrier.wait(timeout=5)
                validate_oauth_state(request, "google", oauth_state.state)
                return "consumed"
            except ProviderAuthorizationError as exc:
                return str(exc)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = (executor.submit(consume), executor.submit(consume))
            outcomes = sorted(future.result() for future in futures)

        self.assertEqual(outcomes, ["consumed", "state_reused"])
        oauth_state.refresh_from_db()
        self.assertIsNotNone(oauth_state.used_at)
        self.assertEqual(
            AdvertisingConnectionAuditLog.objects.filter(
                event_type=AdvertisingConnectionAuditLog.EVENT_CALLBACK_ACCEPTED,
                advertiser_identity=identity,
            ).count(),
            1,
        )
