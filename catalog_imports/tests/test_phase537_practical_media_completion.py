from types import SimpleNamespace

from django.test import SimpleTestCase

from catalog_imports.models import ImportMediaCandidate
from catalog_imports.services.practical_media_completion import (
    practical_media_completion,
)


class _FakeQuerySet(list):
    def filter(self, **kwargs):
        return self

    def order_by(self, *args):
        return self


class Phase537PracticalMediaCompletionTests(SimpleTestCase):
    def _candidate(self, role, status, has_asset=True):
        return SimpleNamespace(
            view_role=role,
            status=status,
            asset_storage_name=("review/image.webp" if has_asset else ""),
        )

    def _item(self, candidates, max_images=10):
        return SimpleNamespace(
            batch=SimpleNamespace(max_images=max_images),
            media_candidates=_FakeQuerySet(candidates),
        )

    def test_six_usable_images_plus_main_is_sufficient_for_review(self):
        candidates = [
            self._candidate(
                ImportMediaCandidate.VIEW_MAIN,
                ImportMediaCandidate.STATUS_APPROVED,
            )
        ]
        candidates += [
            self._candidate(
                ImportMediaCandidate.VIEW_LIFESTYLE,
                ImportMediaCandidate.STATUS_READY_REVIEW,
            )
            for _ in range(5)
        ]
        report = practical_media_completion(
            self._item(candidates),
            minimum=6,
        )
        self.assertTrue(report["sufficient_for_review"])
        self.assertTrue(report["stop_bulk_generation"])
        self.assertEqual(report["usable_count"], 6)
        self.assertEqual(report["remaining_optional_slots"], 4)

    def test_no_main_never_counts_as_sufficient(self):
        candidates = [
            self._candidate(
                ImportMediaCandidate.VIEW_LIFESTYLE,
                ImportMediaCandidate.STATUS_READY_REVIEW,
            )
            for _ in range(7)
        ]
        report = practical_media_completion(
            self._item(candidates),
            minimum=6,
        )
        self.assertFalse(report["sufficient_for_review"])
        self.assertFalse(report["main_usable"])

    def test_rejected_failed_and_planned_assets_do_not_count(self):
        candidates = [
            self._candidate(
                ImportMediaCandidate.VIEW_MAIN,
                ImportMediaCandidate.STATUS_APPROVED,
            ),
            self._candidate(
                ImportMediaCandidate.VIEW_FRONT,
                ImportMediaCandidate.STATUS_REJECTED,
            ),
            self._candidate(
                ImportMediaCandidate.VIEW_BACK,
                ImportMediaCandidate.STATUS_FAILED,
            ),
            self._candidate(
                ImportMediaCandidate.VIEW_SIDE,
                ImportMediaCandidate.STATUS_PLANNED,
            ),
        ]
        report = practical_media_completion(
            self._item(candidates),
            minimum=2,
        )
        self.assertEqual(report["usable_count"], 1)
        self.assertFalse(report["sufficient_for_review"])
