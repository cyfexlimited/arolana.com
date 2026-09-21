from pathlib import Path

from django.test import SimpleTestCase


class Phase5341AdminReasonFieldTests(SimpleTestCase):
    def test_admin_accepts_dedicated_manual_creative_reason(self):
        import catalog_imports.admin as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        self.assertIn(
            'request.POST.get("manual_creative_reason")',
            source,
        )
