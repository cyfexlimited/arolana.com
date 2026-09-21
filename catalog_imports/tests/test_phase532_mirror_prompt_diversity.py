from pathlib import Path

from django.test import SimpleTestCase


class Phase532MirrorPromptTests(SimpleTestCase):
    def test_mirror_prompt_requests_store_press_and_host_diversity(self):
        import catalog_imports.services.web_evidence as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        self.assertIn("Prioritize HOST DIVERSITY", source)
        self.assertIn("official brand-owned online store product pages", source)
        self.assertIn("press-centre", source)
        self.assertIn("up to 12 strong exact-model pages", source)
