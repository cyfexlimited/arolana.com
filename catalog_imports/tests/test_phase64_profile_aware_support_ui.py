from types import SimpleNamespace

from django.test import SimpleTestCase

from catalog_imports.models import ImportMediaCandidate
from catalog_imports.admin import _profile_aware_support_reason


class Phase64ProfileAwareSupportUITests(SimpleTestCase):
    def _candidate(self, label, policy="verified_preferred", actual=False):
        return SimpleNamespace(
            view_role=ImportMediaCandidate.VIEW_PORTS,
            metadata={
                "display_label": label,
                "media_profile_label": "Shoes / footwear",
                "generation_policy": policy,
                "actual_only": actual,
            },
        )

    def test_footwear_outsole_error_does_not_say_ports_controls(self):
        candidate = self._candidate("Sole / outsole")
        text = _profile_aware_support_reason(
            candidate,
            {"supported": False, "reason": "No ports/controls reference."},
        )
        self.assertIn("Sole / outsole", text)
        self.assertNotIn("ports/controls", text.lower())

    def test_creative_slot_explains_unverified_fallback(self):
        candidate = self._candidate(
            "Street / styling scene",
            policy="creative",
        )
        text = _profile_aware_support_reason(candidate, {"supported": False})
        self.assertIn("Street / styling scene", text)
        self.assertIn("creative fallback", text)
