from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from catalog_imports.models import ImportMediaCandidate
from catalog_imports.services.deep_official_references import (
    _secondary_seed_urls,
    deep_official_reference_urls,
)
from catalog_imports.services.media_references import (
    classify_reference_views,
    semantic_reference_decision,
)


class Phase511OfficialSupportSeedTests(SimpleTestCase):
    def _item(self, secondary=""):
        return SimpleNamespace(
            pk=4,
            secondary_evidence_urls=secondary,
            normalized_payload={
                "brand": "Example",
                "name": "Widget 2 Video Conferencing Camera",
                "model": "Widget 2",
            },
            created_product=None,
        )

    def test_secondary_seed_urls_require_official_domain(self):
        item = self._item(
            "https://hub.example.com/widget-2/ports\n"
            "https://evil.example.net/widget-2/back\n"
        )
        urls = _secondary_seed_urls(item, "example.com")
        self.assertEqual(
            urls,
            ["https://hub.example.com/widget-2/ports"],
        )

    @patch(
        "catalog_imports.services.deep_official_references.cache.get",
        return_value=None,
    )
    @patch("catalog_imports.services.deep_official_references.cache.set")
    @patch("catalog_imports.services.deep_official_references.fetch_html")
    def test_heading_context_seed_does_not_unlock_ports_or_back_without_visual_classification(
        self,
        fetch_html,
        cache_set,
        cache_get,
    ):
        support_html = """
        <html><body>
          <h1>Widget 2 Video Conferencing Camera</h1>
          <h2>Input + Output / Button Functions</h2>
          <p>Rear view and ports. Power button on the back.</p>
          <img
            src="https://resource.example.com/media/widget-2-io.png"
            alt="Image"
          >
        </body></html>
        """
        fetch_html.return_value = SimpleNamespace(
            url="https://hub.example.com/widget-2/io",
            text=support_html,
        )
        item = self._item("https://hub.example.com/widget-2/io")
        evidence = SimpleNamespace(
            pk=9,
            url="https://www.example.com/products/widget-2",
        )

        urls = deep_official_reference_urls(
            item=item,
            manufacturer_evidences=[evidence],
            official_domain="example.com",
        )
        matches = [u for u in urls if "widget-2-io.png" in u]
        self.assertTrue(matches)

        roles = classify_reference_views(matches[0])
        self.assertIn(ImportMediaCandidate.VIEW_PORTS, roles)
        self.assertIn(ImportMediaCandidate.VIEW_BACK, roles)

        allowed, reason = semantic_reference_decision(
            item,
            matches[0],
            ImportMediaCandidate.VIEW_PORTS,
        )
        self.assertFalse(allowed)
        self.assertIn("visually classified", reason)

    @patch(
        "catalog_imports.services.deep_official_references.cache.get",
        return_value=None,
    )
    @patch("catalog_imports.services.deep_official_references.cache.set")
    @patch("catalog_imports.services.deep_official_references.fetch_html")
    def test_navigation_image_is_rejected(
        self,
        fetch_html,
        cache_set,
        cache_get,
    ):
        html = """
        <html><body>
          <h1>Widget 2 Video Conferencing Camera</h1>
          <h2>Meeting Room Setup</h2>
          <img
            src="https://resource.example.com/navigation/business/meeting-rooms.png"
            alt="Meeting rooms"
          >
        </body></html>
        """
        fetch_html.return_value = SimpleNamespace(
            url="https://hub.example.com/widget-2/setup",
            text=html,
        )
        item = self._item("https://hub.example.com/widget-2/setup")
        evidence = SimpleNamespace(
            pk=9,
            url="https://www.example.com/products/widget-2",
        )

        urls = deep_official_reference_urls(
            item=item,
            manufacturer_evidences=[evidence],
            official_domain="example.com",
        )
        self.assertFalse(any("/navigation/" in u for u in urls))

    @patch(
        "catalog_imports.services.deep_official_references.cache.get",
        return_value=None,
    )
    @patch("catalog_imports.services.deep_official_references.cache.set")
    @patch("catalog_imports.services.deep_official_references.fetch_html")
    def test_whats_in_box_seed_supplies_package_contents(
        self,
        fetch_html,
        cache_set,
        cache_get,
    ):
        html = """
        <html><body>
          <h1>Widget 2 Video Conferencing Camera</h1>
          <h2>What's in the box</h2>
          <img
            src="https://resource.example.com/media/widget-2-box-contents.png"
            alt="Image"
          >
        </body></html>
        """
        fetch_html.return_value = SimpleNamespace(
            url="https://hub.example.com/widget-2/box",
            text=html,
        )
        item = self._item("https://hub.example.com/widget-2/box")
        evidence = SimpleNamespace(
            pk=9,
            url="https://www.example.com/products/widget-2",
        )

        urls = deep_official_reference_urls(
            item=item,
            manufacturer_evidences=[evidence],
            official_domain="example.com",
        )
        matches = [u for u in urls if "box-contents" in u]
        self.assertTrue(matches)
        self.assertIn(
            ImportMediaCandidate.VIEW_PACKAGE,
            classify_reference_views(matches[0]),
        )
