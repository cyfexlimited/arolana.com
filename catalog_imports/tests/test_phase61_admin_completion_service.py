from types import SimpleNamespace

from django.test import SimpleTestCase

from catalog_imports.services.admin_completion import build_admin_completion_report


class _Images:
    def __init__(self, count):
        self._count = count

    def count(self):
        return self._count


class _Candidates(list):
    def filter(self, **kwargs):
        return self

    def order_by(self, *args):
        return self


class Phase61AdminCompletionServiceTests(SimpleTestCase):
    def _item(self, product):
        return SimpleNamespace(
            verification_report={
                "product_data_completion": {
                    "status": "ready",
                    "missing_critical": [],
                }
            },
            identity_verified=True,
            specifications_verified=True,
            price_verified=True,
            calculated_price=100,
            created_product=product,
            batch=SimpleNamespace(max_images=10),
            media_candidates=_Candidates([]),
        )

    def test_missing_operational_fields_are_manual_not_verification_failure(self):
        product = SimpleNamespace(
            pk=91,
            sku="TEST-91",
            is_active=False,
            approval_status="draft",
            description="Description",
            specifications="Specs",
            meta_title="Title",
            meta_description="Description",
            weight=1,
            dimensions_length=1,
            dimensions_width=1,
            dimensions_height=1,
            country_of_origin="",
            manufacturer_address="",
            certifications=[],
            warranty_years=0,
            warranty_description="",
            main_image=None,
            images=_Images(0),
        )
        report = build_admin_completion_report(self._item(product))
        self.assertEqual(report["status"], "ready_for_admin_completion")
        keys = {row["key"] for row in report["manual_remaining"]}
        self.assertIn("shipping_weight", keys)
        self.assertIn("package_dimensions", keys)
        self.assertIn("delivery_range", keys)
        self.assertIn("warranty", keys)

    def test_optional_manufacturer_fields_do_not_block(self):
        product = SimpleNamespace(
            pk=1,
            sku="SKU",
            is_active=False,
            approval_status="draft",
            description="x",
            specifications="x",
            meta_title="x",
            meta_description="x",
            weight=1,
            dimensions_length=1,
            dimensions_width=1,
            dimensions_height=1,
            country_of_origin="",
            manufacturer_address="",
            certifications=[],
            warranty_years=1,
            warranty_description="",
            main_image="main.webp",
            images=_Images(8),
            shipping_info=SimpleNamespace(
                weight_shipping=2,
                dimensions_package="10 x 10 x 10 cm",
                estimated_delivery_days_min=2,
                estimated_delivery_days_max=5,
            ),
        )
        report = build_admin_completion_report(self._item(product))
        self.assertEqual(report["status"], "ready_for_approval_review")
        self.assertTrue(report["optional_remaining"])
