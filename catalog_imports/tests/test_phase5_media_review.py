from unittest.mock import patch

from django.test import SimpleTestCase

from catalog_imports.models import ImportMediaCandidate
from catalog_imports.services.media_review import MediaReviewError, approve_candidate, reject_candidate


class DummyCandidate:
    kind = ImportMediaCandidate.KIND_GENERATION
    status = ImportMediaCandidate.STATUS_READY_REVIEW
    asset_storage_alias = "default"
    asset_storage_name = "catalog-imports/review/x.webp"
    sha256 = "a" * 64
    exact_identity_verified = False
    source_identity_check_passed = False
    watermark_status = ImportMediaCandidate.WATERMARK_UNKNOWN
    rights_status = ImportMediaCandidate.RIGHTS_UNKNOWN
    selected_for_product = False
    reviewed_at = None
    approved_by = None
    approved_at = None
    rejected_by = None
    rejected_at = None
    rejection_reason = ""
    last_error = ""

    def save(self, *args, **kwargs):
        return None


class Phase5MediaReviewTests(SimpleTestCase):
    @patch("catalog_imports.services.media_review.duplicate_hash_exists", return_value=False)
    @patch("catalog_imports.services.media_review.review_asset_exists", return_value=True)
    def test_approval_requires_all_human_checks(self, exists, duplicate):
        candidate = DummyCandidate()
        with self.assertRaises(MediaReviewError):
            approve_candidate(
                candidate,
                actor=object(),
                exact_identity_verified=True,
                watermark_clear=False,
                source_identity_clear=True,
                rights_confirmed=True,
            )

    @patch("catalog_imports.services.media_review.duplicate_hash_exists", return_value=False)
    @patch("catalog_imports.services.media_review.review_asset_exists", return_value=True)
    def test_approval_sets_all_safety_state(self, exists, duplicate):
        candidate = DummyCandidate()
        actor = object()
        approve_candidate(
            candidate,
            actor=actor,
            exact_identity_verified=True,
            watermark_clear=True,
            source_identity_clear=True,
            rights_confirmed=True,
        )
        self.assertEqual(candidate.status, ImportMediaCandidate.STATUS_APPROVED)
        self.assertTrue(candidate.exact_identity_verified)
        self.assertTrue(candidate.source_identity_check_passed)
        self.assertEqual(candidate.watermark_status, ImportMediaCandidate.WATERMARK_CLEAR)
        self.assertEqual(candidate.rights_status, ImportMediaCandidate.RIGHTS_CONFIRMED)
        self.assertTrue(candidate.selected_for_product)

    def test_reference_only_candidate_cannot_be_approved(self):
        candidate = DummyCandidate()
        candidate.kind = ImportMediaCandidate.KIND_REFERENCE
        with self.assertRaises(MediaReviewError):
            approve_candidate(
                candidate,
                actor=object(),
                exact_identity_verified=True,
                watermark_clear=True,
                source_identity_clear=True,
                rights_confirmed=True,
            )
