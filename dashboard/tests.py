from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.conf import settings
from django.urls import reverse

from products.models import Category, Product, ProductVideo
from social_publishing.models import SocialPublication
from vendors.models import VendorProfile

User = get_user_model()


class VendorAddProductVideoPublishingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="vendor-create-video@arolana.com",
            username="vendor-create-video",
            password="StrongPassword123!",
            user_type="vendor",
        )
        self.profile = VendorProfile.objects.create(
            user=self.user,
            store_name="Creation Video Vendor",
            store_slug="creation-video-vendor",
            description="Video creation tests",
            approval_status="approved",
            is_verified=True,
            is_active=True,
            address_line_1="1 Video Way",
            city="Ikeja",
            state="Lagos",
            country="Nigeria",
        )
        self.category = Category.objects.create(name="Creation Video", slug="creation-video")
        self.client.force_login(self.user)

    @patch("dashboard.views._inspect_vendor_product_uploads", return_value=[])
    @patch("dashboard.views.require_verified_kyc", return_value=None)
    @patch("dashboard.views.youtube_upload_video")
    @patch("dashboard.views.user_subscription_limits")
    def test_ajax_creation_returns_primary_product_video_id(
        self,
        subscription_limits,
        youtube_upload,
        _kyc,
        _uploads,
    ):
        subscription_limits.return_value = {
            "max_products": -1,
            "featured_products": -1,
            "can_upload_video": True,
            "can_upload_pdf": True,
            "max_images_per_product": 10,
            "max_variants_per_product": 10,
        }
        youtube_upload.return_value = {
            "id": "web-create-video-id",
            "url": "https://www.youtube.com/watch?v=web-create-video-id",
        }

        for suffix, headers in (
            ("xhr", {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest", "HTTP_ACCEPT": "application/json"}),
            ("accept-only", {"HTTP_ACCEPT": "application/json"}),
        ):
            with self.subTest(transport=suffix):
                response = self.client.post(
                    "/dashboard/vendor/product/add/",
                    {
                        "product_mode": "new_product",
                        "name": f"Web Product With Video {suffix}",
                        "description": "Created with a permanent YouTube video.",
                        "price": Decimal("100.00"),
                        "stock_quantity": "2",
                        "category": str(self.category.id),
                        "condition": "brand_new",
                        "video_type": "local",
                        "local_video": SimpleUploadedFile(
                            f"web-create-{suffix}.mp4",
                            b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom",
                            content_type="video/mp4",
                        ),
                    },
                    **headers,
                )

                self.assertEqual(response.status_code, 201, response.content)
                payload = response.json()
                self.assertTrue(payload["youtube_upload_requested"])
                self.assertTrue(payload["youtube_upload_succeeded"])
                video = ProductVideo.objects.get(pk=payload["product_video_id"])
                self.assertEqual(video.vendor, self.profile)
                self.assertEqual(video.youtube_video_id, "web-create-video-id")

        response = self.client.post(
            "/dashboard/vendor/product/add/",
            {
                "product_mode": "new_product",
                "name": "Normal Browser Product With Video",
                "description": "Normal non-AJAX submission.",
                "price": Decimal("100.00"),
                "stock_quantity": "2",
                "category": str(self.category.id),
                "condition": "brand_new",
                "video_type": "local",
                "local_video": SimpleUploadedFile(
                    "normal-browser.mp4",
                    b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom",
                    content_type="video/mp4",
                ),
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(ProductVideo.objects.filter(vendor=self.profile).count(), 3)

    def test_add_product_frontend_retains_id_before_instagram_request(self):
        template = Path(settings.BASE_DIR, "templates/dashboard/vendor_add_product.html").read_text()
        retained_assignment = template.index("retainedVideoId=returnedVideoId")
        instagram_request = template.index('/api/social-publishing/instagram/videos/publish/')
        self.assertLess(retained_assignment, instagram_request)
        self.assertIn('error.code==="primary_handoff_missing"', template)
        self.assertIn("YouTube: Published. Instagram: Failed", template)
        self.assertIn("Primary upload response could not be confirmed", template)


class VendorEditProductPublishingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="vendor-edit-video@arolana.com",
            username="vendor-edit-video",
            password="StrongPassword123!",
            user_type="vendor",
        )
        self.profile = VendorProfile.objects.create(
            user=self.user,
            store_name="Edit Video Vendor",
            store_slug="edit-video-vendor",
            description="Edit video tests",
            approval_status="approved",
            is_verified=True,
            is_active=True,
            address_line_1="2 Video Way",
            city="Ikeja",
            state="Lagos",
            country="Nigeria",
        )
        self.category = Category.objects.create(name="Edit Video", slug="edit-video")
        self.product = Product.objects.create(
            vendor=self.user,
            category=self.category,
            name="Edit Product",
            slug="edit-product",
            sku="EDIT-1",
            price=Decimal("50.00"),
            stock_quantity=4,
            video_type="youtube",
            video_url="https://www.youtube.com/watch?v=existing-id",
            approval_status="approved",
            is_active=True,
        )
        self.client.force_login(self.user)

    @patch("dashboard.views._inspect_vendor_product_uploads", return_value=[])
    @patch("dashboard.views.require_verified_kyc", return_value=None)
    @patch("dashboard.views.user_subscription_limits")
    def test_metadata_only_edit_does_not_republish_or_clear_video(self, limits, _kyc, _uploads):
        limits.return_value = {
            "can_upload_video": True, "can_upload_pdf": True,
            "max_images_per_product": 10, "max_variants_per_product": 10,
        }
        response = self.client.post(
            f"/dashboard/vendor/product/{self.product.id}/",
            {
                "name": "Metadata Only Edit", "price": "55.00", "stock_quantity": "5",
                "category": str(self.category.id), "condition": "brand_new",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.video_url, "https://www.youtube.com/watch?v=existing-id")
        self.assertEqual(ProductVideo.objects.count(), 0)
        self.assertEqual(SocialPublication.objects.count(), 0)

    @patch("products.views.youtube_upload_video")
    @patch("products.views.user_subscription_limits")
    def test_explicit_edit_video_upload_creates_one_pending_owned_video(self, limits, youtube_upload):
        limits.return_value = {"can_upload_video": True}
        youtube_upload.return_value = {
            "id": "replacement-id",
            "url": "https://www.youtube.com/watch?v=replacement-id",
        }
        response = self.client.post(
            reverse("products:vendor_product_videos_api"),
            {
                "product_id": str(self.product.id),
                "title": "Replacement video",
                "video": SimpleUploadedFile("replacement.mp4", b"video-bytes", content_type="video/mp4"),
            },
        )
        self.assertEqual(response.status_code, 201, response.content)
        video = ProductVideo.objects.get(pk=response.json()["video"]["id"])
        self.assertEqual(video.vendor, self.profile)
        self.assertEqual(video.moderation_status, "pending")
        self.assertIsNone(video.approved_at)
        self.assertEqual(SocialPublication.objects.count(), 0)

    def test_edit_template_has_one_upload_workspace_and_shared_progress(self):
        template = Path(settings.BASE_DIR, "templates/dashboard/vendor_product_detail.html").read_text()
        self.assertEqual(template.count('id="uploadProductVideoToYouTube"'), 1)
        self.assertIn("arolana-publishing-progress.js", template)
        self.assertIn("Existing Instagram publication", template)
