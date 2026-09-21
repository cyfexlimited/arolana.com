from pathlib import Path

from django.test import SimpleTestCase


class Phase535AcquisitionWiringTests(SimpleTestCase):
    def test_official_media_acquisition_runs_semantic_classifier_before_support(self):
        import catalog_imports.services.official_media_acquisition as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        classifier_at = source.index("semantic_classification = classify_authoritative_evidence_images(item)")
        refs_at = source.index("refs = manufacturer_reference_urls(item)")
        support_at = source.index("support = reference_support_report(item)")

        self.assertLess(classifier_at, refs_at)
        self.assertLess(refs_at, support_at)
        self.assertIn('"semantic_classification": semantic_classification', source)

    def test_contextual_acquisition_preserves_semantic_context(self):
        import catalog_imports.services.official_media_acquisition as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        self.assertIn('"semantic_context": context', source)
