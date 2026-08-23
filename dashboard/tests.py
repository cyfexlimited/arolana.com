from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.conf import settings

from products.models import Category, ProductVideo
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
