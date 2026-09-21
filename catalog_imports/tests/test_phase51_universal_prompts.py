from types import SimpleNamespace

from django.test import SimpleTestCase

from catalog_imports.models import ImportMediaCandidate
from catalog_imports.services.media_prompts import MediaPromptHold, build_generation_prompt


class Phase51UniversalPromptTests(SimpleTestCase):
    def _item(self, specs=False):
        return SimpleNamespace(
            identity_verified=True,
            specifications_verified=specs,
            normalized_payload={
                "brand": "Example",
                "name": "Classic Shirt",
                "model": "SH-1",
            },
        )

    def test_nontechnical_profile_slot_does_not_require_specs(self):
        candidate = SimpleNamespace(
            view_role=ImportMediaCandidate.VIEW_MAIN,
            metadata={
                "media_profile": "fashion",
                "media_profile_label": "Clothing / fashion",
                "display_label": "Main / hero",
                "slot_prompt": "Show the exact garment.",
                "requires_specifications": False,
                "generation_policy": "verified_preferred",
            },
        )
        prompt = build_generation_prompt(self._item(specs=False), candidate)
        self.assertIn("Clothing / fashion", prompt)
        self.assertIn("garment", prompt)

    def test_actual_only_slot_is_held(self):
        candidate = SimpleNamespace(
            view_role=ImportMediaCandidate.VIEW_MAIN,
            metadata={
                "media_profile": "property",
                "display_label": "Actual exterior",
                "generation_policy": "actual_only",
                "slot_prompt": "Actual photo required.",
                "requires_specifications": False,
            },
        )
        with self.assertRaises(MediaPromptHold):
            build_generation_prompt(self._item(specs=False), candidate)
