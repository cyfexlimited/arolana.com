from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import TestCase

from catalog_imports.models import ImportMediaCandidate
from catalog_imports.services.media_generation import materialize_candidate
from catalog_imports.services.media_reference_preserving import ReferencePreservingResult


class Phase514TechnicalPromptBypassTests(TestCase):
    def test_package_reference_preserving_generation_does_not_require_text_package_contents(self):
        product = SimpleNamespace(is_active=False)
        item = SimpleNamespace(
            created_product_id=90,
            created_product=product,
            identity_verified=True,
            specifications_verified=True,
        )

        candidate = MagicMock()
        candidate.item = item
        candidate.item_id = 4
        candidate.pk = 99
        candidate.kind = ImportMediaCandidate.KIND_GENERATION
        candidate.status = ImportMediaCandidate.STATUS_FAILED
        candidate.view_role = ImportMediaCandidate.VIEW_PACKAGE
        candidate.generation_attempts = 0
        candidate.reference_urls = []
        candidate.metadata = {}
        candidate.provider_response = {}
        candidate.attached_product_image = None

        refs = [
            "https://cdn.example.com/package"
            "#arolana_verified=1&arolana_view=package_contents&arolana_kind=package"
        ]
        local_result = ReferencePreservingResult(
            content=b"package-reference-layout",
            provider_asset_id="local-package",
            metadata={"render_mode": "reference_preserving", "ai_redraw": False},
        )
        stored = SimpleNamespace(
            storage_alias="default",
            storage_name="catalog-imports/review/package.webp",
            original_name="package.webp",
            mime_type="image/webp",
            width=800,
            height=800,
            file_size=1000,
            sha256="packagehash",
        )

        with patch(
            "catalog_imports.services.media_generation.build_generation_prompt"
        ) as build_prompt, patch(
            "catalog_imports.services.media_generation.review_storage_alias",
            return_value="default",
        ), patch(
            "catalog_imports.services.media_generation.select_generation_reference_urls",
            return_value=refs,
        ), patch(
            "catalog_imports.services.media_generation.record_reference_trace",
            return_value=refs,
        ), patch(
            "catalog_imports.services.media_generation.render_reference_preserving_asset",
            return_value=local_result,
        ), patch(
            "catalog_imports.services.media_generation.save_review_asset",
            return_value=stored,
        ), patch(
            "catalog_imports.services.media_generation.validate_materialized_candidate",
            return_value=[],
        ), patch(
            "catalog_imports.services.media_generation.duplicate_hash_exists",
            return_value=False,
        ), patch(
            "catalog_imports.services.media_generation.get_provider"
        ) as get_provider:
            materialize_candidate(candidate)

        build_prompt.assert_not_called()
        get_provider.assert_not_called()
        self.assertEqual(candidate.provider_key, "reference-preserving")
