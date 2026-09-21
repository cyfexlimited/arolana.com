from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from catalog_imports.models import ImportMediaCandidate
from catalog_imports.services.deep_official_references import (
    _extract_html_images,
)
from catalog_imports.services.media_references import (
    _looks_like_image_url,
    classify_reference_views,
    semantic_reference_decision,
)


class Phase512DelegatedCDNReferenceTests(SimpleTestCase):
    def _item(self):
        return SimpleNamespace(
            normalized_payload={
                "brand": "Example",
                "name": "Widget 2 Video Conferencing Camera",
                "model": "Widget 2",
            },
            created_product=None,
        )

    @patch(
        "catalog_imports.services.deep_official_references.fetch_binary"
    )
    def test_external_opaque_imgix_style_image_stays_blocked_without_visual_classification(
        self,
        fetch_binary,
    ):
        fetch_binary.return_value = SimpleNamespace(
            url=(
                "https://cdn.example-images.net/"
                "opaqueAssetKey?auto=compress%2Cformat"
            ),
            data=b"fake-image-bytes",
        )

        html = """
        <html><body>
          <h1>Widget 2 Video Conferencing Camera</h1>
          <h2>Input + Output</h2>
          <img
            src="https://cdn.example-images.net/opaqueAssetKey?auto=compress%2Cformat"
            alt="Image"
          >
        </body></html>
        """

        refs, text = _extract_html_images(
            html,
            page_url="https://hub.example.com/widget-2/ports",
            official_domain="example.com",
            source="official-support-seed",
        )

        self.assertEqual(len(refs), 1)
        self.assertIn("arolana_verified=1", refs[0])
        self.assertIn("ports_detail", refs[0])
        fetch_binary.assert_called_once()

        roles = classify_reference_views(refs[0])
        self.assertIn(ImportMediaCandidate.VIEW_PORTS, roles)

        allowed, reason = semantic_reference_decision(
            self._item(),
            refs[0],
            ImportMediaCandidate.VIEW_PORTS,
        )
        self.assertFalse(allowed)
        self.assertIn("visually classified", reason)

    @patch(
        "catalog_imports.services.deep_official_references.fetch_binary"
    )
    def test_logo_is_rejected_even_when_near_back_heading(
        self,
        fetch_binary,
    ):
        html = """
        <html><body>
          <h1>Widget 2 Video Conferencing Camera</h1>
          <h2>Back view</h2>
          <img
            src="https://partners.example.com/images/logo/Example_logo_black.png"
            alt="Example"
          >
        </body></html>
        """

        refs, _ = _extract_html_images(
            html,
            page_url="https://hub.example.com/widget-2/back",
            official_domain="example.com",
            source="official-support-seed",
        )

        self.assertEqual(refs, [])
        fetch_binary.assert_not_called()

    def test_unannotated_opaque_url_is_still_not_normal_reference(self):
        self.assertFalse(
            _looks_like_image_url(
                "https://cdn.example-images.net/opaqueAssetKey"
            )
        )
