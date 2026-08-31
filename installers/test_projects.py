from datetime import date
from datetime import timedelta
from io import BytesIO
from pathlib import Path
import shutil
import subprocess
import tempfile
from unittest import skipUnless
from unittest.mock import patch
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from core.youtube_service import YouTubeUploadError
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
    resolve_project_primary_video,
)
from .project_video_processing import (
    ensure_legacy_project_video_media,
    process_project_video,
)
from social_publishing.models import (
    SocialAccount,
    SocialConnectionStatus,
    SocialPlatform,
    SocialPublication,
    TemporaryVideoLease,
)
from staff_mobile.models import StaffMobileToken


User = get_user_model()


def tiny_gif(name="project.gif"):
    return SimpleUploadedFile(
        name,
        b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04"
        b"\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;",
        content_type="image/gif",
    )


def tiny_mp4(name="project.mp4"):
    return SimpleUploadedFile(
        name,
        b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom",
        content_type="video/mp4",
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

    def test_provider_media_api_returns_created_video_id_for_instagram_ui(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse(
                "provider_api:provider_project_media",
                args=[self.project.id],
            ),
            {
                "media_type": ServiceProjectMedia.TYPE_VIDEO,
                "caption": "Instagram-ready proof video",
                "video": tiny_mp4(),
            },
            HTTP_ACCEPT="application/json",
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload["media"][0]["media_type"], ServiceProjectMedia.TYPE_VIDEO)
        self.assertTrue(payload["media"][0]["id"])

    def test_provider_media_api_returns_safe_owned_facebook_publication_status(self):
        media = ServiceProjectMedia.objects.create(
            project=self.project,
            media_type=ServiceProjectMedia.TYPE_VIDEO,
            caption="Facebook-ready project video",
            external_video_url="https://www.youtube.com/watch?v=provider-facebook-status",
        )
        account = SocialAccount.objects.create(
            user=self.user,
            owner_role="provider",
            platform=SocialPlatform.FACEBOOK,
            status=SocialConnectionStatus.CONNECTED,
            external_account_id="provider-page-1",
            access_token_encrypted="encrypted-provider-page-token",
        )
        SocialPublication.objects.create(
            owner_user=self.user,
            owner_role="provider",
            social_account=account,
            platform=SocialPlatform.FACEBOOK,
            content_object=media,
            status="pending",
            attempt_count=1,
        )
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("provider_api:provider_project_media", args=[self.project.id]),
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(response.status_code, 200)
        returned = next(item for item in response.json()["media"] if item["id"] == media.id)
        self.assertEqual(returned["facebook_publication"]["status"], "pending")
        self.assertNotIn("access_token", str(returned["facebook_publication"]).lower())

    @patch("installers.project_api.youtube_upload_video")
    def test_provider_mobile_video_uses_youtube_primary_host_when_selected(self, youtube_upload):
        youtube_upload.return_value = {
            "id": "provider-youtube-id",
            "url": "https://www.youtube.com/watch?v=provider-youtube-id",
        }
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("provider_api:provider_project_media", args=[self.project.id]),
            {
                "media_type": ServiceProjectMedia.TYPE_VIDEO,
                "caption": "Permanent YouTube project video",
                "publish_youtube": "true",
                "video": tiny_mp4("youtube-project.mp4"),
            },
            HTTP_ACCEPT="application/json",
        )

        self.assertEqual(response.status_code, 201, response.content)
        media = ServiceProjectMedia.objects.get(pk=response.json()["media"][0]["id"])
        self.assertEqual(media.external_video_url, youtube_upload.return_value["url"])
        self.assertFalse(media.video)

    @patch("installers.project_api.youtube_upload_video")
    def test_provider_mobile_youtube_failures_are_safe_and_create_no_media_or_social_intent(self, youtube_upload):
        cases = (
            ("validation", "youtube_validation_failed", "The selected video could not be prepared for YouTube."),
            ("token_refresh", "youtube_token_refresh_failed", "Could not refresh the Arolana YouTube connection."),
            ("upload_initialization", "youtube_upload_init_failed", "Could not start the YouTube upload."),
            ("video_upload", "youtube_upload_failed", "YouTube could not complete the video upload."),
            ("unknown", "youtube_unknown_error", "YouTube upload failed. Please try again."),
        )
        session = StaffMobileToken.issue("provider", user=self.user)
        for index, (stage, code, message) in enumerate(cases):
            with self.subTest(stage=stage):
                youtube_upload.side_effect = (
                    RuntimeError("Authorization: Bearer provider-secret")
                    if stage == "unknown"
                    else YouTubeUploadError(message, stage=stage, code=code, http_status=500)
                )
                response = self.client.post(
                    reverse("provider_api:provider_project_media", args=[self.project.id]),
                    {
                        "media_type": ServiceProjectMedia.TYPE_VIDEO,
                        "publish_youtube": "true",
                        "publish_instagram": "true",
                        "video": tiny_mp4(f"youtube-failure-{index}.mp4"),
                    },
                    HTTP_AUTHORIZATION=f"Bearer {session.token}",
                    HTTP_ACCEPT="application/json",
                )
                self.assertEqual(response.status_code, 400, response.content)
                payload = response.json()
                self.assertEqual(payload["youtube_upload_requested"], True)
                self.assertEqual(payload["youtube_upload_succeeded"], False)
                self.assertEqual(payload["youtube_error"], {"stage": stage, "code": code, "message": message})
                self.assertNotIn("provider-secret", response.content.decode())
                self.assertFalse(ServiceProjectMedia.objects.filter(external_video_url__icontains="youtube-failure").exists())
                self.assertFalse(SocialPublication.objects.exists())

    @patch("installers.views.youtube_upload_video")
    def test_provider_web_video_uses_youtube_primary_host_when_selected(self, youtube_upload):
        youtube_upload.return_value = {
            "id": "provider-web-youtube-id",
            "url": "https://www.youtube.com/watch?v=provider-web-youtube-id",
        }
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("provider_workspace:project_media", args=[self.project.id])
            + "?status=connected&platform=instagram",
            {
                "action": "upload",
                "stage": ServiceProjectMedia.STAGE_GENERAL,
                "caption": "Web permanent YouTube project video",
                "publish_youtube": "true",
                "files": tiny_mp4("web-youtube-project.mp4"),
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            HTTP_ACCEPT="application/json",
        )

        self.assertEqual(response.status_code, 201, response.content)
        media = ServiceProjectMedia.objects.get(pk=response.json()["media"][0]["id"])
        self.assertEqual(media.external_video_url, youtube_upload.return_value["url"])
        self.assertFalse(media.video)

    def test_provider_workspace_ajax_upload_returns_created_video_id_for_instagram_ui(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse(
                "provider_workspace:project_media",
                args=[self.project.id],
            ),
            {
                "action": "upload",
                "stage": ServiceProjectMedia.STAGE_GENERAL,
                "caption": "Instagram-ready workspace video",
                "files": tiny_mp4("workspace-project.mp4"),
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            HTTP_ACCEPT="application/json",
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["media"][0]["media_type"], ServiceProjectMedia.TYPE_VIDEO)
        self.assertTrue(payload["media"][0]["id"])

    def _instagram_account_and_lease(self, suffix):
        SocialAccount.objects.create(
            user=self.user,
            owner_role="provider",
            platform=SocialPlatform.INSTAGRAM,
            status=SocialConnectionStatus.CONNECTED,
            external_account_id=f"provider-instagram-{suffix}",
            access_token_encrypted="encrypted-test-token",
        )
        return TemporaryVideoLease.objects.create(
            owner_user=self.user,
            owner_role="provider",
            storage_key=f"provider-intents/{suffix}.mp4",
            original_filename=f"{suffix}.mp4",
            expires_at=timezone.now() + timedelta(days=1),
        )

    @override_settings(
        SOCIAL_PUBLISHING_ENABLED=True,
        SOCIAL_PUBLISHING_INSTAGRAM_ENABLED=True,
    )
    @patch("social_publishing.publisher.stage_video_for_social")
    @patch("social_publishing.publisher.social_publishing_access")
    @patch("installers.views.youtube_upload_video")
    def test_provider_web_primary_upload_creates_instagram_intent(
        self, youtube_upload, publishing_access, stage_video
    ):
        lease = self._instagram_account_and_lease("web")
        publishing_access.return_value = SimpleNamespace(allowed=True, reason="")

        def consume_youtube(upload, **_kwargs):
            upload.read()
            return {"id": "provider-web", "url": "https://youtu.be/provider-web"}

        youtube_upload.side_effect = consume_youtube
        stage_video.side_effect = lambda **kwargs: (
            self.assertEqual(kwargs["uploaded_file"].tell(), 0) or lease
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("provider_workspace:project_media", args=[self.project.id]),
            {
                "action": "upload",
                "stage": ServiceProjectMedia.STAGE_GENERAL,
                "publish_youtube": "true",
                "publish_instagram": "true",
                "instagram_caption": "Provider web Reel",
                "instagram_share_to_feed": "true",
                "files": tiny_mp4("provider-web-intent.mp4"),
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            HTTP_ACCEPT="application/json",
        )

        self.assertEqual(response.status_code, 201, response.content)
        media_id = response.json()["media"][0]["id"]
        publication = SocialPublication.objects.get(
            owner_role="provider", content_type__app_label="installers",
            content_type__model="serviceprojectmedia", object_id=media_id,
        )
        self.assertEqual(publication.status, "pending")
        self.assertEqual(publication.deferred_video_lease, lease)
        self.assertEqual(response.json()["instagram_publication"]["publication_id"], publication.id)
        self.assertEqual(youtube_upload.call_count, 1)
        self.assertEqual(stage_video.call_count, 1)

    @override_settings(
        SOCIAL_PUBLISHING_ENABLED=True,
        SOCIAL_PUBLISHING_INSTAGRAM_ENABLED=True,
    )
    @patch("social_publishing.publisher.stage_video_for_social")
    @patch("social_publishing.publisher.social_publishing_access")
    @patch("installers.project_api.youtube_upload_video")
    def test_provider_staff_mobile_primary_upload_creates_same_instagram_intent(
        self, youtube_upload, publishing_access, stage_video
    ):
        lease = self._instagram_account_and_lease("mobile")
        publishing_access.return_value = SimpleNamespace(allowed=True, reason="")
        youtube_upload.side_effect = lambda upload, **_kwargs: (
            upload.read() and {"id": "provider-mobile", "url": "https://youtu.be/provider-mobile"}
        )
        stage_video.return_value = lease
        session = StaffMobileToken.issue("provider", user=self.user)

        response = self.client.post(
            reverse("provider_api:provider_project_media", args=[self.project.id]),
            {
                "media_type": ServiceProjectMedia.TYPE_VIDEO,
                "publish_youtube": "true",
                "publish_instagram": "true",
                "instagram_caption": "Provider app Reel",
                "instagram_share_to_feed": "false",
                "video": tiny_mp4("provider-mobile-intent.mp4"),
            },
            HTTP_AUTHORIZATION=f"Bearer {session.token}",
            HTTP_ACCEPT="application/json",
        )

        self.assertEqual(response.status_code, 201, response.content)
        media_id = response.json()["media"][0]["id"]
        publication = SocialPublication.objects.get(
            owner_role="provider", content_type__app_label="installers",
            content_type__model="serviceprojectmedia", object_id=media_id,
        )
        self.assertEqual(publication.status, "pending")
        self.assertFalse(publication.request_metadata["share_to_feed"])
        self.assertEqual(response.json()["instagram_publication"]["publication_id"], publication.id)

    def test_provider_media_page_separates_video_source_from_destinations(self):
        self.client.force_login(self.user)

        response = self.client.get(
            reverse(
                "provider_workspace:project_media",
                args=[self.project.id],
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Video source — external URL")
        self.assertContains(response, "Publishing Destinations")
        self.assertContains(response, "YouTube")
        self.assertContains(response, "Instagram")
        self.assertContains(response, "Connect Instagram")

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

    def test_legacy_mov_is_normalized_as_pending_without_exposing_raw_source(self):
        self.project.local_video = SimpleUploadedFile(
            "legacy-walkthrough.mov",
            b"legacy-mov-placeholder",
            content_type="video/quicktime",
        )
        self.project.video_source = "upload"
        self.project.save(update_fields=["local_video", "video_source", "updated_at"])

        response = self.client.get(
            reverse("projects_api:detail", args=[self.project.slug])
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()["project"]
        self.assertTrue(payload["has_video"])
        self.assertEqual(payload["video_url"], "")
        self.assertEqual(payload["primary_video"]["processing_status"], "pending")
        self.assertEqual(payload["primary_video"]["mime_type"], "video/quicktime")
        self.assertFalse(payload["primary_video"]["is_playable"])

        page = self.client.get(self.project.get_absolute_url())
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Preparing project video")
        self.assertContains(page, "Back to projects")
        self.assertNotContains(page, "legacy-walkthrough.mov")
        self.assertNotContains(page, "<source")

    def test_project_detail_includes_responsive_gallery_and_lightbox_controls(self):
        for name, stage in (
            ("portrait.gif", ServiceProjectMedia.STAGE_BEFORE),
            ("landscape.gif", ServiceProjectMedia.STAGE_REPAIR_PROCESS),
            ("square.gif", ServiceProjectMedia.STAGE_FINAL_RESULT),
        ):
            ServiceProjectMedia.objects.create(
                project=self.project,
                media_type=ServiceProjectMedia.TYPE_IMAGE,
                stage=stage,
                image=tiny_gif(name),
                approval_status=ServiceProjectMedia.STATUS_APPROVED,
            )

        page = self.client.get(self.project.get_absolute_url())

        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'class="project-media-grid"', count=3)
        self.assertContains(
            page,
            'loading="lazy" decoding="async" width="720" height="540" '
            "data-project-gallery-image></span>",
            count=3,
        )
        self.assertContains(page, "data-project-lightbox-prev")
        self.assertContains(page, "data-project-lightbox-next")
        self.assertContains(page, 'id="project-lightbox-counter"')
        self.assertContains(page, "-webkit-line-clamp:4")
        self.assertContains(
            page,
            "scroll-snap-type:x mandatory",
        )
        self.assertContains(page, "project-media-card--image")
        self.assertContains(page, "data-project-video-open")
        self.assertContains(page, "video.load();armTimeout();")
        self.assertContains(page, "if(video.readyState>=1)ready();else armTimeout();")

    def test_processed_project_video_uses_streaming_route_with_byte_ranges(self):
        media = ServiceProjectMedia.objects.create(
            project=self.project,
            media_type=ServiceProjectMedia.TYPE_VIDEO,
            stage=ServiceProjectMedia.STAGE_WALKTHROUGH,
            processed_video=SimpleUploadedFile(
                "processed-walkthrough.mp4",
                b"0123456789",
                content_type="video/mp4",
            ),
            approval_status=ServiceProjectMedia.STATUS_APPROVED,
            processing_status=ServiceProjectMedia.PROCESSING_COMPLETED,
        )

        detail = self.client.get(
            reverse("projects_api:detail", args=[self.project.slug])
        )
        video_url = detail.json()["project"]["primary_video"]["video_url"]
        self.assertIn("/stream-media/", video_url)

        stream = self.client.get(
            reverse(
                "stream_public_media",
                kwargs={"path": media.processed_video.name},
            ),
            HTTP_RANGE="bytes=0-3",
        )
        self.assertEqual(stream.status_code, 206)
        self.assertEqual(stream["Accept-Ranges"], "bytes")
        self.assertEqual(stream["Content-Range"], "bytes 0-3/10")
        self.assertEqual(b"".join(stream.streaming_content), b"0123")

    def test_streaming_route_redirects_to_uncached_signed_object_url(self):
        stream_path = (
            "installers/projects/videos/processed/"
            "signed-walkthrough.mp4"
        )
        signed_url = "https://storage.example/video.mp4?signature=test"

        with patch(
            "arolana_config.urls.default_storage.url",
            return_value=signed_url,
        ):
            response = self.client.get(
                reverse(
                    "stream_public_media",
                    kwargs={"path": stream_path},
                )
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], signed_url)
        self.assertEqual(
            response["Cache-Control"],
            "private, no-store, max-age=0",
        )

    def test_legacy_video_repair_is_idempotent_and_queues_conversion(self):
        self.project.local_video = SimpleUploadedFile(
            "repair-me.mov",
            b"legacy-mov-placeholder",
            content_type="video/quicktime",
        )
        self.project.video_source = "upload"
        self.project.save(update_fields=["local_video", "video_source", "updated_at"])

        self.assertEqual(ensure_legacy_project_video_media(), 1)
        self.assertEqual(ensure_legacy_project_video_media(), 0)
        media = self.project.media_items.get(media_type=ServiceProjectMedia.TYPE_VIDEO)
        self.assertEqual(media.processing_status, ServiceProjectMedia.PROCESSING_PENDING)
        self.assertEqual(media.approval_status, ServiceProjectMedia.STATUS_APPROVED)

    def test_active_video_job_cannot_be_claimed_by_a_second_worker(self):
        media = ServiceProjectMedia.objects.create(
            project=self.project,
            media_type=ServiceProjectMedia.TYPE_VIDEO,
            stage=ServiceProjectMedia.STAGE_WALKTHROUGH,
            video=SimpleUploadedFile(
                "claimed.mov",
                b"legacy-mov-placeholder",
                content_type="video/quicktime",
            ),
            approval_status=ServiceProjectMedia.STATUS_APPROVED,
        )
        ServiceProjectMedia.objects.filter(pk=media.pk).update(
            processing_status=ServiceProjectMedia.PROCESSING_ACTIVE,
        )

        with patch("installers.project_video_processing._binary") as binary:
            self.assertFalse(process_project_video(media.pk))

        binary.assert_not_called()
        media.refresh_from_db()
        self.assertEqual(
            media.processing_status,
            ServiceProjectMedia.PROCESSING_ACTIVE,
        )

    def test_project_copy_renders_escaped_semantic_bullets(self):
        self.project.description = (
            "A documented professional installation.\n\n"
            "* Professional conference room design\n"
            "* <script>unsafe</script>"
        )
        self.project.save(update_fields=["description", "updated_at"])

        response = self.client.get(self.project.get_absolute_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<ul class="project-copy-list">')
        self.assertContains(response, "Professional conference room design")
        self.assertContains(response, "&lt;script&gt;unsafe&lt;/script&gt;")
        self.assertNotContains(response, "* Professional conference room design")

    @skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is required")
    def test_mov_processing_creates_streaming_mp4_payload(self):
        with tempfile.TemporaryDirectory(prefix="arolana-project-test-source-") as root:
            source_path = Path(root) / "source.mov"
            subprocess.run(
                [
                    shutil.which("ffmpeg"),
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=blue:s=160x90:d=0.3",
                    "-c:v",
                    "mpeg4",
                    "-pix_fmt",
                    "yuv420p",
                    str(source_path),
                ],
                check=True,
                timeout=30,
            )
            media = ServiceProjectMedia.objects.create(
                project=self.project,
                media_type=ServiceProjectMedia.TYPE_VIDEO,
                stage=ServiceProjectMedia.STAGE_WALKTHROUGH,
                video=SimpleUploadedFile(
                    "source.mov",
                    source_path.read_bytes(),
                    content_type="video/quicktime",
                ),
                approval_status=ServiceProjectMedia.STATUS_APPROVED,
            )

        self.assertTrue(process_project_video(media.id))
        media.refresh_from_db()
        primary_video = resolve_project_primary_video(
            ServicePortfolio.objects.public().optimized().get(pk=self.project.pk)
        )
        self.assertEqual(media.processing_status, ServiceProjectMedia.PROCESSING_COMPLETED)
        self.assertTrue(media.processed_video.name.endswith(".mp4"))
        self.assertEqual(primary_video.mime_type, "video/mp4")
        self.assertTrue(primary_video.video_url.endswith(".mp4"))

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

    @patch("social_publishing.publisher.release_pending_facebook_publications")
    def test_staff_mobile_media_approval_uses_shared_deferred_release_hook(self, release_facebook):
        staff = User.objects.create_superuser(
            username="mobile-media-admin",
            email="mobile-media-admin@example.com",
            password="pass12345",
        )
        media = ServiceProjectMedia.objects.create(
            project=self.project,
            media_type=ServiceProjectMedia.TYPE_VIDEO,
            external_video_url="https://www.youtube.com/watch?v=staff-media-release",
            approval_status=ServiceProjectMedia.STATUS_PENDING,
        )
        self.client.force_login(staff)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse(
                    "staff_mobile:staff_projects_api:staff_project_media_moderate",
                    args=[self.project.id, media.id],
                ),
                {"status": ServiceProjectMedia.STATUS_APPROVED},
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 200, response.content)
        media.refresh_from_db()
        self.assertEqual(media.approval_status, ServiceProjectMedia.STATUS_APPROVED)
        release_facebook.assert_called_once()

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
