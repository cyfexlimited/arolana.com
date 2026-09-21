import inspect
import re

from django.test import SimpleTestCase


class Phase524TextGroundedActionUITests(SimpleTestCase):
    def test_admin_does_not_require_visual_fallback_refs_for_text_grounded_creative(self):
        # Assert behaviorally important source tokens without depending on the
        # exact indentation/newline layout of admin.py.
        import catalog_imports.admin as admin_module

        source = inspect.getsource(
            admin_module.ImportItemAdmin.generate_media_view
        )
        normalized = re.sub(r"\s+", " ", source)

        self.assertIn(
            'text_grounded_creative = bool( capability.get("text_grounded_creative") )',
            normalized,
        )
        self.assertRegex(
            normalized,
            r"creative_available\s*=\s*bool\(\s*capability\.get\(\"available\"\)"
            r"\s*and\s*\(\s*fallback_refs\s*or\s*text_grounded_creative\s*\)\s*\)",
        )

    def test_generate_template_exposes_text_grounded_button_and_warning(self):
        from django.template.loader import get_template

        template = get_template(
            "admin/catalog_imports/importitem/generate_media.html"
        )
        source = template.template.source
        self.assertIn("Generate text-grounded creative", source)
        self.assertIn("verified manufacturer", source)
        self.assertIn("not manufacturer-verified", source)
