from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from catalog_imports.models import ImportMediaCandidate
from catalog_imports.services.deep_official_references import (
    annotate_reference_url,
)
from catalog_imports.services.media_references import (
    rank_reference_urls,
    reference_support_for_view,
)


class Phase5122TrustedCDNRankingTests(SimpleTestCase):
    def _item(self):
        return SimpleNamespace(
            normalized_payload={
                "brand": "Example",
                "name": "Widget 2 Video Conferencing Camera",
                "model": "Widget 2",
            },
            created_product=None,
        )

    def test_rank_keeps_verified_opaque_ports_reference(self):
        url = annotate_reference_url(
            "https://cdn.example-images.net/opaquePortsKey?auto=format",
            roles={"ports_detail"},
            kind="physical",
            source="official-support-seed",
        )

        ranked = rank_reference_urls(
            [url],
            ImportMediaCandidate.VIEW_PORTS,
            visual_score_func=lambda _url: 0.0,
        )

        self.assertEqual(ranked, [url])

    def test_rank_still_drops_unannotated_opaque_url(self):
        url = "https://cdn.example-images.net/opaquePortsKey?auto=format"

        ranked = rank_reference_urls(
            [url],
            ImportMediaCandidate.VIEW_PORTS,
            visual_score_func=lambda _url: 0.0,
        )

        self.assertEqual(ranked, [])

    @patch(
        "catalog_imports.services.media_references.manufacturer_reference_urls"
    )
    def test_ports_support_accepts_verified_opaque_reference(
        self,
        manufacturer_reference_urls,
    ):
        url = annotate_reference_url(
            "https://cdn.example-images.net/opaquePortsKey?auto=format",
            roles={"ports_detail"},
            kind="physical",
            source="official-support-seed",
        )
        manufacturer_reference_urls.return_value = [url]

        report = reference_support_for_view(
            self._item(),
            ImportMediaCandidate.VIEW_PORTS,
        )

        self.assertFalse(report["supported"])
        self.assertEqual(report["eligible_urls"], [])

    @patch(
        "catalog_imports.services.media_references.manufacturer_reference_urls"
    )
    def test_package_support_accepts_verified_opaque_reference(
        self,
        manufacturer_reference_urls,
    ):
        url = annotate_reference_url(
            "https://cdn.example-images.net/opaquePackageKey?auto=format",
            roles={"package_contents"},
            kind="package",
            source="official-support-seed",
        )
        manufacturer_reference_urls.return_value = [url]

        report = reference_support_for_view(
            self._item(),
            ImportMediaCandidate.VIEW_PACKAGE,
        )

        self.assertFalse(report["supported"])
        self.assertEqual(report["eligible_urls"], [])
