from decimal import Decimal

from django.test import SimpleTestCase

from catalog_imports.schema import UniversalProductDraft
from catalog_imports.services.product_data_completion import (
    build_product_data_completion_report,
    enrich_verified_draft_from_specs,
    weight_to_kg,
)


class Phase60ProductDataCompletionTests(SimpleTestCase):
    def test_verified_specs_fill_explicit_weight_dimensions_and_package_facts(self):
        draft = UniversalProductDraft(
            name="Sony PXW-Z200",
            brand="Sony",
            model="PXW-Z200",
            specifications={
                "Physical": {
                    "Weight": "2.0 kg",
                    "Dimensions": "175 x 201 x 371 mm",
                },
                "Package": {
                    "Package Weight": "8.8 lb",
                    "Package Dimensions": "20 x 15 x 12 in",
                },
            },
        )
        result = enrich_verified_draft_from_specs(draft)

        self.assertTrue(result["changed"])
        self.assertEqual(draft.weight, Decimal("2.0"))
        self.assertEqual(draft.weight_unit, "kg")
        self.assertEqual(draft.dimension_unit, "mm")
        self.assertEqual(
            draft.shipping["weight_shipping"],
            str(weight_to_kg("8.8", "lb")),
        )
        self.assertEqual(
            draft.shipping["dimensions_package"],
            "20 x 15 x 12 in",
        )

    def test_delivery_and_free_shipping_are_never_invented_by_spec_enrichment(self):
        draft = UniversalProductDraft(
            specifications={
                "Package Weight": "3 kg",
                "Package Dimensions": "40 x 30 x 20 cm",
            }
        )
        enrich_verified_draft_from_specs(draft)
        self.assertNotIn("estimated_delivery_days_min", draft.shipping)
        self.assertNotIn("estimated_delivery_days_max", draft.shipping)
        self.assertNotIn("free_shipping", draft.shipping)

    def test_optional_physical_shipping_gaps_do_not_make_critical_report_fail(self):
        draft = UniversalProductDraft(
            name="Sony PXW-Z200",
            brand="Sony",
            model="PXW-Z200",
            source_price=Decimal("4678"),
            specifications={"Sensor": "1.0-type CMOS"},
            key_features=["4K recording"],
        )
        report = build_product_data_completion_report(
            draft,
            identity_verified=True,
            specifications_verified=True,
            price_verified=True,
            calculated_price=Decimal("7067000"),
        )
        self.assertEqual(report["status"], "ready")
        self.assertEqual(report["missing_critical"], [])
        self.assertTrue(report["manual_follow_up"])
