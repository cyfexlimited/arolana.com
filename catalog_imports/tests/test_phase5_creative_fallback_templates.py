from pathlib import Path

from django.test import SimpleTestCase


class Phase514CreativeFallbackTemplateTests(SimpleTestCase):
    def test_generation_template_exposes_creative_fallback_action(self):
        path = (
            Path(__file__).resolve().parents[1]
            / "templates/admin/catalog_imports/importitem/generate_media.html"
        )
        text = path.read_text(encoding="utf-8")
        self.assertIn("Generate creative fallback", text)
        self.assertIn("Unverified perspective", text)
        self.assertIn("Generate all verified queued media", text)

    def test_review_template_labels_and_acknowledges_creative_fallback(self):
        path = (
            Path(__file__).resolve().parents[1]
            / "templates/admin/catalog_imports/importitem/media_review.html"
        )
        text = path.read_text(encoding="utf-8")
        self.assertIn("CREATIVE FALLBACK — UNVERIFIED PERSPECTIVE", text)
        self.assertIn("creative_fallback_ack", text)
        self.assertIn("Download / edit creative fallback", text)
        self.assertIn("Official manufacturer reference", text)
        self.assertIn("candidate.reference_urls", text)
        self.assertIn("row.reference_urls_used", text)
