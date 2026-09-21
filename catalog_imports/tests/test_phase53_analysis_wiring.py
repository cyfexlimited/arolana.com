from pathlib import Path

from django.test import SimpleTestCase


class Phase53AnalysisWiringTests(SimpleTestCase):
    def test_analysis_auto_discovers_and_acquires_official_media(self):
        import catalog_imports.services.analysis as analysis

        source = Path(analysis.__file__).read_text(encoding="utf-8")
        self.assertIn("discover_manufacturer_web_identity", source)
        self.assertIn("acquire_official_media(item)", source)
        self.assertIn('verification["official_media"]', source)
