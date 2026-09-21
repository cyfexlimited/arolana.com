from pathlib import Path

from django.test import SimpleTestCase


class Phase536VisualClassifierSafetySourceTests(SimpleTestCase):
    def test_service_is_authoritative_only_cached_and_bounded(self):
        import catalog_imports.services.official_reference_visual_classifier as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        self.assertIn("role=ImportEvidence.ROLE_MANUFACTURER", source)
        self.assertIn("is_authoritative=True", source)
        self.assertIn("CATALOG_IMPORT_VISUAL_CLASSIFIER_MAX_IMAGES", source)
        self.assertIn("def _already_done", source)
        self.assertIn("marketing_graphic", source)
        self.assertIn("ports_require_visible_ports", source)
        self.assertIn("package_requires_visible_package", source)
