from types import SimpleNamespace

from django.test import SimpleTestCase

from catalog_imports.services.media_profiles import candidate_display_label


class Phase51DisplayLabelTests(SimpleTestCase):
    def test_display_label_prefers_profile_metadata(self):
        candidate = SimpleNamespace(
            metadata={"display_label": "Model wearing item"},
            get_view_role_display=lambda: "Lifestyle",
            view_role="lifestyle",
        )
        self.assertEqual(candidate_display_label(candidate), "Model wearing item")
