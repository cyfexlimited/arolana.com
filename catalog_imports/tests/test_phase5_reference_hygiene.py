from types import SimpleNamespace

from django.test import SimpleTestCase

from catalog_imports.models import ImportMediaCandidate
from catalog_imports.services.media_references import (
    _product_relevant_url,
    _srcset_urls,
    extract_official_image_urls,
    rank_reference_urls,
)


class Phase506ReferenceHygieneTests(SimpleTestCase):
    def test_cloudinary_style_srcset_commas_are_not_split_into_fragments(self):
        value = (
            "https://resource.example.com/w_150,h_220,c_limit,q_auto,f_auto,dpr_1.0/"
            "content/dam/example/widget/gallery/widget-front.png?v=1 1x, "
            "https://resource.example.com/w_150,h_220,c_limit,q_auto,f_auto,dpr_2.0/"
            "content/dam/example/widget/gallery/widget-front.png?v=1 2x"
        )
        urls = _srcset_urls(value)
        self.assertEqual(len(urls), 2)
        self.assertTrue(all("/w_150,h_220,c_limit," in url for url in urls))
        self.assertFalse(any(url.endswith("/w_150") for url in urls))

    def test_non_image_transform_fragments_are_rejected(self):
        html = """
        <img srcset="https://resource.example.com/w_1206,h_900,c_limit,q_auto/content/dam/example/widget/front.png 1x,
                     https://resource.example.com/w_1206,h_900,c_limit,q_auto/content/dam/example/widget/front.png 2x">
        """
        urls = extract_official_image_urls(
            html,
            page_url="https://www.example.com/products/widget",
            official_domain="example.com",
        )
        self.assertTrue(urls)
        self.assertTrue(all(url.endswith(".png") for url in urls))
        self.assertFalse(any(url.endswith("/w_1206") for url in urls))
        self.assertFalse(any(url.endswith("/c_limit") for url in urls))

    def test_versioned_product_rejects_predecessor_and_sibling_assets(self):
        item = SimpleNamespace(
            normalized_payload={
                "brand": "Example",
                "name": "MeetUp 2 Video Conferencing Camera",
                "model": "MeetUp 2",
            },
            created_product=None,
        )
        self.assertTrue(
            _product_relevant_url(
                item,
                "https://resource.example.com/content/dam/example/meetup-2/gallery/meetup-2-graphite-01.png",
            )
        )
        self.assertFalse(
            _product_relevant_url(
                item,
                "https://resource.example.com/content/dam/example/meetup/gallery/meetup-old.png",
            )
        )
        self.assertFalse(
            _product_relevant_url(
                item,
                "https://resource.example.com/content/dam/example/rally-bar/gallery/rally-bar-front.png",
            )
        )

    def test_main_gallery_reference_ranks_above_lifestyle_without_probing_everything(self):
        urls = [
            "https://resource.example.com/content/dam/example/meetup-2/meetup-2-room-solution.png",
            "https://resource.example.com/content/dam/example/meetup-2/gallery/meetup-2-graphite-01.png",
        ]
        calls = []
        def scorer(url):
            calls.append(url)
            return 0
        ranked = rank_reference_urls(
            urls,
            ImportMediaCandidate.VIEW_MAIN,
            visual_score_func=scorer,
        )
        self.assertIn("gallery", ranked[0])
        self.assertEqual(len(calls), 2)
