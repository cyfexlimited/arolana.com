from datetime import date

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import (
    ServiceCategory,
    ServiceMarketplaceHomepageSection,
    ServicePortfolio,
    ServiceProjectMedia,
    ServiceProviderProfile,
)
from .project_services import ProjectEntitlementService, moderate_project


User = get_user_model()


def tiny_gif(name="project.gif"):
    return SimpleUploadedFile(
        name,
        b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04"
        b"\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;",
        content_type="image/gif",
    )


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    MEDIA_ROOT="/tmp/arolana-project-tests",
    SECURE_SSL_REDIRECT=False,
)
class ProjectNetworkTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="project-provider",
            email="projects@example.com",
            password="pass12345",
        )
        self.provider = ServiceProviderProfile.objects.create(
            user=self.user,
            business_name="Project Proof Limited",
            contact_person="Project Lead",
            provider_type="installer",
            phone_number="+2348000000001",
            email="projects@example.com",
            country="Nigeria",
            state="Lagos",
            city="Ikeja",
            address="1 Proof Road",
            description="Verified project delivery.",
            verification_status=ServiceProviderProfile.STATUS_APPROVED,
            subscription_status="active",
            subscription_plan="Plus",
            is_active=True,
        )
        self.category = ServiceCategory.objects.create(
            name="Conference Room Installation",
            description="Professional meeting room installations.",
        )
        self.project = ServicePortfolio.objects.create(
            provider=self.provider,
            title="Twenty Seat Conference Room Installation",
            short_summary="A complete hybrid meeting room deployment in Ikeja.",
            description="A documented professional installation.",
            service_category=self.category,
            city="Ikeja",
            state="Lagos",
            country="Nigeria",
            completed_at=date.today(),
            project_result="The customer can now run reliable hybrid meetings.",
            image=tiny_gif(),
            approval_status=ServicePortfolio.STATUS_APPROVED,
        )

    def test_project_slug_is_unique_and_public_page_is_crawlable(self):
        second = ServicePortfolio.objects.create(
            provider=self.provider,
            title=self.project.title,
            service_category=self.category,
        )
        self.assertNotEqual(self.project.slug, second.slug)
        response = self.client.get(self.project.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.project.title)
        self.assertContains(response, "Request a similar project")

    def test_public_api_hides_drafts_and_returns_approved_project(self):
        ServicePortfolio.objects.create(
            provider=self.provider,
            title="Private Draft Project",
            approval_status=ServicePortfolio.STATUS_DRAFT,
        )
        response = self.client.get(reverse("projects_api:list"))
        self.assertEqual(response.status_code, 200)
        titles = [item["title"] for item in response.json()["results"]]
        self.assertIn(self.project.title, titles)
        self.assertNotIn("Private Draft Project", titles)

    def test_provider_cannot_edit_another_provider_project(self):
        other_user = User.objects.create_user("other-provider", password="pass12345")
        other = ServiceProviderProfile.objects.create(
            user=other_user,
            business_name="Other Provider",
            contact_person="Other",
            provider_type="installer",
            phone_number="+2348000000002",
            email="other@example.com",
            country="Nigeria",
            state="Lagos",
            city="Lekki",
            address="2 Other Road",
            description="Other provider.",
            verification_status=ServiceProviderProfile.STATUS_APPROVED,
        )
        other_project = ServicePortfolio.objects.create(provider=other, title="Other Provider Installation")
        self.client.force_login(self.user)
        response = self.client.patch(
            reverse("provider_api:provider_project_detail", args=[other_project.id]),
            {"title": "Attempted takeover"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)

    def test_entitlement_is_centralized_and_structured(self):
        payload = ProjectEntitlementService(self.provider).payload()
        self.assertTrue(payload["can_create_project"])
        self.assertEqual(payload["project_limit"], 20)
        self.assertIn("max_media_per_project", payload)
        self.assertIn("can_upload_local_video", payload)

    def test_staff_moderation_logs_and_notifies_provider(self):
        staff = User.objects.create_superuser(
            username="project-admin",
            email="admin@example.com",
            password="pass12345",
        )
        self.project.approval_status = ServicePortfolio.STATUS_PENDING
        self.project.save()
        moderate_project(self.project, ServicePortfolio.STATUS_APPROVED, staff, "Strong project evidence.")
        self.project.refresh_from_db()
        self.assertEqual(self.project.approval_status, ServicePortfolio.STATUS_APPROVED)
        self.assertTrue(self.project.moderation_history.filter(actor=staff).exists())
        self.assertTrue(self.user.notifications.filter(metadata__service_project_id=self.project.id).exists())

    def test_request_similar_project_preserves_source_context(self):
        response = self.client.post(
            reverse("projects_api:request_similar_quote", args=[self.project.slug]),
            {
                "name": "Customer",
                "phone": "+2348000000009",
                "email": "customer@example.com",
                "address": "3 Customer Road",
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        quote = self.project.quote_requests.get(pk=response.json()["quote_id"])
        self.assertEqual(quote.provider, self.provider)
        self.assertEqual(quote.category, self.category)

    def test_project_media_uses_same_record_for_web_and_api(self):
        media = ServiceProjectMedia.objects.create(
            project=self.project,
            media_type="after_image",
            image=tiny_gif("after.gif"),
            approval_status=ServiceProjectMedia.STATUS_APPROVED,
        )
        response = self.client.get(reverse("projects_api:detail", args=[self.project.slug]))
        self.assertEqual(response.status_code, 200)
        media_ids = [item["id"] for item in response.json()["project"]["media"]]
        self.assertIn(media.id, media_ids)

    def test_project_category_api_includes_active_categories_before_first_project(self):
        empty_category = ServiceCategory.objects.create(name="New Service Without Projects")
        response = self.client.get(reverse("projects_api:categories"))
        self.assertEqual(response.status_code, 200)
        category_ids = {item["id"] for item in response.json()["categories"]}
        self.assertIn(empty_category.id, category_ids)

    def test_staff_mobile_can_moderate_same_project_record(self):
        staff = User.objects.create_superuser(
            username="mobile-project-admin",
            email="mobile-project-admin@example.com",
            password="pass12345",
        )
        self.project.approval_status = ServicePortfolio.STATUS_PENDING
        self.project.save()
        self.client.force_login(staff)
        response = self.client.post(
            reverse("staff_mobile:staff_projects_api:staff_project_approve", args=[self.project.id]),
            {"notes": "Approved from staff mobile."},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.project.refresh_from_db()
        self.assertEqual(self.project.approval_status, ServicePortfolio.STATUS_APPROVED)
        self.assertTrue(self.project.moderation_history.filter(actor=staff).exists())

    def test_mobile_home_exposes_admin_controlled_projects_section(self):
        ServiceMarketplaceHomepageSection.objects.create(
            title="Services",
            projects_enabled=True,
            projects_title="Real Arolana Projects",
            is_active=True,
        )
        response = self.client.get(reverse("products:mobile_home_api"))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["projects_section"]["enabled"])
        self.assertEqual(payload["projects_section"]["title"], "Real Arolana Projects")
        self.assertIn(self.project.id, {item["id"] for item in payload["featured_projects"]})
