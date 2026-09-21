from pathlib import Path

from django.test import SimpleTestCase


class Phase65StrictRoleReferenceGateTests(SimpleTestCase):
    def test_front_is_a_strict_role(self):
        import catalog_imports.services.media_references as module

        self.assertIn(
            module.ImportMediaCandidate.VIEW_FRONT,
            module._STRICT_VIEW_ROLES,
        )
        self.assertIn(
            module.ImportMediaCandidate.VIEW_FRONT,
            module._STRICT_VISUAL_REFERENCE_ROLES,
        )

    def test_generic_gallery_no_longer_promotes_to_front(self):
        import catalog_imports.services.media_references as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        generic_block_start = source.index(
            "if any(hint.strip"
        )
        generic_block = source[generic_block_start:generic_block_start + 300]
        self.assertIn("VIEW_MAIN", generic_block)
        self.assertNotIn("VIEW_FRONT", generic_block)

    def test_front_main_fallback_removed(self):
        import catalog_imports.services.media_references as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        self.assertNotIn(
            "Front is allowed to fall back to a clean exact-product gallery/hero image.",
            source,
        )
