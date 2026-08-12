import json
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from ads.models import AdCampaign, AdCreative
from installers.models import (
    ServiceCategory,
    ServicePortfolio,
    ServiceProjectMedia,
    ServiceProviderProfile,
)
from products.models import Category, Product, ProductVideo, VideoCommerceEvent


class VideoCommerceFeedTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.vendor = User.objects.create_user(
            email="video-feed-vendor@example.com",
            username="video-feed-vendor",
            password="test-password",
            user_type="vendor",
        )
        self.category = Category.objects.create(
            name="Video Commerce Test",
            slug="video-commerce-test",
            is_active=True,
        )
        self.products = []
        for index in range(3):
            product = Product.objects.create(
                sku=f"VIDEO-FEED-{index}",
                name=f"Video Feed Product {index}",
                slug=f"video-feed-product-{index}",
                description="An approved video-commerce product.",
                category=self.category,
                vendor=self.vendor,
                price=Decimal("100000.00") + index,
                stock_quantity=5,
                is_active=True,
                approval_status="approved",
            )
            self.products.append(product)
            ProductVideo.objects.create(
                product=product,
                title=f"Product demo {index}",
                source="youtube",
                youtube_url=f"https://www.youtube.com/watch?v=feedVideo{index}",
                moderation_status="approved",
                is_active=True,
            )

        ProductVideo.objects.create(
            product=self.products[0],
            title="A second clip for the same product",
            source="youtube",
            youtube_url="https://www.youtube.com/watch?v=duplicateProduct",
            moderation_status="approved",
            is_active=True,
        )
        self.pending_video = ProductVideo.objects.create(
            product=self.products[1],
            title="Pending seller clip",
            source="youtube",
            youtube_url="https://www.youtube.com/watch?v=pendingVideo",
            moderation_status="pending",
            is_active=True,
        )

        provider_user = User.objects.create_user(
            email="video-feed-provider@example.com",
            username="video-feed-provider",
            password="test-password",
        )
        self.provider = ServiceProviderProfile.objects.create(
            user=provider_user,
            business_name="Verified Installation Partner",
            contact_person="Project Lead",
            provider_type="installer",
            phone_number="+2348000000099",
            email="video-feed-provider@example.com",
            country="Nigeria",
            state="Lagos",
            city="Ikeja",
            address="1 Commerce Road",
            description="Approved professional installation services.",
            verification_status=ServiceProviderProfile.STATUS_APPROVED,
            subscription_status="active",
            subscription_plan="Plus",
            is_active=True,
        )
        service_category = ServiceCategory.objects.create(
            name="Video Feed Installation",
            description="Installation test category.",
        )
        self.project = ServicePortfolio.objects.create(
            provider=self.provider,
            title="Approved Video Installation",
            short_summary="A verified installation walkthrough.",
            description="Professional installation proof.",
            service_category=service_category,
            city="Ikeja",
            state="Lagos",
            country="Nigeria",
            completed_at=date.today(),
            project_result="Installation completed.",
            approval_status=ServicePortfolio.STATUS_APPROVED,
            is_active=True,
        )
        self.service_video = ServiceProjectMedia.objects.create(
            project=self.project,
            media_type=ServiceProjectMedia.TYPE_VIDEO,
            external_video_url="https://www.youtube.com/watch?v=serviceVideo1",
            caption="Professional installation walkthrough",
            approval_status=ServiceProjectMedia.STATUS_APPROVED,
            is_active=True,
        )
        self.pending_service_video = ServiceProjectMedia.objects.create(
            project=self.project,
            media_type=ServiceProjectMedia.TYPE_VIDEO,
            external_video_url="https://www.youtube.com/watch?v=servicePending1",
            caption="Pending service walkthrough",
            approval_status=ServiceProjectMedia.STATUS_PENDING,
            is_active=True,
        )

        self.campaign = AdCampaign.objects.create(
            name="Approved Video Campaign",
            campaign_type="video",
            status="active",
            approved=True,
            approved_by=self.vendor,
            start_date=timezone.now(),
        )
        self.sponsored_video = AdCreative.objects.create(
            campaign=self.campaign,
            name="Sponsored marketplace video",
            creative_type="video",
            headline="Sponsored product demo",
            video_url="https://www.youtube.com/watch?v=sponsoredVideo1",
            clickthrough_url="https://example.com/sponsored-product",
            is_active=True,
        )

    def test_feed_returns_real_unique_moderated_sources(self):
        response = self.client.get(
            reverse("products:video_commerce_feed_api"),
            {"product": self.products[0].slug, "limit": 12},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        cards = payload["results"]

        self.assertEqual(len(cards), 5)
        self.assertEqual(
            {card["content_type"] for card in cards},
            {"product", "service", "sponsored"},
        )
        self.assertEqual(
            len([card for card in cards if card["content_type"] == "product"]),
            3,
        )
        self.assertNotIn(
            f"product:{self.pending_video.pk}",
            {card["id"] for card in cards},
        )
        self.assertNotIn(
            f"service:{self.pending_service_video.pk}",
            {card["id"] for card in cards},
        )

    def test_feed_does_not_duplicate_cards_to_fill_a_limit(self):
        response = self.client.get(
            reverse("products:video_commerce_feed_api"),
            {
                "limit": 24,
                "include_services": "false",
                "include_sponsored": "false",
            },
        )
        cards = response.json()["results"]
        self.assertEqual(len(cards), 3)
        self.assertEqual(len({card["product"]["id"] for card in cards}), 3)

    def test_event_api_deduplicates_per_client_session(self):
        video = ProductVideo.objects.filter(
            product=self.products[0],
            moderation_status="approved",
        ).first()
        payload = {
            "session_id": "mobile-test-session",
            "content_type": "product",
            "source_id": video.pk,
            "product_id": self.products[0].pk,
            "event_type": "video_impression",
            "position": 1,
            "context": "customer_mobile_product_detail",
        }
        url = reverse("products:video_commerce_event_api")
        first = self.client.post(url, data=json.dumps(payload), content_type="application/json")
        second = self.client.post(url, data=json.dumps(payload), content_type="application/json")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(first.json()["created"])
        self.assertFalse(second.json()["created"])
        self.assertEqual(VideoCommerceEvent.objects.count(), 1)
        video.refresh_from_db()
        self.assertEqual(video.views_count, 1)
