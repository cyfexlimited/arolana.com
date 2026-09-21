from pathlib import Path

from django.template.loader import get_template
from django.test import SimpleTestCase


class Phase61AdminCompletionUITests(SimpleTestCase):
    def test_completion_template_compiles_and_has_product_admin_action(self):
        template = get_template(
            "admin/catalog_imports/importitem/admin_completion.html"
        )
        source = template.template.source
        self.assertIn("Open Product admin / finish fields", source)
        self.assertIn("Finish in Product admin", source)
        self.assertIn("does not approve, activate, or publish", source)

    def test_import_item_change_form_has_finish_button(self):
        template = get_template(
            "admin/catalog_imports/importitem/change_form.html"
        )
        source = template.template.source
        self.assertIn("Finish product draft", source)
        self.assertIn("catalog_imports_importitem_admin_completion", source)

    def test_admin_registers_completion_route(self):
        import catalog_imports.admin as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        self.assertIn("def admin_completion_view", source)
        self.assertIn("def admin_completion_status", source)
        self.assertIn("catalog_imports_importitem_admin_completion", source)
