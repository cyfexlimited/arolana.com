from pathlib import Path

from django.test import SimpleTestCase


class Phase536VisualClassifierWiringTests(SimpleTestCase):
    def test_acquisition_runs_visual_classifier_before_reference_support(self):
        import catalog_imports.services.official_media_acquisition as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        visual_at = source.index(
            "visual_classification = classify_authoritative_evidence_images_visual(item)"
        )
        refs_at = source.index("refs = manufacturer_reference_urls(item)")
        support_at = source.index("support = reference_support_report(item)")

        self.assertLess(visual_at, refs_at)
        self.assertLess(refs_at, support_at)
        self.assertIn('"visual_classification": visual_classification', source)
