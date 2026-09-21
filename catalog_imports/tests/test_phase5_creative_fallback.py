from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from catalog_imports.models import ImportMediaCandidate
from catalog_imports.services.media_creative_fallback import (
    build_creative_fallback_prompt,
    creative_fallback_capability,
)


class Phase514CreativeFallbackTests(SimpleTestCase):
    def _item(self):
        return SimpleNamespace(
            normalized_payload={
                "brand": "Example",
                "name": "Widget 2",
                "model": "Widget 2",
            }
        )

    def _candidate(self, role):
        return SimpleNamespace(
            kind=ImportMediaCandidate.KIND_GENERATION,
            view_role=role,
            status=ImportMediaCandidate.STATUS_FAILED,
        )

    @patch(
        "catalog_imports.services.media_creative_fallback.creative_fallback_reference_urls",
        return_value=["https://manufacturer.example/widget-2-front.png"],
    )
    def test_creative_fallback_is_available_only_when_exact_view_is_unsupported(
        self,
        refs,
    ):
        candidate = self._candidate(ImportMediaCandidate.VIEW_SIDE)

        available = creative_fallback_capability(
            self._item(),
            candidate,
            support_info={
                "supported": False,
                "reason": "No verified side view.",
            },
        )
        self.assertTrue(available["available"])

        blocked = creative_fallback_capability(
            self._item(),
            candidate,
            support_info={
                "supported": True,
                "reason": "",
            },
        )
        self.assertFalse(blocked["available"])

    def test_ports_do_not_offer_creative_fallback(self):
        candidate = self._candidate(ImportMediaCandidate.VIEW_PORTS)
        result = creative_fallback_capability(
            self._item(),
            candidate,
            support_info={"supported": False, "reason": "No port view."},
        )
        self.assertFalse(result["available"])

    def test_package_creative_prompt_never_invents_contents(self):
        candidate = self._candidate(ImportMediaCandidate.VIEW_PACKAGE)
        prompt = build_creative_fallback_prompt(self._item(), candidate)
        lower = prompt.lower()

        self.assertIn("plain unbranded closed box", lower)
        self.assertIn("do not show the inside of the box", lower)
        self.assertIn("do not show or imply specific included accessories", lower)
        self.assertIn("unverified", lower)
