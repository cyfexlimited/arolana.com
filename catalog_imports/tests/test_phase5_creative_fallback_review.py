from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from catalog_imports.services.media_review import MediaReviewError, approve_candidate


class Phase514CreativeApprovalTests(SimpleTestCase):
    @patch(
        "catalog_imports.services.media_review.review_asset_exists",
        return_value=True,
    )
    @patch(
        "catalog_imports.services.media_review.duplicate_hash_exists",
        return_value=False,
    )
    def test_creative_fallback_requires_extra_ack(
        self,
        duplicate,
        exists,
    ):
        candidate = SimpleNamespace(
            kind="generation",
            status="ready_review",
            provider_response={"_arolana_creative_fallback": True},
        )

        with self.assertRaises(MediaReviewError) as ctx:
            approve_candidate(
                candidate,
                actor=None,
                exact_identity_verified=True,
                watermark_clear=True,
                source_identity_clear=True,
                rights_confirmed=True,
                creative_fallback_ack=False,
            )

        self.assertIn("Creative fallback requires explicit confirmation", str(ctx.exception))
