from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from catalog_imports.services.deep_official_references import (
    annotate_reference_url,
)
from catalog_imports.services.media_references import manufacturer_reference_urls


class Phase512ManufacturerDeepReferenceTests(SimpleTestCase):
    @patch(
        "catalog_imports.services.media_references._official_manufacturer_evidence",
        return_value=[],
    )
    @patch(
        "catalog_imports.services.media_references._verification_profile"
    )
    @patch(
        "catalog_imports.services.deep_official_references.deep_official_reference_urls"
    )
    def test_verified_annotated_opaque_cdn_reference_is_not_dropped(
        self,
        deep_urls,
        verification_profile,
        evidence_records,
    ):
        verification_profile.return_value = SimpleNamespace(
            official_domain="example.com"
        )
        deep_urls.return_value = [
            annotate_reference_url(
                "https://cdn.example-images.net/opaqueAssetKey?auto=format",
                roles={"ports_detail"},
                kind="physical",
                source="official-support-seed",
            )
        ]

        item = SimpleNamespace(
            normalized_payload={
                "brand": "Example",
                "name": "Widget 2",
                "model": "Widget 2",
            },
            created_product=None,
        )

        urls = manufacturer_reference_urls(item)
        self.assertEqual(len(urls), 1)
        self.assertIn("opaqueAssetKey", urls[0])
        self.assertIn("arolana_verified=1", urls[0])
