from types import SimpleNamespace

from django.test import SimpleTestCase

from catalog_imports.models import ImportMediaCandidate
from catalog_imports.services.manual_creative_downgrade import (
    can_downgrade_to_manual_creative,
)


class Phase534ManualCreativeDowngradeTests(SimpleTestCase):
    def _candidate(self, **overrides):
        values = dict(
            kind=ImportMediaCandidate.KIND_GENERATION,
            status=ImportMediaCandidate.STATUS_READY_REVIEW,
            selected_for_product=False,
            attached_product_image_id=None,
            asset_storage_name="catalog_imports/review/front.webp",
            provider_response={},
        )
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_ready_review_verified_candidate_can_be_downgraded(self):
        self.assertTrue(can_downgrade_to_manual_creative(self._candidate()))

    def test_approved_unattached_candidate_can_be_downgraded(self):
        candidate = self._candidate(status=ImportMediaCandidate.STATUS_APPROVED)
        self.assertTrue(can_downgrade_to_manual_creative(candidate))

    def test_attached_candidate_cannot_be_downgraded(self):
        self.assertFalse(can_downgrade_to_manual_creative(
            self._candidate(
                status=ImportMediaCandidate.STATUS_APPROVED,
                attached_product_image_id=99,
            )
        ))

    def test_candidate_without_generated_asset_cannot_be_downgraded(self):
        self.assertFalse(can_downgrade_to_manual_creative(
            self._candidate(status=ImportMediaCandidate.STATUS_APPROVED, asset_storage_name="")
        ))

    def test_existing_creative_candidate_is_not_downgraded_again(self):
        self.assertFalse(
            can_downgrade_to_manual_creative(
                self._candidate(
                    provider_response={"_arolana_creative_fallback": True}
                )
            )
        )
