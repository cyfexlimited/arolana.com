from django.test import SimpleTestCase

from catalog_imports.services.web_evidence import deterministic_identity_check


class Phase522ExactModelIdentityTests(SimpleTestCase):
    def test_wrong_model_cannot_pass_on_family_name_overlap(self):
        payload = {
            "exact_identity_confirmed": True,
            "name": "Sony PXW-Z190 Camcorder",
            "brand": "Sony",
            "model": "PXW-Z190",
        }
        result = deterministic_identity_check(
            "https://www.bhphotovideo.com/c/product/1848319-REG/sony_pxw_z200_4k_1_cmos.html",
            payload,
            expected_brand="Sony",
        )
        self.assertFalse(result["passed"])
        self.assertFalse(result["identifier_match"])
        self.assertEqual(result["identity_rule"], "explicit_identifier_required")

    def test_exact_model_still_passes(self):
        payload = {
            "exact_identity_confirmed": True,
            "name": "Sony PXW-Z200 4K XDCAM Camcorder",
            "brand": "Sony",
            "model": "PXW-Z200",
        }
        result = deterministic_identity_check(
            "https://www.bhphotovideo.com/c/product/1848319-REG/sony_pxw_z200_4k_1_cmos.html",
            payload,
            expected_brand="Sony",
        )
        self.assertTrue(result["passed"])
        self.assertTrue(result["identifier_match"])

    def test_name_overlap_is_only_fallback_when_no_identifier_exists(self):
        payload = {
            "exact_identity_confirmed": True,
            "name": "Acme Studio Chair Deluxe",
            "brand": "Acme",
            "model": "",
            "manufacturer_sku": "",
            "gtin": "",
            "ean": "",
            "upc": "",
        }
        result = deterministic_identity_check(
            "https://retailer.example/acme-studio-chair-deluxe",
            payload,
            expected_brand="Acme",
        )
        self.assertTrue(result["passed"])
        self.assertEqual(result["identity_rule"], "name_overlap_fallback_no_identifier")
