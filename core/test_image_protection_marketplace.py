import shutil
import tempfile
from decimal import Decimal
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image

from core.image_protection import duplicate_warning_payload, inspect_vendor_image_upload
from core.models import ProtectedImageAsset
from products.models import Category, Product, ProductImage


def _uploaded_image(name="vendor-original-name.jpg", color=(20, 90, 180)):
    buffer = BytesIO()
    Image.new("RGB", (64, 64), color).save(buffer, format="JPEG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/jpeg")


class MarketplaceImageProtectionTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media_root)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(lambda: shutil.rmtree(self.media_root, ignore_errors=True))

        self.category = Category.objects.create(name="Image Review Category", slug="image-review-category")
        self.vendor_one = get_user_model().objects.create_user(
            email="image-vendor-one@example.com",
            username="image-vendor-one",
            password="test-pass-123",
            user_type="vendor",
        )
        self.vendor_two = get_user_model().objects.create_user(
            email="image-vendor-two@example.com",
            username="image-vendor-two",
            password="test-pass-123",
            user_type="vendor",
        )
        self.product_one = self._product("IMG-001", self.vendor_one)
        self.product_two = self._product("IMG-002", self.vendor_two)

    def _product(self, sku, vendor):
        return Product.objects.create(
            sku=sku,
            name=f"Marketplace Image Product {sku}",
            description="Image review product",
            category=self.category,
            vendor=vendor,
            price=Decimal("100.00"),
            stock_quantity=3,
            is_active=True,
            approval_status="approved",
        )

    def test_upload_rewrites_filename_to_uuid_webp_and_records_original_name(self):
        product_image = ProductImage.objects.create(
            product=self.product_one,
            image=_uploaded_image("supplier-private-file-name.jpg"),
        )
        asset = ProtectedImageAsset.objects.get(
            object_id=product_image.pk,
            field_name="image",
        )

        self.assertTrue(product_image.image.name.endswith(".webp"))
        self.assertNotIn("supplier-private-file-name", product_image.image.name)
        self.assertEqual(asset.original_filename, "supplier-private-file-name.jpg")
        self.assertEqual(asset.duplicate_status, "original")
        self.assertFalse(asset.is_duplicate)

    def test_admin_saved_cross_vendor_duplicate_is_flagged_for_review(self):
        ProductImage.objects.create(
            product=self.product_one,
            image=_uploaded_image("manufacturer-image.jpg", color=(90, 20, 20)),
        )
        duplicate = ProductImage.objects.create(
            product=self.product_two,
            image=_uploaded_image("copied-manufacturer-image.jpg", color=(90, 20, 20)),
        )
        warning = duplicate_warning_payload(duplicate, "image")
        asset = ProtectedImageAsset.objects.get(
            object_id=duplicate.pk,
            field_name="image",
        )

        self.assertEqual(asset.duplicate_status, "exact_duplicate_cross_vendor")
        self.assertEqual(asset.duplicate_type, "exact")
        self.assertTrue(asset.is_duplicate)
        self.assertTrue(warning["needs_review"])

    def test_vendor_exact_cross_vendor_upload_is_blocked_before_save(self):
        ProductImage.objects.create(
            product=self.product_one,
            image=_uploaded_image("manufacturer-image.jpg", color=(90, 20, 20)),
        )

        result = inspect_vendor_image_upload(
            _uploaded_image("renamed-copy.jpg", color=(90, 20, 20)),
            self.vendor_two,
        )

        self.assertFalse(result["allowed"])
        self.assertEqual(result["status"], "exact_duplicate_cross_vendor")
        self.assertEqual(result["first_vendor_id"], self.vendor_one.id)
        self.assertEqual(result["first_product_id"], self.product_one.id)

    def test_vendor_same_vendor_upload_is_allowed_before_save(self):
        ProductImage.objects.create(
            product=self.product_one,
            image=_uploaded_image("same-vendor-base.jpg", color=(20, 140, 20)),
        )

        result = inspect_vendor_image_upload(
            _uploaded_image("renamed-own-copy.jpg", color=(20, 140, 20)),
            self.vendor_one,
        )

        self.assertTrue(result["allowed"])
        self.assertEqual(result["status"], "same_vendor_reuse")

    def test_same_vendor_duplicate_is_allowed_as_reuse(self):
        ProductImage.objects.create(
            product=self.product_one,
            image=_uploaded_image("same-vendor-base.jpg", color=(20, 140, 20)),
        )
        duplicate = ProductImage.objects.create(
            product=self.product_one,
            image=_uploaded_image("same-vendor-copy.jpg", color=(20, 140, 20)),
        )
        warning = duplicate_warning_payload(duplicate, "image")
        asset = ProtectedImageAsset.objects.get(
            object_id=duplicate.pk,
            field_name="image",
        )

        self.assertEqual(asset.duplicate_status, "same_vendor_reuse")
        self.assertTrue(warning["same_vendor_reuse"])
