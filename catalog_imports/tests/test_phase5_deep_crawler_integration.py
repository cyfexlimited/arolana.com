from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from catalog_imports.services.deep_official_references import deep_official_reference_urls


class Phase510DeepCrawlerIntegrationTests(SimpleTestCase):
    @patch("catalog_imports.services.deep_official_references.cache.get", return_value=None)
    @patch("catalog_imports.services.deep_official_references.cache.set")
    @patch("catalog_imports.services.deep_official_references.fetch_html")
    def test_identity_verified_support_page_contributes_view_annotated_image(
        self, fetch_html, cache_set, cache_get
    ):
        product_html = """
        <html><body>
          <a href="/support/widget-2/setup-guide">Setup guide</a>
        </body></html>
        """
        support_html = """
        <html><body>
          <h1>Widget 2 Video Conferencing Camera</h1>
          <p>Rear view and ports</p>
          <img src="/media/widget-rear.png" alt="Widget 2 rear view ports and connectors">
        </body></html>
        """
        fetch_html.side_effect = [
            SimpleNamespace(
                url="https://www.example.com/products/widget-2",
                text=product_html,
            ),
            SimpleNamespace(
                url="https://www.example.com/support/widget-2/setup-guide",
                text=support_html,
            ),
        ]

        item = SimpleNamespace(
            pk=4,
            normalized_payload={
                "name": "Widget 2 Video Conferencing Camera",
                "model": "Widget 2",
            },
            created_product=None,
        )
        evidence = SimpleNamespace(
            pk=9,
            url="https://www.example.com/products/widget-2",
        )

        urls = deep_official_reference_urls(
            item=item,
            manufacturer_evidences=[evidence],
            official_domain="example.com",
        )
        self.assertEqual(len(urls), 1)
        self.assertIn("widget-rear.png", urls[0])
        self.assertIn("arolana_verified=1", urls[0])
        self.assertIn("back", urls[0])
        self.assertIn("ports_detail", urls[0])
