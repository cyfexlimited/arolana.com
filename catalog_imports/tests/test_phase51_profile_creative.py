from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from catalog_imports.models import ImportMediaCandidate
from catalog_imports.services.media_creative_fallback import (
    build_creative_fallback_prompt,
    creative_fallback_capability,
)


class Phase51ProfileAwareCreativeTests(SimpleTestCase):
    def _candidate(self, metadata):
        return SimpleNamespace(
            kind=ImportMediaCandidate.KIND_GENERATION,
            view_role=ImportMediaCandidate.VIEW_LIFESTYLE,
            status=ImportMediaCandidate.STATUS_PLANNED,
            metadata=metadata,
        )

    @patch(
        "catalog_imports.services.media_creative_fallback.creative_fallback_reference_urls",
        return_value=["https://manufacturer.example/item.png"],
    )
    def test_intentional_creative_slot_works_even_when_legacy_role_has_support(self, refs):
        candidate = self._candidate({
            "generation_policy": "creative",
            "creative_fallback_allowed": True,
            "display_label": "Model wearing item",
            "media_profile": "fashion",
        })
        result = creative_fallback_capability(
            SimpleNamespace(),
            candidate,
            support_info={"supported": True, "reason": ""},
        )
        self.assertTrue(result["available"])
        self.assertTrue(result["intentional_creative"])

    def test_actual_only_property_slot_blocks_creative_generation(self):
        candidate = self._candidate({
            "generation_policy": "actual_only",
            "creative_fallback_allowed": False,
            "display_label": "Actual exterior",
            "media_profile": "property",
        })
        result = creative_fallback_capability(
            SimpleNamespace(),
            candidate,
            support_info={"supported": False, "reason": ""},
        )
        self.assertFalse(result["available"])
        self.assertIn("actual", result["reason"].lower())

    def test_concept_property_prompt_disclaims_documentary_facts(self):
        candidate = self._candidate({
            "generation_policy": "creative",
            "creative_fallback_allowed": True,
            "display_label": "Concept staging visualization",
            "creative_prompt": "Create an optional staged concept.",
            "representation_rule": "concept_only",
            "media_profile": "property",
        })
        item = SimpleNamespace(
            normalized_payload={"name": "4 Bedroom Duplex", "brand": "", "model": ""}
        )
        prompt = build_creative_fallback_prompt(item, candidate).lower()
        self.assertIn("concept visualization", prompt)
        self.assertIn("not documentary evidence", prompt)
        self.assertIn("do not represent", prompt)
