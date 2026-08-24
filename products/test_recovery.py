import io
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.test import TestCase

from products.models import Category, Product, ProductVideo
from social_publishing.models import PublicationStatus, SocialPlatform, SocialPublication
from vendors.models import VendorProfile


class DeletedProductRecoveryTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.vendor = User.objects.create_user(
            username="recovery-vendor",
            email="recovery-vendor@example.com",
            user_type="vendor",
        )
        self.profile = VendorProfile.objects.create(
            user=self.vendor,
            store_name="Recovery Vendor",
            store_slug="recovery-vendor",
            description="Recovery",
            approval_status="approved",
            country="Nigeria",
            state="Lagos",
            city="Ikeja",
            address_line_1="1 Recovery Road",
        )
        self.admin_user = User.objects.create_superuser(
            username="recovery-admin",
            email="recovery-admin@example.com",
            password="test",
        )
        self.category = Category.objects.create(
            name="Recovery Category", slug="recovery-category", is_active=True
        )
        self.product = Product.objects.create(
            id=1042,
            vendor=self.vendor,
            category=self.category,
            sku="RECOVERY-1042",
            name="Recovered product",
            slug="recovered-product-deleted",
            description="Recovered description",
            price="100.00",
            stock_quantity=1,
            approval_status="approved",
            approved_by=self.admin_user,
            is_active=True,
        )
        self.video = ProductVideo.objects.create(
            id=15,
            product=self.product,
            vendor=self.profile,
            title="Recovered product",
            description="Recovered description",
            source="youtube",
            youtube_url="https://www.youtube.com/watch?v=NSEgziF-7zY",
            youtube_video_id="NSEgziF-7zY",
            youtube_visibility="unlisted",
            moderation_status="approved",
            approved_by=self.admin_user,
            is_active=True,
        )
        self.publication = SocialPublication.objects.create(
            owner_user=self.vendor,
            owner_role="vendor",
            platform=SocialPlatform.INSTAGRAM,
            content_object=self.video,
            status=PublicationStatus.PUBLISHED,
            external_id="instagram-media-1",
            external_url="https://www.instagram.com/reel/example/",
        )

    def _manifest(self):
        return {
            "evidence": {"deleted_product_id": 1042, "deleted_product_video_id": 15},
            "product": {
                "vendor_user_id": self.vendor.pk,
                "vendor_email": self.vendor.email,
                "sku": "RECOVERY-1042",
                "name": "Recovered product",
                "slug": "recovered-product",
                "description": "Recovered description",
                "specifications": "",
                "category_id": self.category.pk,
                "brand_id": None,
                "price": "100.00",
                "stock_quantity": 1,
                "condition": Product.CONDITION_BRAND_NEW,
                "manufacturer_sku": "",
                "main_image": "products/recovery-main.webp",
                "approved_by_user_id": self.admin_user.pk,
                "approved_at": "2026-08-23T23:36:59+00:00",
            },
            "video": {
                "vendor_profile_id": self.profile.pk,
                "title": "Recovered product",
                "description": "Recovered description",
                "youtube_video_id": "NSEgziF-7zY",
                "youtube_url": "https://www.youtube.com/watch?v=NSEgziF-7zY",
                "youtube_visibility": "unlisted",
                "duration_seconds": 19,
                "approved_by_user_id": self.admin_user.pk,
                "approved_at": "2026-08-24T00:08:52+00:00",
            },
            "gallery_images": [
                {"file_name": "products/gallery/recovery-1.webp", "order": 0}
            ],
            "social_publication": {
                "id": self.publication.pk,
                "external_id": self.publication.external_id,
                "status": "published",
            },
        }

    def _write_manifest(self, data):
        directory = tempfile.TemporaryDirectory()
        path = Path(directory.name, "manifest.json")
        path.write_text(json.dumps(data))
        self.addCleanup(directory.cleanup)
        return path

    @patch("products.management.commands.reconstruct_deleted_product.default_storage.exists", return_value=True)
    def test_dry_run_reports_plan_without_creating_records(self, _mock_exists):
        self.product.delete()
        path = self._write_manifest(self._manifest())
        output = io.StringIO()

        call_command("reconstruct_deleted_product", manifest=str(path), stdout=output)

        payload = json.loads(output.getvalue())
        self.assertTrue(payload["ready_to_apply"])
        self.assertFalse(payload["would_create"]["forced_primary_keys"])
        self.assertFalse(payload["would_publish_externally"])
        self.assertFalse(Product.objects.filter(sku="RECOVERY-1042").exists())

    @patch("products.models.record_protected_image")
    @patch("products.management.commands.reconstruct_deleted_product.default_storage.exists", return_value=True)
    @patch("social_publishing.instagram.publish_reel")
    def test_apply_creates_new_ids_and_only_reattaches_audit_record(
        self, mock_publish, _mock_exists, _mock_record_image
    ):
        self.product.delete()
        path = self._write_manifest(self._manifest())
        output = io.StringIO()

        call_command(
            "reconstruct_deleted_product",
            manifest=str(path),
            apply=True,
            confirm="RECONSTRUCT_DELETED_PRODUCT",
            stdout=output,
        )

        payload = json.loads(output.getvalue())
        self.assertNotEqual(payload["product_id"], 1042)
        self.assertNotEqual(payload["product_video_id"], 15)
        self.publication.refresh_from_db()
        self.assertEqual(self.publication.object_id, payload["product_video_id"])
        self.assertEqual(self.publication.status, PublicationStatus.PUBLISHED)
        mock_publish.assert_not_called()

    def test_product_admin_delete_is_blocked_when_publication_audit_exists(self):
        product_admin = admin.site._registry[Product]

        _deleted, _counts, permissions, _protected = product_admin.get_deleted_objects(
            [self.product], type("Request", (), {"user": self.admin_user})()
        )

        self.assertTrue(any("social publication audit records" in item for item in permissions))
        with self.assertRaises(PermissionDenied):
            product_admin.delete_model(
                type("Request", (), {"user": self.admin_user})(), self.product
            )

    def test_product_video_admin_delete_is_blocked_when_publication_audit_exists(self):
        video_admin = admin.site._registry[ProductVideo]

        with self.assertRaises(PermissionDenied):
            video_admin.delete_model(
                type("Request", (), {"user": self.admin_user})(), self.video
            )
