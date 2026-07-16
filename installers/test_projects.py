from datetime import date
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .models import (
    ServiceCategory,
    ServiceMarketplaceHomepageSection,
    ServicePortfolio,
    ServiceProjectMedia,
    ServiceProviderProfile,
)
from .project_services import (
    ProjectEntitlementService,
    group_project_gallery_media,
    moderate_project,
)


User = get_user_model()


def tiny_gif(name="project.gif"):
    return SimpleUploadedFile(
        name,
        b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04"
        b"\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;",
        content_type="image/gif",
    )


def distinct_test_image(name="distinct-project.png"):
    """Return proof media that is not a duplicate of the default fixture."""
    output = BytesIO()
    image = Image.new("RGB", (8, 8), "#071A44")
    for coordinate in range(8):
        image.putpixel((coordinate, coordinate), (255, 122, 0))
        image.putpixel((7 - coordinate, coordinate), (0, 102, 204))
    image.save(output, format="PNG")
    return SimpleUploadedFile(
        name,
        output.getvalue(),
        content_type="image/png",
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

    def test_cover_selection_does_not_destroy_media_stage(self):
        before = ServiceProjectMedia.objects.create(
            project=self.project,
            media_type=ServiceProjectMedia.TYPE_IMAGE,
            stage=ServiceProjectMedia.STAGE_BEFORE,
            image=tiny_gif("before.gif"),
            approval_status=ServiceProjectMedia.STATUS_APPROVED,
        )
        final = ServiceProjectMedia.objects.create(
            project=self.project,
            media_type=ServiceProjectMedia.TYPE_IMAGE,
            stage=ServiceProjectMedia.STAGE_FINAL_RESULT,
            image=tiny_gif("final.gif"),
            approval_status=ServiceProjectMedia.STATUS_APPROVED,
        )

        self.assertTrue(before.is_cover)
        self.assertEqual(before.stage, ServiceProjectMedia.STAGE_BEFORE)
        final.is_cover = True
        final.save(update_fields=["is_cover", "is_featured", "updated_at"])
        before.refresh_from_db()
        final.refresh_from_db()

        self.assertFalse(before.is_cover)
        self.assertTrue(final.is_cover)
        self.assertEqual(before.stage, ServiceProjectMedia.STAGE_BEFORE)
        self.assertEqual(final.stage, ServiceProjectMedia.STAGE_FINAL_RESULT)
        self.assertEqual(
            self.project.media_items.filter(is_cover=True).count(),
            1,
        )

    def test_before_and_after_are_optional_and_only_used_stages_are_grouped(self):
        ServiceProjectMedia.objects.create(
            project=self.project,
            media_type=ServiceProjectMedia.TYPE_VIDEO,
            stage=ServiceProjectMedia.STAGE_REPAIR_DIAGNOSIS,
            external_video_url="https://youtu.be/dQw4w9WgXcQ",
            approval_status=ServiceProjectMedia.STATUS_APPROVED,
        )
        ServiceProjectMedia.objects.create(
            project=self.project,
            media_type=ServiceProjectMedia.TYPE_VIDEO,
            stage=ServiceProjectMedia.STAGE_TESTING,
            external_video_url="https://vimeo.com/76979871",
            approval_status=ServiceProjectMedia.STATUS_APPROVED,
        )

        groups = group_project_gallery_media(self.project)
        stages = {group["stage"] for group in groups}
        self.assertEqual(
            stages,
            {
                ServiceProjectMedia.STAGE_REPAIR_DIAGNOSIS,
                ServiceProjectMedia.STAGE_TESTING,
            },
        )
        self.assertNotIn(ServiceProjectMedia.STAGE_BEFORE, stages)
        self.assertNotIn(ServiceProjectMedia.STAGE_AFTER, stages)

    def test_public_api_exposes_only_approved_active_media(self):
        approved = ServiceProjectMedia.objects.create(
            project=self.project,
            media_type=ServiceProjectMedia.TYPE_IMAGE,
            stage=ServiceProjectMedia.STAGE_FINAL_RESULT,
            image=tiny_gif("approved.gif"),
            caption="Approved public proof",
            approval_status=ServiceProjectMedia.STATUS_APPROVED,
        )
        pending = ServiceProjectMedia.objects.create(
            project=self.project,
            media_type=ServiceProjectMedia.TYPE_IMAGE,
            stage=ServiceProjectMedia.STAGE_BEFORE,
            image=tiny_gif("pending.gif"),
            caption="Pending private proof",
            approval_status=ServiceProjectMedia.STATUS_PENDING,
        )

        response = self.client.get(reverse("projects_api:detail", args=[self.project.slug]))
        self.assertEqual(response.status_code, 200)
        media_ids = {item["id"] for item in response.json()["project"]["media"]}
        self.assertIn(approved.id, media_ids)
        self.assertNotIn(pending.id, media_ids)
        self.assertNotContains(response, "Pending private proof")

    def test_project_media_rejects_unsafe_external_video_provider(self):
        media = ServiceProjectMedia(
            project=self.project,
            media_type=ServiceProjectMedia.TYPE_VIDEO,
            stage=ServiceProjectMedia.STAGE_WALKTHROUGH,
            external_video_url="https://example.com/untrusted-video",
        )
        with self.assertRaises(ValidationError):
            media.full_clean()

    def test_provider_cannot_delete_another_provider_media(self):
        other_user = User.objects.create_user("other-media-provider", password="pass12345")
        other_provider = ServiceProviderProfile.objects.create(
            user=other_user,
            business_name="Other Media Provider",
            contact_person="Other",
            provider_type="installer",
            phone_number="+2348000000012",
            email="other-media@example.com",
            country="Nigeria",
            state="Lagos",
            city="Lekki",
            address="12 Other Media Road",
            description="Other media provider.",
            verification_status=ServiceProviderProfile.STATUS_APPROVED,
            is_active=True,
        )
        other_project = ServicePortfolio.objects.create(
            provider=other_provider,
            title="Other Provider Media Project",
        )
        other_media = ServiceProjectMedia.objects.create(
            project=other_project,
            media_type=ServiceProjectMedia.TYPE_IMAGE,
            image=distinct_test_image(),
        )
        self.client.force_login(self.user)

        response = self.client.delete(
            reverse(
                "provider_api:provider_project_media_delete",
                args=[other_project.id, other_media.id],
            )
        )
        self.assertEqual(response.status_code, 404)
        self.assertTrue(ServiceProjectMedia.objects.filter(pk=other_media.id).exists())

    def test_provider_media_reorder_persists_and_resequences_remaining_items(self):
        first = ServiceProjectMedia.objects.create(
            project=self.project,
            media_type=ServiceProjectMedia.TYPE_IMAGE,
            image=tiny_gif("first.gif"),
            display_order=0,
        )
        second = ServiceProjectMedia.objects.create(
            project=self.project,
            media_type=ServiceProjectMedia.TYPE_IMAGE,
            image=tiny_gif("second.gif"),
            display_order=1,
        )
        third = ServiceProjectMedia.objects.create(
            project=self.project,
            media_type=ServiceProjectMedia.TYPE_IMAGE,
            image=tiny_gif("third.gif"),
            display_order=2,
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("provider_api:provider_project_media_reorder", args=[self.project.id]),
            {"media_ids": [third.id, first.id]},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        ordered_ids = list(
            self.project.media_items.order_by("display_order", "id").values_list("id", flat=True)
        )
        self.assertEqual(ordered_ids, [third.id, first.id, second.id])

    def test_public_project_page_renders_video_only_gallery_without_empty_stages(self):
        self.project.image = None
        self.project.save(update_fields=["image", "updated_at"])
        ServiceProjectMedia.objects.create(
            project=self.project,
            media_type=ServiceProjectMedia.TYPE_VIDEO,
            stage=ServiceProjectMedia.STAGE_REPAIR_PROCESS,
            external_video_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            caption="Repair process proof",
            approval_status=ServiceProjectMedia.STATUS_APPROVED,
        )

        response = self.client.get(self.project.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Repair process")
        self.assertContains(response, "youtube.com/embed/dQw4w9WgXcQ")
        self.assertNotContains(response, '<h3 class="text-xl font-black text-[#071A44]">Before</h3>')

    def test_project_video_processing_state_follows_source_format(self):
        mov_media = ServiceProjectMedia.objects.create(
            project=self.project,
            media_type=ServiceProjectMedia.TYPE_VIDEO,
            stage=ServiceProjectMedia.STAGE_WALKTHROUGH,
            video=SimpleUploadedFile(
                "walkthrough.mov",
                b"mov-video-placeholder",
                content_type="video/quicktime",
            ),
        )
        mp4_media = ServiceProjectMedia.objects.create(
            project=self.project,
            media_type=ServiceProjectMedia.TYPE_VIDEO,
            stage=ServiceProjectMedia.STAGE_TESTING,
            video=SimpleUploadedFile(
                "testing.mp4",
                b"mp4-video-placeholder",
                content_type="video/mp4",
            ),
        )

        self.assertEqual(
            mov_media.processing_status,
            ServiceProjectMedia.PROCESSING_PENDING,
        )
        self.assertIsNone(mov_media.playable_video)
        self.assertEqual(
            mp4_media.processing_status,
            ServiceProjectMedia.PROCESSING_NONE,
        )
        self.assertTrue(mp4_media.playable_video)

    def test_replacing_video_source_retires_stale_processed_derivative(self):
        media = ServiceProjectMedia.objects.create(
            project=self.project,
            media_type=ServiceProjectMedia.TYPE_VIDEO,
            video=SimpleUploadedFile(
                "original.mov",
                b"original-video-placeholder",
                content_type="video/quicktime",
            ),
            processed_video=SimpleUploadedFile(
                "original-processed.mp4",
                b"processed-video-placeholder",
                content_type="video/mp4",
            ),
            processing_status=ServiceProjectMedia.PROCESSING_COMPLETED,
        )
        old_processed_name = media.processed_video.name
        old_storage = media.processed_video.storage
        self.assertTrue(old_storage.exists(old_processed_name))

        media.video = SimpleUploadedFile(
            "replacement.mov",
            b"replacement-video-placeholder",
            content_type="video/quicktime",
        )
        media.save()
        media.refresh_from_db()

        self.assertFalse(media.processed_video)
        self.assertEqual(media.video_duration, 0)
        self.assertEqual(
            media.processing_status,
            ServiceProjectMedia.PROCESSING_PENDING,
        )
        self.assertFalse(old_storage.exists(old_processed_name))

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
