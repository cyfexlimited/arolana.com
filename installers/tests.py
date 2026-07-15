from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import (
    ProviderProfileChangeRequest,
    ProviderService,
    ServiceCategory,
    ServicePortfolio,
    ServiceProviderProfile,
    ServiceReview,
)


User = get_user_model()


@override_settings(SECURE_SSL_REDIRECT=False)
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


@override_settings(SECURE_SSL_REDIRECT=False)
class ProviderWorkspaceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="workspace-provider",
            email="workspace@example.com",
            password="pass12345",
        )
        self.provider = ServiceProviderProfile.objects.create(
            user=self.user,
            business_name="Workspace Engineering",
            contact_person="Workspace Lead",
            provider_type="av_engineer",
            phone_number="+2348000000011",
            email="workspace@example.com",
            country="Nigeria",
            state="Lagos",
            city="Ikeja",
            address="11 Workspace Road",
            service_coverage="Lagos and Ogun",
            description="Professional audio visual engineering and installation.",
            years_of_experience=7,
            verification_status=ServiceProviderProfile.STATUS_APPROVED,
            subscription_status="active",
        )
        self.category = ServiceCategory.objects.create(name="AV Installation")
        self.client.force_login(self.user)

    def test_provider_workspace_pages_use_same_provider_profile(self):
        for name in (
            "provider_workspace:dashboard",
            "provider_workspace:profile",
            "provider_workspace:services",
            "provider_workspace:coverage",
            "provider_workspace:kyc",
            "provider_workspace:analytics",
            "provider_workspace:notifications",
            "provider_workspace:settings",
        ):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200, name)
            self.assertContains(response, self.provider.business_name)

    def test_shared_header_exposes_provider_dashboard(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("provider_workspace:dashboard"))
        self.assertContains(response, "Provider Dashboard")

    def test_provider_dashboard_redirects_unregistered_user_to_profile_setup(self):
        self.provider.delete()

        response = self.client.get(reverse("provider_workspace:dashboard"))

        self.assertRedirects(response, reverse("installers:register"))
        homepage = self.client.get("/")
        self.assertContains(homepage, "Set Up Provider Profile")

    def test_completion_tracks_services_projects_kyc_and_hours(self):
        initial = self.provider.profile_completion_percent
        ProviderService.objects.create(
            provider=self.provider,
            category=self.category,
            service_name="Meeting room installation",
        )
        ServicePortfolio.objects.create(
            provider=self.provider,
            title="Completed Boardroom Installation",
        )
        self.provider.business_hours_data = {
            "monday": {"enabled": True, "open": "09:00", "close": "17:00"}
        }
        self.provider.kyc_status = ServiceProviderProfile.KYC_PENDING
        self.provider.save(update_fields=["business_hours_data", "kyc_status", "updated_at"])
        self.assertGreater(self.provider.profile_completion_percent, initial)
        missing_keys = {item["key"] for item in self.provider.profile_missing_steps}
        self.assertNotIn("services", missing_keys)
        self.assertNotIn("project", missing_keys)
        self.assertNotIn("kyc", missing_keys)
        self.assertNotIn("hours", missing_keys)

    def test_service_delete_deactivates_and_preserves_record(self):
        service = ProviderService.objects.create(
            provider=self.provider,
            category=self.category,
            service_name="Projector setup",
        )
        response = self.client.delete(
            reverse("provider_api:provider_service_detail", args=[service.id])
        )
        self.assertEqual(response.status_code, 200)
        service.refresh_from_db()
        self.assertFalse(service.is_active)

    def test_approved_sensitive_profile_update_creates_change_request(self):
        response = self.client.patch(
            reverse("provider_api:provider_profile"),
            {"business_name": "Updated Workspace Engineering"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.provider.refresh_from_db()
        self.assertEqual(self.provider.business_name, "Workspace Engineering")
        self.assertTrue(
            ProviderProfileChangeRequest.objects.filter(
                provider=self.provider,
                status=ProviderProfileChangeRequest.STATUS_PENDING,
            ).exists()
        )

    def test_dashboard_api_exposes_workspace_stats_and_entitlements(self):
        ProviderService.objects.create(
            provider=self.provider,
            category=self.category,
            service_name="Display installation",
        )
        response = self.client.get(reverse("provider_api:provider_dashboard"))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["cards"]["active_services"], 1)
        self.assertIn("missing_steps", payload["profile_completion"])
        self.assertIn("max_project_media", payload["entitlements"])
