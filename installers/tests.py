from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .forms import ProviderServiceForm
from .models import (
    ProviderProfileChangeRequest,
    ProviderService,
    ServiceCategory,
    ServicePortfolio,
    ServiceProviderProfile,
    ServiceReview,
)
from .serializers import ProviderServiceSerializer
from .service_offerings import ProviderServicePolicy


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

    def test_category_count_includes_approved_provider_without_verified_badge(self):
        category = ServiceCategory.objects.create(name="Meeting Room Installation")
        ProviderService.objects.create(
            provider=self.approved,
            category=category,
            service_name="Conference room installation",
            is_active=True,
        )
        self.approved.refresh_from_db()
        self.assertFalse(self.approved.is_verified)

        response = self.client.get(reverse("installers_api:category_list"))

        self.assertEqual(response.status_code, 200)
        payload = next(item for item in response.json() if item["id"] == category.id)
        self.assertEqual(payload["provider_count"], 1)

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


@override_settings(SECURE_SSL_REDIRECT=False)
class ProviderServiceSystemTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="service-owner",
            email="service-owner@example.com",
            password="pass12345",
        )
        self.other_user = User.objects.create_user(
            username="other-service-owner",
            email="other-service-owner@example.com",
            password="pass12345",
        )
        profile_data = {
            "contact_person": "Service Lead",
            "provider_type": "installer",
            "phone_number": "+2348000000100",
            "email": "services@example.com",
            "country": "Nigeria",
            "state": "Lagos",
            "city": "Ikeja",
            "address": "10 Service Avenue",
            "service_coverage": "Lagos and nearby states",
            "description": "Professional installation and support.",
            "verification_status": ServiceProviderProfile.STATUS_APPROVED,
            "is_verified": True,
            "subscription_status": "active",
        }
        self.provider = ServiceProviderProfile.objects.create(
            user=self.user,
            business_name="Service Systems Limited",
            **profile_data,
        )
        self.other_provider = ServiceProviderProfile.objects.create(
            user=self.other_user,
            business_name="Other Service Systems",
            **{
                **profile_data,
                "phone_number": "+2348000000101",
                "email": "other-services@example.com",
            },
        )
        self.category = ServiceCategory.objects.create(name="Conference Room Services")
        self.service = ProviderService.objects.create(
            provider=self.provider,
            category=self.category,
            service_name="Conference room design and installation",
            short_description="Design, installation, configuration, and handover.",
            description=(
                '<h2>Complete room delivery</h2><p>We install <strong>secure AV systems</strong>.</p>'
                '<ul><li>Design</li><li>Testing</li></ul>'
            ),
            starting_price=Decimal("50000.00"),
        )

    def _unlimited_subscription(self):
        return SimpleNamespace(
            entitlements={},
            display_name="Free / Starter",
            tier="free",
        )

    @patch("installers.service_offerings.get_effective_subscription")
    def test_provider_can_create_service_and_mobile_created_record_is_public_on_web(self, mocked_subscription):
        mocked_subscription.return_value = self._unlimited_subscription()
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("provider_api:provider_services"),
            {
                "category": self.category.id,
                "service_name": "Projector setup and calibration",
                "short_description": "Professional projector setup for offices and schools.",
                "description": "Installation, alignment, testing, and customer handover.",
                "starting_price": "25000",
                "is_active": True,
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        service = ProviderService.objects.get(service_name="Projector setup and calibration")
        self.assertIn("<p>", service.description)
        public_page = self.client.get(self.provider.get_absolute_url())
        self.assertContains(public_page, service.service_name)

    @patch("installers.service_offerings.get_effective_subscription")
    def test_provider_can_edit_activate_and_deactivate_own_service(self, mocked_subscription):
        mocked_subscription.return_value = self._unlimited_subscription()
        self.client.force_login(self.user)
        endpoint = reverse("provider_api:provider_service_detail", args=[self.service.id])
        response = self.client.patch(
            endpoint,
            {"short_description": "Updated concise customer summary."},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.service.refresh_from_db()
        self.assertEqual(self.service.short_description, "Updated concise customer summary.")

        response = self.client.delete(endpoint)
        self.assertEqual(response.status_code, 200)
        self.service.refresh_from_db()
        self.assertFalse(self.service.is_active)

        response = self.client.patch(endpoint, {"is_active": True}, content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        self.service.refresh_from_db()
        self.assertTrue(self.service.is_active)

    def test_provider_cannot_edit_another_providers_service(self):
        self.client.force_login(self.other_user)
        response = self.client.patch(
            reverse("provider_api:provider_service_detail", args=[self.service.id]),
            {"service_name": "Taken over service"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)
        self.service.refresh_from_db()
        self.assertNotEqual(self.service.service_name, "Taken over service")

    def test_inactive_service_is_hidden_from_public_web_and_customer_api(self):
        self.service.is_active = False
        self.service.save(update_fields=["is_active", "updated_at"])
        web_response = self.client.get(self.service.get_absolute_url())
        api_response = self.client.get(
            reverse("installers_api:public_service_detail", args=[self.provider.id, self.service.id])
        )
        provider_response = self.client.get(
            reverse("installers_api:provider_detail", args=[self.provider.id])
        )
        self.assertEqual(web_response.status_code, 404)
        self.assertEqual(api_response.status_code, 404)
        self.assertEqual(provider_response.status_code, 200)
        self.assertEqual(provider_response.json()["services"], [])

    def test_multiple_active_services_all_appear_publicly_without_full_html_in_list(self):
        expected = {self.service.service_name}
        for index in range(1, 8):
            service = ProviderService.objects.create(
                provider=self.provider,
                category=self.category,
                service_name=f"Professional service {index}",
                description=f"<p>Full rich description {index}</p>",
            )
            expected.add(service.service_name)

        web_response = self.client.get(self.provider.get_absolute_url())
        api_response = self.client.get(
            reverse("installers_api:provider_detail", args=[self.provider.id])
        )
        self.assertEqual(api_response.status_code, 200)
        services = api_response.json()["services"]
        self.assertEqual({item["service_name"] for item in services}, expected)
        self.assertEqual(len(services), 8)
        self.assertNotIn("description_html", services[0])
        for name in expected:
            self.assertContains(web_response, name)

    def test_public_detail_api_returns_safe_full_and_plain_descriptions(self):
        response = self.client.get(
            reverse("installers_api:public_service_detail", args=[self.provider.id, self.service.id])
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()["service"]
        for field in (
            "description_html", "description_text", "excerpt", "formatted_starting_price",
            "provider", "absolute_url", "created_at", "updated_at",
        ):
            self.assertIn(field, payload)
        self.assertIn("Complete room delivery", payload["description_text"])
        self.assertIn("50,000", payload["formatted_starting_price"])

    def test_rich_html_is_sanitized_while_safe_formatting_remains(self):
        self.service.description = (
            '<script>alert(1)</script><h2 onclick="bad()">Scope</h2>'
            '<p>Safe <strong>content</strong>.</p>'
            '<a href="javascript:alert(1)" onmouseover="bad()">unsafe link</a>'
            '<ul><li>Testing</li></ul>'
        )
        self.service.save()
        self.service.refresh_from_db()
        self.assertNotIn("script", self.service.description.lower())
        self.assertNotIn("onclick", self.service.description.lower())
        self.assertNotIn("javascript:", self.service.description.lower())
        self.assertIn("<h2>Scope</h2>", self.service.description)
        self.assertIn("<strong>content</strong>", self.service.description)
        self.assertIn("<ul><li>Testing</li></ul>", self.service.description)

    def test_rich_description_generates_clean_excerpt_and_formatted_price(self):
        self.service.short_description = ""
        self.service.save()
        self.assertNotIn("<", self.service.card_excerpt)
        self.assertIn("Complete room delivery", self.service.card_excerpt)
        payload = ProviderServiceSerializer(self.service).data
        self.assertNotIn("<", payload["excerpt"])
        self.assertIn("50,000", payload["formatted_starting_price"])

    def test_form_keeps_entered_values_on_validation_error_and_uses_ckeditor(self):
        form = ProviderServiceForm(
            data={
                "category": self.category.id,
                "service_name": "x",
                "short_description": "My entered summary",
                "description": "My entered description",
                "starting_price": "-1",
                "is_active": True,
            }
        )
        self.assertFalse(form.is_valid())
        self.assertEqual(form.data["short_description"], "My entered summary")
        self.assertEqual(form.fields["description"].widget.__class__.__name__, "CKEditor5Widget")

        self.client.force_login(self.user)
        response = self.client.get(reverse("provider_workspace:services"))
        self.assertContains(response, "django_ckeditor_5")
        self.assertContains(response, "ck-editor-container")

    def test_cache_invalidation_runs_after_service_change(self):
        keys = [
            f"provider-detail:{self.provider.id}",
            f"provider-services:{self.provider.id}",
            "provider-directory:public",
        ]
        cache.set_many({key: "stale" for key in keys})
        self.service.short_description = "Cache-busting update"
        self.service.save()
        self.assertTrue(all(cache.get(key) is None for key in keys))

    @patch("installers.service_offerings.get_effective_subscription")
    def test_missing_service_entitlement_is_unlimited(self, mocked_subscription):
        mocked_subscription.return_value = self._unlimited_subscription()
        access = ProviderServicePolicy(self.provider).can_activate(self.service)
        self.assertTrue(access.allowed)
        self.assertTrue(access.unlimited)
        self.assertEqual(access.limit, -1)

    @patch("installers.service_offerings.get_effective_subscription")
    def test_service_api_query_count_stays_bounded_with_many_services(self, mocked_subscription):
        mocked_subscription.return_value = self._unlimited_subscription()
        for index in range(20):
            category = ServiceCategory.objects.create(name=f"Service category {index}")
            ProviderService.objects.create(
                provider=self.provider,
                category=category,
                service_name=f"Scalable service {index}",
                description="<p>Compact API payload.</p>",
            )
        self.client.force_login(self.user)
        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(reverse("provider_api:provider_services"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["services"]), 21)
        self.assertLessEqual(len(captured), 10, [query["sql"] for query in captured])
