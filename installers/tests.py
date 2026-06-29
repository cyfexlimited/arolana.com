from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import ServiceProviderProfile, ServiceReview


User = get_user_model()


class InstallerMarketplaceTests(TestCase):
    def setUp(self):
        self.approved_user = User.objects.create_user(
            username="approved-engineer",
            email="approved@example.com",
            password="pass12345",
        )
        self.pending_user = User.objects.create_user(
            username="pending-engineer",
            email="pending@example.com",
            password="pass12345",
        )
        base = {
            "contact_person": "Engineer",
            "provider_type": "installer",
            "phone_number": "+2348000000000",
            "email": "engineer@example.com",
            "country": "Nigeria",
            "state": "Lagos",
            "city": "Ikeja",
            "address": "1 Arolana Way",
            "description": "Professional installation services.",
        }
        self.approved = ServiceProviderProfile.objects.create(
            user=self.approved_user,
            business_name="Approved Engineering",
            verification_status=ServiceProviderProfile.STATUS_APPROVED,
            is_verified=True,
            **base,
        )
        self.pending = ServiceProviderProfile.objects.create(
            user=self.pending_user,
            business_name="Pending Engineering",
            verification_status=ServiceProviderProfile.STATUS_PENDING,
            is_verified=False,
            **{**base, "email": "pending-provider@example.com"},
        )

    def test_public_api_only_returns_approved_or_verified_active_providers(self):
        response = self.client.get(reverse("installers_api:provider_list"))
        self.assertEqual(response.status_code, 200)
        names = [item["business_name"] for item in response.json()["results"]]
        self.assertIn(self.approved.business_name, names)
        self.assertNotIn(self.pending.business_name, names)

    def test_pending_provider_detail_is_not_public(self):
        response = self.client.get(
            reverse("installers:provider_detail", kwargs={"slug": self.pending.slug})
        )
        self.assertEqual(response.status_code, 404)

    def test_only_approved_reviews_update_public_rating(self):
        customer = User.objects.create_user(
            username="reviewer",
            email="reviewer@example.com",
            password="pass12345",
        )
        ServiceReview.objects.create(
            provider=self.approved,
            customer=customer,
            rating=5,
            comment="Excellent.",
            professionalism_rating=5,
            communication_rating=5,
            quality_rating=5,
            timeliness_rating=5,
            is_approved=False,
        )
        self.approved.refresh_from_db()
        self.assertEqual(self.approved.total_reviews, 0)

        review = self.approved.reviews.first()
        review.is_approved = True
        review.save()
        self.approved.refresh_from_db()
        self.assertEqual(self.approved.total_reviews, 1)
        self.assertEqual(float(self.approved.average_rating), 5.0)
