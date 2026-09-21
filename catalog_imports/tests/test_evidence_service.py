from decimal import Decimal
from django.test import SimpleTestCase

from catalog_imports.schema import UniversalProductDraft
from catalog_imports.services.evidence import (
    compare_identity,
    merge_authoritative_draft,
    official_domain_matches,
    readiness_decision,
)


class EvidenceServiceTests(SimpleTestCase):
    def test_official_domain_allows_subdomains_only(self):
        self.assertTrue(official_domain_matches("https://www.logitech.com/en-us/x", "logitech.com"))
        self.assertTrue(official_domain_matches("https://logitech.com/x", "logitech.com"))
        self.assertFalse(official_domain_matches("https://logitech.example.com/x", "logitech.com"))
        self.assertFalse(official_domain_matches("http://notlogitech.com/x", "logitech.com"))

    def test_manufacturer_merge_never_replaces_retailer_price(self):
        retailer = UniversalProductDraft(
            source_name="Retailer",
            source_url="https://retailer.example/item",
            name="Logitech MeetUp 2",
            brand="Logitech",
            manufacturer_sku="960-001681",
            source_price=Decimal("1500500.00"),
            source_currency="NGN",
        )
        manufacturer = UniversalProductDraft(
            source_name="Logitech",
            source_url="https://www.logitech.com/meetup-2",
            name="MeetUp 2",
            brand="Logitech",
            manufacturer_sku="960-001681",
            source_price=Decimal("999.00"),
            source_currency="USD",
            specifications={"Resolution": "4K"},
        )
        merged = merge_authoritative_draft(retailer, manufacturer)
        self.assertEqual(merged.source_price, Decimal("1500500.00"))
        self.assertEqual(merged.source_currency, "NGN")
        self.assertEqual(merged.source_name, "Retailer")
        self.assertEqual(merged.specifications["Resolution"], "4K")

    def test_exact_identifier_conflict_blocks_identity(self):
        retailer = UniversalProductDraft(
            name="Logitech MeetUp 2",
            brand="Logitech",
            manufacturer_sku="960-001681",
        )
        manufacturer = UniversalProductDraft(
            name="MeetUp 2",
            brand="Logitech",
            manufacturer_sku="960-WRONG",
        )
        report = compare_identity(
            retailer,
            manufacturer,
            input_hint="https://example.com/logitech-meetup-2.html",
            expected_brand="Logitech",
            official_domain_ok=True,
        )
        self.assertFalse(report["passed"])
        self.assertTrue(report["identifier_conflict"])

    def test_blocked_retailer_can_verify_identity_but_price_hold_remains(self):
        manufacturer = UniversalProductDraft(
            name="Logitech MeetUp 2 Conference Camera",
            brand="Logitech",
            manufacturer_sku="960-001681",
        )
        report = compare_identity(
            None,
            manufacturer,
            input_hint="https://retailer.example/logitech-meetup-2-video-conferencing-camera.html",
            expected_brand="Logitech",
            official_domain_ok=True,
        )
        self.assertTrue(report["passed"])
        decision = readiness_decision(
            quality_passed=True,
            contamination_passed=True,
            price_verified=False,
            manufacturer_required=True,
            identity_verified=True,
        )
        self.assertFalse(decision["ready"])
        self.assertIn("source_price_unverified", decision["reasons"])

class BlockedSourceIdentityStrictnessTests(SimpleTestCase):
    def test_old_meetup_does_not_verify_meetup_2_url(self):
        manufacturer = UniversalProductDraft(
            name="Logitech MeetUp Conference Camera",
            brand="Logitech",
        )
        report = compare_identity(
            None,
            manufacturer,
            input_hint="https://paykobo.com/logitech-meetup-2-video-conferencing-camera.html",
            expected_brand="Logitech",
            official_domain_ok=True,
        )
        self.assertFalse(report["passed"])
