from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from catalog_imports.models import ImportMediaCandidate
from catalog_imports.services.media_generation import MediaGenerationError, materialize_candidate
from catalog_imports.services.media_references import ReferenceViewHold


class Phase508GenerationGateTests(SimpleTestCase):
    def test_reference_hold_happens_before_provider_is_created(self):
        product = SimpleNamespace(is_active=False)
        item = SimpleNamespace(
            created_product_id=90,
            created_product=product,
            identity_verified=True,
            specifications_verified=True,
        )
        candidate = MagicMock()
        candidate.item = item
        candidate.kind = ImportMediaCandidate.KIND_GENERATION
        candidate.status = ImportMediaCandidate.STATUS_PLANNED
        candidate.view_role = ImportMediaCandidate.VIEW_BACK
        candidate.generation_attempts = 0

        with patch(
            "catalog_imports.services.media_generation.build_generation_prompt",
            return_value="safe prompt",
        ), patch(
            "catalog_imports.services.media_generation.review_storage_alias",
            return_value="catalog_import_reviews",
        ), patch(
            "catalog_imports.services.media_generation.select_generation_reference_urls",
            side_effect=ReferenceViewHold(
                "No trustworthy official manufacturer rear/back reference was discovered. "
                "Generation is blocked to prevent invented physical geometry."
            ),
        ), patch(
            "catalog_imports.services.media_generation.get_provider"
        ) as get_provider:
            with self.assertRaises(MediaGenerationError):
                materialize_candidate(candidate)

        get_provider.assert_not_called()
        self.assertEqual(candidate.status, ImportMediaCandidate.STATUS_FAILED)
        self.assertEqual(candidate.generation_attempts, 0)
