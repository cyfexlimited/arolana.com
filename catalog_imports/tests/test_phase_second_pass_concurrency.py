from types import SimpleNamespace
from decimal import Decimal
from base64 import b64decode
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from catalog_imports.models import ImportBatch, ImportItem, ImportMediaCandidate, ImportSource
from catalog_imports.services.draft_creation import prepare_arolana_draft
from catalog_imports.services.media_publish import attach_approved_media


class SecondPassConcurrencyTests(TestCase):
    def _real_item_product(self):
        from products.models import Category, Product

        user_model = get_user_model()
        vendor = user_model.objects.create(username="rollback-vendor", user_type="vendor")
        category = Category.objects.create(name="Rollback Category", slug="rollback-category")
        product = Product.objects.create(
            sku="ROLLBACK-1", name="Rollback Product", slug="rollback-product",
            description="Product", category=category, vendor=vendor, price=Decimal("100"),
            is_active=False, approval_status="draft",
        )
        source = ImportSource.objects.create(name="Rollback Source", domain="rollback.example")
        batch = ImportBatch.objects.create(source=source, max_images=10)
        item = ImportItem.objects.create(
            batch=batch, input_value="Rollback Product", source=source,
            status=ImportItem.STATUS_DRAFT_CREATED, created_product=product,
            identity_verified=True, specifications_verified=True, price_verified=True,
        )
        return item, product

    def test_draft_wrapper_reuses_product_after_item_lock(self):
        existing_product = SimpleNamespace(pk=41, is_active=False, approval_status="draft")
        item = SimpleNamespace(pk=7)
        locked_item = SimpleNamespace(pk=7, created_product_id=41, created_product=existing_product)
        manager = MagicMock()
        manager.select_for_update.return_value.get.return_value = locked_item

        with patch("catalog_imports.services.draft_creation.ImportItem.objects", manager), \
             patch("catalog_imports.services.draft_creation._prepare_arolana_draft_locked") as prepare:
            result = prepare_arolana_draft(item)

        self.assertIs(result, existing_product)
        prepare.assert_not_called()
        manager.select_for_update.assert_called_once_with()
        manager.select_for_update.return_value.get.assert_called_once_with(pk=7)

    def test_attachment_reuses_already_attached_candidate_after_locks(self):
        class ItemStub:
            pass

        attached_image = SimpleNamespace(pk=91)
        candidate = SimpleNamespace(
            pk=12,
            kind=ImportMediaCandidate.KIND_GENERATION,
            selected_for_product=True,
            status=ImportMediaCandidate.STATUS_ATTACHED,
            exact_identity_verified=True,
            source_identity_check_passed=True,
            watermark_status=ImportMediaCandidate.WATERMARK_CLEAR,
            rights_status=ImportMediaCandidate.RIGHTS_CONFIRMED,
            asset_storage_alias="private_import_review",
            asset_storage_name="review/12.webp",
            attached_product_image_id=91,
            attached_product_image=attached_image,
            sha256="",
            view_role=ImportMediaCandidate.VIEW_MAIN,
        )
        candidate_manager = MagicMock()
        candidate_manager.filter.return_value.select_for_update.return_value.select_related.return_value.order_by.return_value = [candidate]
        locked_item = SimpleNamespace(
            pk=7,
            created_product_id=33,
            batch=SimpleNamespace(max_images=10),
            media_candidates=candidate_manager,
        )
        item_manager = MagicMock()
        item_manager.select_for_update.return_value.select_related.return_value.get.return_value = locked_item
        product = SimpleNamespace(pk=33, is_active=False, approval_status="draft")

        item = ItemStub()
        item.pk = 7
        with patch.object(ItemStub, "objects", item_manager, create=True), \
             patch("products.models.Product.objects", MagicMock(
                 select_for_update=MagicMock(return_value=MagicMock(get=MagicMock(return_value=product)))
             )), patch("products.models.ProductImage") as product_image:
            result = attach_approved_media(item)

        self.assertEqual(result, [attached_image])
        product_image.assert_not_called()
        candidate_manager.filter.return_value.select_for_update.assert_called_once_with()

    def test_media_attachment_rolls_back_and_retries_idempotently(self):
        from products.models import ProductImage

        item, product = self._real_item_product()
        candidate = ImportMediaCandidate.objects.create(
            item=item, kind=ImportMediaCandidate.KIND_GENERATION,
            view_role=ImportMediaCandidate.VIEW_MAIN,
            status=ImportMediaCandidate.STATUS_APPROVED,
            selected_for_product=True,
            exact_identity_verified=True,
            source_identity_check_passed=True,
            watermark_status=ImportMediaCandidate.WATERMARK_CLEAR,
            rights_status=ImportMediaCandidate.RIGHTS_CONFIRMED,
            asset_storage_alias="private_import_review",
            asset_storage_name="rollback.webp",
            asset_original_name="rollback.webp",
        )
        image_bytes = b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")

        with patch("catalog_imports.services.media_publish._read_candidate_bytes", return_value=image_bytes), \
             patch.object(ProductImage, "save", side_effect=RuntimeError("forced image failure")):
            with self.assertRaises(RuntimeError):
                attach_approved_media(item)

        candidate.refresh_from_db()
        self.assertNotEqual(candidate.status, ImportMediaCandidate.STATUS_ATTACHED)
        self.assertIsNone(candidate.attached_product_image_id)
        self.assertFalse(ProductImage.objects.filter(product=product).exists())

        with patch("catalog_imports.services.media_publish._read_candidate_bytes", return_value=image_bytes):
            attached = attach_approved_media(item)
            self.assertEqual(len(attached), 1)
            self.assertEqual(ProductImage.objects.filter(product=product).count(), 1)
            candidate.refresh_from_db()
            self.assertIsNotNone(candidate.attached_product_image_id)
            attach_approved_media(item)

        self.assertEqual(ProductImage.objects.filter(product=product).count(), 1)

    def test_product_draft_creation_rolls_back_and_retries_idempotently(self):
        from products.models import Category, Product

        user_model = get_user_model()
        vendor = user_model.objects.create(username="draft-rollback-vendor", user_type="vendor")
        category = Category.objects.create(name="Draft Rollback Category", slug="draft-rollback-category")
        source = ImportSource.objects.create(name="Draft Rollback Source", domain="draft-rollback.example")
        batch = ImportBatch.objects.create(source=source)
        item = ImportItem.objects.create(
            batch=batch, input_value="Draft Rollback Product", source=source,
            status=ImportItem.STATUS_READY, identity_verified=True,
            specifications_verified=True, price_verified=True,
            calculated_price=Decimal("1000"), source_price=Decimal("800"),
            normalized_payload={
                "name": "Draft Rollback Product", "brand": "Example", "model": "DR-1",
                "specifications": {"Color": "Black"}, "manufacturer_sku": "DR-1",
            }, target_vendor=vendor, target_category=category,
        )
        before = Product.objects.count()

        with patch("products.models.Product.save", side_effect=RuntimeError("forced product failure")):
            with self.assertRaises(RuntimeError):
                prepare_arolana_draft(item)

        item.refresh_from_db()
        self.assertIsNone(item.created_product_id)
        self.assertEqual(Product.objects.count(), before)

        product = prepare_arolana_draft(item)
        item.refresh_from_db()
        self.assertEqual(Product.objects.count(), before + 1)
        self.assertEqual(item.created_product_id, product.pk)
        self.assertFalse(product.is_active)
        self.assertEqual(product.approval_status, "draft")

        reused = prepare_arolana_draft(item)
        self.assertEqual(reused.pk, product.pk)
        self.assertEqual(Product.objects.count(), before + 1)
