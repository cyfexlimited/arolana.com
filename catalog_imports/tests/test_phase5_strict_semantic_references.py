from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from catalog_imports.models import ImportMediaCandidate
from catalog_imports.services.media_references import (
    reference_support_for_view,
    semantic_reference_audit,
    semantic_reference_decision,
)


class Phase509StrictSemanticReferenceTests(SimpleTestCase):
    def _item(self, name="Widget 2", model="Widget 2"):
        return SimpleNamespace(
            normalized_payload={"brand": "Example", "name": name, "model": model},
            created_product=None,
        )

    def test_ports_rejects_marketing_experience_even_with_ethernet_port_keyword(self):
        item = self._item()
        url = (
            "https://resource.example.com/content/dam/example/widget-2/"
            "widget-2-byod-experience-ethernet-port.png"
        )
        allowed, reason = semantic_reference_decision(
            item, url, ImportMediaCandidate.VIEW_PORTS
        )
        self.assertFalse(allowed)
        self.assertIn("visually classified", reason.lower())

    def test_ports_accepts_real_port_detail_asset(self):
        item = self._item()
        url = (
            "https://resource.example.com/content/dam/example/widget-2/"
            "gallery/widget-2-rear-io-port-detail.png"
        )
        allowed, reason = semantic_reference_decision(
            item, url, ImportMediaCandidate.VIEW_PORTS
        )
        self.assertFalse(allowed)
        self.assertIn("visually classified", reason.lower())

    def test_lifestyle_rejects_accessory_specific_room_solution(self):
        item = self._item()
        url = (
            "https://resource.example.com/content/dam/example/widget-2/"
            "widget-2-room-solution-active-usb-cable.png"
        )
        allowed, reason = semantic_reference_decision(
            item, url, ImportMediaCandidate.VIEW_LIFESTYLE
        )
        self.assertFalse(allowed)
        self.assertIn("visually classified", reason.lower())

    def test_lifestyle_accepts_clean_deployment_scene(self):
        item = self._item()
        url = (
            "https://resource.example.com/content/dam/example/widget-2/"
            "widget-2-deployment-byod.png"
        )
        allowed, reason = semantic_reference_decision(
            item, url, ImportMediaCandidate.VIEW_LIFESTYLE
        )
        self.assertFalse(allowed)
        self.assertIn("visually classified", reason.lower())

    def test_product_named_tap_is_not_rejected_merely_for_identity_word(self):
        item = self._item(name="Tap IP Touch Controller", model="Tap IP")
        url = (
            "https://resource.example.com/content/dam/example/tap-ip/"
            "tap-ip-meeting-room-deployment.png"
        )
        allowed, reason = semantic_reference_decision(
            item, url, ImportMediaCandidate.VIEW_LIFESTYLE
        )
        self.assertFalse(allowed)
        self.assertIn("visually classified", reason.lower())

    def test_support_blocks_ports_when_only_feature_scene_matches_keyword(self):
        item = self._item()
        feature_scene = (
            "https://resource.example.com/content/dam/example/widget-2/"
            "widget-2-byod-experience-ethernet-port.png"
        )
        with patch(
            "catalog_imports.services.media_references.manufacturer_reference_urls",
            return_value=[feature_scene],
        ), patch(
            "catalog_imports.services.media_references.rank_reference_urls",
            return_value=[feature_scene],
        ):
            report = reference_support_for_view(
                item, ImportMediaCandidate.VIEW_PORTS
            )
        self.assertFalse(report["supported"])
        self.assertTrue(report["semantic_rejections"])
        self.assertIn("strict semantic", report["reason"].lower())

    def test_audit_separates_clean_lifestyle_from_accessory_scene(self):
        item = self._item()
        clean = (
            "https://resource.example.com/content/dam/example/widget-2/"
            "widget-2-deployment-byod.png"
        )
        accessory = (
            "https://resource.example.com/content/dam/example/widget-2/"
            "widget-2-room-solution-controller.png"
        )
        with patch(
            "catalog_imports.services.media_references.manufacturer_reference_urls",
            return_value=[accessory, clean],
        ), patch(
            "catalog_imports.services.media_references.rank_reference_urls",
            return_value=[accessory, clean],
        ):
            audit = semantic_reference_audit(
                item, ImportMediaCandidate.VIEW_LIFESTYLE
            )
        self.assertEqual(audit["eligible_urls"], [])
        self.assertEqual(len(audit["rejected"]), 2)
