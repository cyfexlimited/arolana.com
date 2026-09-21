from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from catalog_imports.models import ImportMediaCandidate
from catalog_imports.services.media_references import (
    ReferenceViewHold,
    classify_reference_views,
    reference_support_for_view,
    select_generation_reference_urls,
)


class Phase508ViewSpecificReferenceTests(SimpleTestCase):
    def test_generic_gallery_supports_front_but_not_hidden_side_or_back(self):
        url = (
            "https://resource.example.com/content/dam/example/widget-2/"
            "gallery/widget-2-graphite-01.png"
        )
        with patch(
            "catalog_imports.services.media_references.manufacturer_reference_urls",
            return_value=[url],
        ), patch(
            "catalog_imports.services.media_references.rank_reference_urls",
            return_value=[url],
        ):
            item = SimpleNamespace()
            front = reference_support_for_view(item, ImportMediaCandidate.VIEW_FRONT)
            side = reference_support_for_view(item, ImportMediaCandidate.VIEW_SIDE)
            back = reference_support_for_view(item, ImportMediaCandidate.VIEW_BACK)

        self.assertFalse(front["supported"])
        self.assertFalse(side["supported"])
        self.assertFalse(back["supported"])

    def test_explicit_left_right_back_and_port_assets_are_classified(self):
        left = "https://m.example/product/widget-2-left-angle.png"
        right = "https://m.example/product/widget-2-right-angle.png"
        back = "https://m.example/product/widget-2-rear-view.png"
        ports = "https://m.example/product/widget-2-ethernet-port-detail.png"

        self.assertIn(
            ImportMediaCandidate.VIEW_LEFT,
            classify_reference_views(left),
        )
        self.assertIn(
            ImportMediaCandidate.VIEW_RIGHT,
            classify_reference_views(right),
        )
        self.assertIn(
            ImportMediaCandidate.VIEW_BACK,
            classify_reference_views(back),
        )
        self.assertIn(
            ImportMediaCandidate.VIEW_PORTS,
            classify_reference_views(ports),
        )

    def test_unsupported_hidden_view_raises_hold_before_generation(self):
        url = (
            "https://resource.example.com/content/dam/example/widget-2/"
            "gallery/widget-2-graphite-01.png"
        )
        with patch(
            "catalog_imports.services.media_references.manufacturer_reference_urls",
            return_value=[url],
        ), patch(
            "catalog_imports.services.media_references.rank_reference_urls",
            return_value=[url],
        ):
            with self.assertRaises(ReferenceViewHold) as ctx:
                select_generation_reference_urls(
                    SimpleNamespace(),
                    ImportMediaCandidate.VIEW_BACK,
                    max_refs=3,
                )
        self.assertIn("blocked", str(ctx.exception).lower())
        self.assertIn("generation is blocked", str(ctx.exception).lower())

    def test_ports_view_uses_only_explicit_port_reference(self):
        front = "https://m.example/product/widget-2-gallery-front.png"
        port = "https://m.example/product/widget-2-ethernet-port-detail.png"
        with patch(
            "catalog_imports.services.media_references.manufacturer_reference_urls",
            return_value=[front, port],
        ), patch(
            "catalog_imports.services.media_references.rank_reference_urls",
            return_value=[front, port],
        ):
            with self.assertRaises(ReferenceViewHold):
                select_generation_reference_urls(
                    SimpleNamespace(),
                    ImportMediaCandidate.VIEW_PORTS,
                    max_refs=3,
                )

    def test_lifestyle_requires_scene_reference(self):
        front = "https://m.example/product/widget-2-gallery-front.png"
        scene = "https://m.example/product/widget-2-room-solution-office.png"
        with patch(
            "catalog_imports.services.media_references.manufacturer_reference_urls",
            return_value=[front, scene],
        ), patch(
            "catalog_imports.services.media_references.rank_reference_urls",
            return_value=[front, scene],
        ):
            with self.assertRaises(ReferenceViewHold):
                select_generation_reference_urls(
                    SimpleNamespace(),
                    ImportMediaCandidate.VIEW_LIFESTYLE,
                    max_refs=3,
                )
