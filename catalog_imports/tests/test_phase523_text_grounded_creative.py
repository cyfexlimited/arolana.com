from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from catalog_imports.models import ImportMediaCandidate
from catalog_imports.services.media_creative_fallback import (
    build_creative_fallback_prompt,
    creative_fallback_capability,
)


class Phase523TextGroundedCreativeTests(SimpleTestCase):
    def _item(self):
        return SimpleNamespace(
            normalized_payload={
                "name": "PXW-Z200",
                "brand": "Sony",
                "manufacturer": "Sony",
                "model": "PXW-Z200",
                "manufacturer_sku": "PXW-Z200",
                "category": "Professional video cameras",
                "subcategory": "Handheld camcorder",
            },
            verification_report={
                "manufacturer_web_fallback": {
                    "status": "verified",
                    "verified": True,
                    "provider": "openai_web_search",
                    "identity": {
                        "passed": True,
                        "identifier_match": True,
                    },
                    "official_product_url": "https://pro.sony/products/pxw-z200",
                    "evidence_urls": [
                        "https://pro.sony/products/pxw-z200",
                    ],
                    "payload": {
                        "name": "PXW-Z200",
                        "brand": "Sony",
                        "manufacturer": "Sony",
                        "model": "PXW-Z200",
                        "manufacturer_sku": "PXW-Z200",
                        "category": "Professional video cameras",
                        "subcategory": "Handheld camcorder",
                        "short_description": "Professional 4K handheld XDCAM camcorder.",
                        "key_features": ["4K HDR recording", "20x optical zoom"],
                        "specifications": {
                            "sensor": "1.0-type Exmor RS",
                            "optical_zoom": "20x",
                        },
                    },
                }
            },
        )

    def _candidate(self, policy="creative", role=ImportMediaCandidate.VIEW_LIFESTYLE):
        return SimpleNamespace(
            kind=ImportMediaCandidate.KIND_GENERATION,
            status=ImportMediaCandidate.STATUS_PLANNED,
            view_role=role,
            metadata={
                "generation_policy": policy,
                "creative_fallback_allowed": True,
                "display_label": "People using the product",
                "media_profile": "electronics",
                "media_profile_label": "Electronics / devices",
                "creative_prompt": "Create a professional people-in-use scene.",
                "representation_rule": "product",
            },
        )

    @patch(
        "catalog_imports.services.media_creative_fallback.creative_fallback_reference_urls",
        return_value=[],
    )
    def test_intentional_creative_slot_can_use_verified_manufacturer_text(self, refs):
        result = creative_fallback_capability(
            self._item(),
            self._candidate(),
            support_info={"supported": False, "reason": "no image"},
        )
        self.assertTrue(result["available"])
        self.assertTrue(result["text_grounded_creative"])
        self.assertEqual(result["reference_urls"], [])
        self.assertEqual(result["text_grounding"]["model"], "PXW-Z200")

    @patch(
        "catalog_imports.services.media_creative_fallback.creative_fallback_reference_urls",
        return_value=[],
    )
    def test_verified_preferred_slot_still_fails_closed_without_visual_reference(self, refs):
        result = creative_fallback_capability(
            self._item(),
            self._candidate(policy="verified_preferred"),
            support_info={"supported": False, "reason": "no image"},
        )
        self.assertFalse(result["available"])

    @patch(
        "catalog_imports.services.media_creative_fallback.creative_fallback_reference_urls",
        return_value=[],
    )
    def test_ports_still_never_use_text_grounded_creative(self, refs):
        result = creative_fallback_capability(
            self._item(),
            self._candidate(policy="creative", role=ImportMediaCandidate.VIEW_PORTS),
            support_info={"supported": False, "reason": "no image"},
        )
        self.assertFalse(result["available"])

    def test_prompt_explicitly_says_text_grounding_is_not_visual_proof(self):
        item = self._item()
        candidate = self._candidate()
        grounding = item.verification_report["manufacturer_web_fallback"]["payload"]
        grounding = {
            **grounding,
            "provider": "openai_web_search",
            "evidence_urls": ["https://pro.sony/products/pxw-z200"],
        }
        prompt = build_creative_fallback_prompt(
            item,
            candidate,
            text_grounding=grounding,
        )
        lowered = prompt.lower()
        self.assertIn("not visual proof", lowered)
        self.assertIn("pxw-z200", lowered)
        self.assertIn("20x optical zoom", lowered)
