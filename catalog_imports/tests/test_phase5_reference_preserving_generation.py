from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import TestCase

from catalog_imports.models import ImportMediaCandidate
from catalog_imports.services.media_generation import materialize_candidate
from catalog_imports.services.media_reference_preserving import (
    ReferencePreservingResult,
)


class Phase513TechnicalGenerationModeTests(TestCase):
    def test_ports_materialization_never_creates_image_provider(self):
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
        candidate.pk = 88
        candidate.kind = ImportMediaCandidate.KIND_GENERATION
        candidate.status = ImportMediaCandidate.STATUS_PLANNED
        candidate.view_role = ImportMediaCandidate.VIEW_PORTS
        candidate.generation_attempts = 0
        candidate.reference_urls = []
        candidate.metadata = {}
        candidate.provider_response = {}
        candidate.attached_product_image = None

        stored = SimpleNamespace(
            storage_alias="default",
            storage_name="catalog-imports/review/example.webp",
            original_name="ports_detail.webp",
            mime_type="image/webp",
            width=800,
            height=800,
            file_size=12345,
            sha256="abc123",
        )

        local_result = ReferencePreservingResult(
            content=b"local-reference-preserving-image",
            provider_asset_id="local-123",
            metadata={
                "render_mode": "reference_preserving",
                "ai_redraw": False,
            },
        )

        refs = [
            "https://cdn.example.com/ports"
            "#arolana_verified=1&arolana_view=ports_detail"
        ]

        with patch(
            "catalog_imports.services.media_generation.build_generation_prompt",
            return_value="normal prompt that should not be sent to AI",
        ), patch(
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
        ) as local_renderer, patch(
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
            result = materialize_candidate(candidate)

        get_provider.assert_not_called()
        local_renderer.assert_called_once()
        self.assertIs(result, candidate)
        self.assertEqual(candidate.provider_key, "reference-preserving")
        self.assertEqual(
            candidate.provider_response["_arolana_render_mode"],
            "reference_preserving",
        )
        self.assertFalse(candidate.provider_response["_arolana_ai_redraw"])
        self.assertEqual(
            candidate.status,
            ImportMediaCandidate.STATUS_READY_REVIEW,
        )

    def test_lifestyle_still_uses_normal_provider_path(self):
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
        candidate.pk = 89
        candidate.kind = ImportMediaCandidate.KIND_GENERATION
        candidate.status = ImportMediaCandidate.STATUS_PLANNED
        candidate.view_role = ImportMediaCandidate.VIEW_LIFESTYLE
        candidate.generation_attempts = 0
        candidate.reference_urls = []
        candidate.metadata = {}
        candidate.provider_response = {}
        candidate.attached_product_image = None

        stored = SimpleNamespace(
            storage_alias="default",
            storage_name="catalog-imports/review/lifestyle.webp",
            original_name="lifestyle.webp",
            mime_type="image/webp",
            width=800,
            height=800,
            file_size=12345,
            sha256="def456",
        )

        provider_result = SimpleNamespace(
            content=b"generated-image",
            provider_asset_id="req-123",
            metadata={"model": "test-model"},
        )
        provider = MagicMock()
        provider.key = "openai"
        provider.generate.return_value = provider_result

        refs = ["https://resource.example.com/lifestyle.png"]

        with patch(
            "catalog_imports.services.media_generation.build_generation_prompt",
            return_value="lifestyle prompt",
        ), patch(
            "catalog_imports.services.media_generation.review_storage_alias",
            return_value="default",
        ), patch(
            "catalog_imports.services.media_generation.select_generation_reference_urls",
            return_value=refs,
        ), patch(
            "catalog_imports.services.media_generation.record_reference_trace",
            return_value=refs,
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
            "catalog_imports.services.media_generation.get_provider",
            return_value=provider,
        ) as get_provider, patch(
            "catalog_imports.services.media_generation.render_reference_preserving_asset"
        ) as local_renderer:
            materialize_candidate(candidate)

        get_provider.assert_called_once()
        provider.generate.assert_called_once()
        local_renderer.assert_not_called()
        self.assertEqual(candidate.provider_key, "openai")
        self.assertEqual(
            candidate.provider_response["_arolana_render_mode"],
            "generative",
        )
        self.assertTrue(candidate.provider_response["_arolana_ai_redraw"])
