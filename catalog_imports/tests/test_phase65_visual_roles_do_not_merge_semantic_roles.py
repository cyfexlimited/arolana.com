from pathlib import Path

from django.test import SimpleTestCase


class Phase65VisualRoleIsolationTests(SimpleTestCase):
    def test_visual_classifier_does_not_merge_semantic_roles_as_visual_proof(self):
        import catalog_imports.services.official_reference_visual_classifier as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        self.assertIn("visual_roles = set(accepted)", source)
        self.assertNotIn("merged_roles.update(entry.get(\"semantic_roles\")", source)
        self.assertIn('source="official-visual-classifier"', source)
