from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from catalog_imports.models import ImportMediaCandidate
from catalog_imports.services.media_plan import VIEW_PLAN, generation_prompt
from catalog_imports.services.media_prompts import build_generation_prompt
from catalog_imports.services.media_review import approve_candidate


class Phase511CompatibilityHotfixTests(SimpleTestCase):
    def test_legacy_view_plan_export_and_generation_prompt_are_preserved(self):
        item = SimpleNamespace(
            normalized_payload={
                "name": "Logitech MeetUp 2",
                "brand": "Logitech",
                "model": "960-001681",
            }
        )
        self.assertLessEqual(len(VIEW_PLAN), 10)
        self.assertEqual(len(set(VIEW_PLAN)), len(VIEW_PLAN))
        prompt = generation_prompt(item, VIEW_PLAN[0])
        self.assertIn("960-001681", prompt)
        self.assertIn("Do not invent", prompt)
        self.assertIn("held for manual review instead of guessing", prompt)

    def test_legacy_prompt_phrase_do_not_invent_ports_remains(self):
        item = SimpleNamespace(
            identity_verified=True,
            specifications_verified=True,
            normalized_payload={
                "name": "MeetUp 2 Video Conferencing Camera",
                "brand": "Logitech",
                "manufacturer_sku": "960-001681",
                "specifications": {
                    "HDMI Out": "1",
                    "USB": "1 x Type C USB 3.1",
                },
                "package_contents": ["MeetUp 2", "Power supply"],
            },
        )
        candidate = SimpleNamespace(
            view_role=ImportMediaCandidate.VIEW_PORTS,
        )
        prompt = build_generation_prompt(item, candidate)
        self.assertIn("Do not invent ports", prompt)
        self.assertIn("HDMI Out", prompt)

    @patch("catalog_imports.services.media_review.duplicate_hash_exists", return_value=False)
    @patch("catalog_imports.services.media_review.review_asset_exists", return_value=True)
    def test_approval_accepts_legacy_candidate_without_provider_response(
        self, review_exists, duplicate_exists
    ):
        class DummyCandidate:
            kind = ImportMediaCandidate.KIND_GENERATION
            status = ImportMediaCandidate.STATUS_READY_REVIEW
            exact_identity_verified = False
            watermark_status = ImportMediaCandidate.WATERMARK_UNKNOWN
            source_identity_check_passed = False
            rights_status = ImportMediaCandidate.RIGHTS_UNKNOWN
            selected_for_product = False
            reviewed_at = None
            approved_by = None
            approved_at = None
            rejected_by = None
            rejected_at = None
            rejection_reason = ""
            last_error = ""

            def save(self):
                return None

        candidate = DummyCandidate()
        approve_candidate(
            candidate,
            actor=object(),
            exact_identity_verified=True,
            watermark_clear=True,
            source_identity_clear=True,
            rights_confirmed=True,
        )
        self.assertEqual(candidate.status, ImportMediaCandidate.STATUS_APPROVED)
        self.assertTrue(candidate.selected_for_product)
