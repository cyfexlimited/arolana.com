from django.test import SimpleTestCase

from catalog_imports.services.deep_official_references import _role_semantics


class Phase5121SemanticNormalizationTests(SimpleTestCase):
    def test_input_plus_output_matches_ports(self):
        roles, kind = _role_semantics("Input + Output")
        self.assertIn("ports_detail", roles)
        self.assertEqual(kind, "physical")

    def test_input_slash_output_matches_ports(self):
        roles, kind = _role_semantics("Input/Output")
        self.assertIn("ports_detail", roles)
        self.assertEqual(kind, "physical")

    def test_input_ampersand_output_matches_ports(self):
        roles, kind = _role_semantics("Input & Output")
        self.assertIn("ports_detail", roles)
        self.assertEqual(kind, "physical")

    def test_whats_in_the_box_still_matches_package(self):
        roles, kind = _role_semantics("What's in the box")
        self.assertIn("package_contents", roles)
        self.assertEqual(kind, "package")
