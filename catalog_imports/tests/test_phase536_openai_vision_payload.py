from pathlib import Path

from django.test import SimpleTestCase


class Phase536OpenAIVisionPayloadTests(SimpleTestCase):
    def test_responses_payload_uses_input_image_and_json_only_contract(self):
        import catalog_imports.services.official_reference_visual_classifier as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        self.assertIn('"type": "input_image"', source)
        self.assertIn('"detail": "high"', source)
        self.assertIn("Return JSON ONLY", source)
        self.assertIn("gpt-5.6-luna", source)
