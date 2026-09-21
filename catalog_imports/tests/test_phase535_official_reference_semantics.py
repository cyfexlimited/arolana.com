from django.test import SimpleTestCase

from catalog_imports.models import ImportMediaCandidate
from catalog_imports.services.official_reference_semantics import (
    classify_image_entry,
    classify_payload_images,
)


class Phase535OfficialReferenceSemanticTests(SimpleTestCase):
    def test_ports_controls_are_classified_from_exact_official_context(self):
        result = classify_image_entry({
            "url": "https://cdn.sony.example/pxw-z200-rear.jpg",
            "semantic_context": (
                "PXW-Z200 rear view showing 12G-SDI, HDMI output, XLR audio "
                "inputs, USB-C and RJ45 Ethernet connectors"
            ),
        })
        self.assertTrue(result["classified"])
        self.assertIn(
            ImportMediaCandidate.VIEW_PORTS,
            result["roles"],
        )
        self.assertIn(
            ImportMediaCandidate.VIEW_BACK,
            result["roles"],
        )

    def test_package_requires_explicit_box_contents_signal(self):
        result = classify_image_entry({
            "url": "https://manufacturer.example/pxw-z200-kit.jpg",
            "alt_text": "PXW-Z200 what's in the box and included accessories",
        })
        self.assertIn(
            ImportMediaCandidate.VIEW_PACKAGE,
            result["roles"],
        )
        self.assertEqual(result["kind"], "package")

    def test_side_and_top_views_are_explicit(self):
        side = classify_image_entry({
            "url": "https://manufacturer.example/pxw-z200-side.jpg",
            "alt_text": "PXW-Z200 side profile view",
        })
        top = classify_image_entry({
            "url": "https://manufacturer.example/pxw-z200-top.jpg",
            "alt_text": "PXW-Z200 top view from above",
        })
        self.assertIn(ImportMediaCandidate.VIEW_SIDE, side["roles"])
        self.assertIn(ImportMediaCandidate.VIEW_TOP, top["roles"])

    def test_generic_promo_graphic_does_not_verify_hidden_geometry(self):
        result = classify_image_entry({
            "url": "https://manufacturer.example/campaign-banner.jpg",
            "alt_text": "PXW-Z200 promotional banner and feature graphic",
        })
        self.assertNotIn(ImportMediaCandidate.VIEW_BACK, result["roles"])
        self.assertNotIn(ImportMediaCandidate.VIEW_PORTS, result["roles"])

    def test_explicit_role_hint_is_preserved_and_annotated(self):
        payload, summary = classify_payload_images({
            "images": [{
                "reference_url": "https://manufacturer.example/z200-package.jpg",
                "role_hint": "package_contents",
                "alt_text": "PXW-Z200 included items",
            }]
        })
        ref = payload["images"][0]["reference_url"]
        self.assertIn("arolana_verified=1", ref)
        self.assertIn("package_contents", ref)
        self.assertEqual(summary["images_classified"], 1)
