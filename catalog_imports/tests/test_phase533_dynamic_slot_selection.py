from types import SimpleNamespace

from django.test import SimpleTestCase

from catalog_imports.models import ImportMediaCandidate
from catalog_imports.services.dynamic_verified_slots import (
    candidate_can_be_replaced,
    select_dynamic_verified_slots,
)
from catalog_imports.services.media_profiles import ELECTRONICS, PROPERTY


def _support(*roles):
    result = {}
    for role, _label in ImportMediaCandidate.VIEW_CHOICES:
        result[role] = {
            "supported": role in roles,
            "eligible_urls": [],
            "reason": "",
        }
    return result


class Phase533DynamicSlotSelectionTests(SimpleTestCase):
    def _item(self, max_images=10):
        return SimpleNamespace(
            batch=SimpleNamespace(max_images=max_images),
        )

    def test_electronics_verified_back_replaces_3d_creative_slot(self):
        result = select_dynamic_verified_slots(
            self._item(),
            profile=ELECTRONICS,
            max_images=10,
            support=_support(
                ImportMediaCandidate.VIEW_MAIN,
                ImportMediaCandidate.VIEW_BACK,
            ),
        )

        self.assertEqual(len(result["slots"]), 10)
        self.assertEqual(len(result["replacements"]), 1)
        replacement = result["replacements"][0]
        self.assertEqual(replacement["role"], ImportMediaCandidate.VIEW_BACK)
        self.assertEqual(replacement["old_slot_key"], "render")
        self.assertEqual(replacement["new_label"], "Back / rear")

        roles = [slot.legacy_view_role for slot in result["slots"]]
        self.assertIn(ImportMediaCandidate.VIEW_BACK, roles)

    def test_supported_side_upgrades_matching_legacy_creative_slot(self):
        result = select_dynamic_verified_slots(
            self._item(),
            profile=ELECTRONICS,
            max_images=10,
            support=_support(ImportMediaCandidate.VIEW_SIDE),
        )
        self.assertEqual(result["replacements"][0]["old_slot_key"], "render")
        self.assertEqual(result["replacements"][0]["role"], ImportMediaCandidate.VIEW_SIDE)
        self.assertEqual(result["replacements"][0]["new_label"], "Side profile")

    def test_existing_factual_role_is_not_duplicated(self):
        result = select_dynamic_verified_slots(
            self._item(),
            profile=ELECTRONICS,
            max_images=10,
            support=_support(
                ImportMediaCandidate.VIEW_FRONT,
                ImportMediaCandidate.VIEW_PORTS,
                ImportMediaCandidate.VIEW_PACKAGE,
            ),
        )
        self.assertEqual(result["replacements"], [])

    def test_property_profile_is_not_dynamically_rewritten(self):
        result = select_dynamic_verified_slots(
            self._item(),
            profile=PROPERTY,
            max_images=10,
            support=_support(ImportMediaCandidate.VIEW_BACK),
        )
        self.assertEqual(result["replacements"], [])

    def test_ready_review_creative_is_replaceable_but_approved_is_not(self):
        ready = SimpleNamespace(
            metadata={"generation_policy": "creative"},
            status=ImportMediaCandidate.STATUS_READY_REVIEW,
            selected_for_product=False,
            attached_product_image_id=None,
        )
        approved = SimpleNamespace(
            metadata={"generation_policy": "creative"},
            status=ImportMediaCandidate.STATUS_APPROVED,
            selected_for_product=False,
            attached_product_image_id=None,
        )
        self.assertTrue(candidate_can_be_replaced(ready))
        self.assertFalse(candidate_can_be_replaced(approved))
