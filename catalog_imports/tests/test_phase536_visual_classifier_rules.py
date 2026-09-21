from django.test import SimpleTestCase

from catalog_imports.models import ImportMediaCandidate
from catalog_imports.services.official_reference_visual_classifier import (
    _accepted_roles,
)


class Phase536VisualClassifierRuleTests(SimpleTestCase):
    def test_clear_high_confidence_back_is_accepted(self):
        roles = _accepted_roles({
            "primary_role": "back",
            "confidence": 0.98,
            "exact_product_visible": True,
            "view_is_clear": True,
            "marketing_graphic": False,
            "ports_visible": False,
        })
        self.assertIn(ImportMediaCandidate.VIEW_BACK, roles)

    def test_ports_need_explicit_visible_ports_and_high_confidence(self):
        blocked = _accepted_roles({
            "primary_role": "ports_detail",
            "confidence": 0.99,
            "exact_product_visible": True,
            "view_is_clear": True,
            "marketing_graphic": False,
            "ports_visible": False,
        })
        allowed = _accepted_roles({
            "primary_role": "ports_detail",
            "confidence": 0.99,
            "exact_product_visible": True,
            "view_is_clear": True,
            "marketing_graphic": False,
            "ports_visible": True,
        })
        self.assertNotIn(ImportMediaCandidate.VIEW_PORTS, blocked)
        self.assertIn(ImportMediaCandidate.VIEW_PORTS, allowed)

    def test_package_needs_visible_package_or_contents(self):
        roles = _accepted_roles({
            "primary_role": "package_contents",
            "confidence": 0.99,
            "exact_product_visible": True,
            "view_is_clear": True,
            "marketing_graphic": False,
            "package_visible": False,
            "package_contents_visible": False,
        })
        self.assertEqual(roles, [])

    def test_marketing_graphic_never_unlocks_geometry(self):
        roles = _accepted_roles({
            "primary_role": "side",
            "confidence": 1.0,
            "exact_product_visible": True,
            "view_is_clear": True,
            "marketing_graphic": True,
        })
        self.assertEqual(roles, [])

    def test_clear_back_with_visible_ports_can_support_both(self):
        roles = _accepted_roles({
            "primary_role": "back",
            "confidence": 0.99,
            "exact_product_visible": True,
            "view_is_clear": True,
            "marketing_graphic": False,
            "ports_visible": True,
        })
        self.assertIn(ImportMediaCandidate.VIEW_BACK, roles)
        self.assertIn(ImportMediaCandidate.VIEW_PORTS, roles)
