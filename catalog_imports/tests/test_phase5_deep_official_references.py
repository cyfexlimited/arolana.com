from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from catalog_imports.models import ImportMediaCandidate
from catalog_imports.services.deep_official_references import (
    annotate_reference_url,
    discover_supplementary_links,
)
from catalog_imports.services.media_references import (
    _product_relevant_url,
    classify_reference_views,
    semantic_reference_decision,
)


class Phase510DeepOfficialReferenceTests(SimpleTestCase):
    def _item(self):
        return SimpleNamespace(
            normalized_payload={
                "brand": "Example",
                "name": "Widget 2 Video Conferencing Camera",
                "model": "Widget 2",
            },
            created_product=None,
        )

    def test_discovers_only_same_domain_support_resource_links(self):
        html = """
        <a href="/support/widget-2/setup-guide">Setup Guide</a>
        <a href="/content/widget-2-user-manual.pdf">User Manual</a>
        <a href="https://evil.example.net/widget-2/rear">Rear ports</a>
        <a href="/privacy">Privacy</a>
        """
        links = discover_supplementary_links(
            html,
            base_url="https://www.example.com/products/widget-2",
            official_domain="example.com",
        )
        self.assertIn("https://www.example.com/support/widget-2/setup-guide", links)
        self.assertIn("https://www.example.com/content/widget-2-user-manual.pdf", links)
        self.assertFalse(any("evil.example.net" in url for url in links))
        self.assertFalse(any(url.endswith("/privacy") for url in links))

    def test_annotated_support_image_does_not_unlock_back_without_visual_classification(self):
        item = self._item()
        raw = "https://resource.example.com/assets/generic-image-123.png"
        annotated = annotate_reference_url(
            raw,
            roles={"back", "ports_detail"},
            kind="physical",
            source="official-support",
        )
        self.assertTrue(_product_relevant_url(item, annotated))
        roles = classify_reference_views(annotated)
        self.assertIn(ImportMediaCandidate.VIEW_BACK, roles)
        self.assertIn(ImportMediaCandidate.VIEW_PORTS, roles)
        allowed, reason = semantic_reference_decision(
            item, annotated, ImportMediaCandidate.VIEW_BACK
        )
        self.assertFalse(allowed)
        self.assertIn("visually classified", reason)

    def test_annotated_scene_does_not_unlock_lifestyle_without_visual_classification(self):
        item = self._item()
        annotated = annotate_reference_url(
            "https://resource.example.com/assets/image-88.jpg",
            roles={"lifestyle"},
            kind="scene",
            source="official-support",
        )
        self.assertIn(
            ImportMediaCandidate.VIEW_LIFESTYLE,
            classify_reference_views(annotated),
        )
        allowed, reason = semantic_reference_decision(
            item, annotated, ImportMediaCandidate.VIEW_LIFESTYLE
        )
        self.assertFalse(allowed)
        self.assertIn("visually classified", reason)

    def test_unannotated_generic_image_is_not_trusted_for_exact_product(self):
        item = self._item()
        self.assertFalse(
            _product_relevant_url(
                item,
                "https://resource.example.com/assets/generic-image-123.png",
            )
        )
