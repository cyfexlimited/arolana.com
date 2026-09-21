import io
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from catalog_imports.models import ImportMediaCandidate
from catalog_imports.services.media_reference_preserving import (
    is_reference_preserving_view,
    render_reference_preserving_asset,
)


class Phase513ReferencePreservingRendererTests(SimpleTestCase):
    def _png(self, size=(400, 200), marker=(80, 40, 160, 120)):
        from PIL import Image, ImageDraw

        image = Image.new("RGB", size, "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle(marker, fill="black")
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        return buf.getvalue()

    def test_geometry_sensitive_views_use_reference_preserving_mode(self):
        self.assertTrue(is_reference_preserving_view(ImportMediaCandidate.VIEW_PORTS))
        self.assertTrue(is_reference_preserving_view(ImportMediaCandidate.VIEW_BACK))
        self.assertTrue(is_reference_preserving_view(ImportMediaCandidate.VIEW_TOP))
        self.assertTrue(is_reference_preserving_view(ImportMediaCandidate.VIEW_PACKAGE))
        self.assertTrue(is_reference_preserving_view(ImportMediaCandidate.VIEW_SIDE))
        self.assertFalse(is_reference_preserving_view(ImportMediaCandidate.VIEW_MAIN))
        self.assertFalse(is_reference_preserving_view(ImportMediaCandidate.VIEW_FRONT))
        self.assertFalse(is_reference_preserving_view(ImportMediaCandidate.VIEW_LIFESTYLE))

    @patch(
        "catalog_imports.services.media_reference_preserving.fetch_binary"
    )
    def test_renderer_is_local_square_and_records_no_ai_redraw(self, fetch_binary):
        raw = self._png()
        fetch_binary.return_value = SimpleNamespace(
            url="https://cdn.example.com/ports-image",
            content_type="image/png",
            data=raw,
        )

        result = render_reference_preserving_asset(
            reference_urls=[
                "https://cdn.example.com/ports-image"
                "#arolana_verified=1&arolana_view=ports_detail"
            ],
            view_role=ImportMediaCandidate.VIEW_PORTS,
            size="1024x1024",
        )

        from PIL import Image

        image = Image.open(io.BytesIO(result.content))
        self.assertEqual(image.size, (1024, 1024))
        self.assertEqual(result.metadata["render_mode"], "reference_preserving")
        self.assertFalse(result.metadata["ai_redraw"])
        self.assertFalse(result.metadata["references"][0]["cropped"])
        self.assertFalse(result.metadata["references"][0]["warped"])
        self.assertFalse(result.metadata["references"][0]["inpainted"])

    @patch(
        "catalog_imports.services.media_reference_preserving.fetch_binary"
    )
    def test_two_ports_references_are_both_preserved(self, fetch_binary):
        first = self._png(marker=(40, 40, 120, 120))
        second = self._png(marker=(240, 40, 340, 120))
        fetch_binary.side_effect = [
            SimpleNamespace(
                url="https://cdn.example.com/one",
                content_type="image/png",
                data=first,
            ),
            SimpleNamespace(
                url="https://cdn.example.com/two",
                content_type="image/png",
                data=second,
            ),
        ]

        result = render_reference_preserving_asset(
            reference_urls=[
                "https://cdn.example.com/one",
                "https://cdn.example.com/two",
            ],
            view_role=ImportMediaCandidate.VIEW_PORTS,
            size="1024x1024",
        )

        self.assertEqual(result.metadata["reference_count"], 2)
        self.assertEqual(len(result.metadata["references"]), 2)
