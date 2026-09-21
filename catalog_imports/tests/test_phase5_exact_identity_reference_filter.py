from types import SimpleNamespace

from django.test import SimpleTestCase

from catalog_imports.models import ImportMediaCandidate
from catalog_imports.services.media_references import (
    _identity_slug_signatures,
    _product_relevant_url,
    rank_reference_urls,
)


class Phase507ExactIdentityReferenceTests(SimpleTestCase):
    def _item(self, name, model=""):
        return SimpleNamespace(
            normalized_payload={
                "brand": "Example",
                "name": name,
                "model": model,
            },
            created_product=None,
        )

    def test_version_number_does_not_match_cdn_dimensions_or_sibling_filename(self):
        item = self._item(
            "MeetUp 2 Video Conferencing Camera",
            "MeetUp 2",
        )
        self.assertTrue(
            _product_relevant_url(
                item,
                "https://resource.example.com/w_150,h_220,c_limit/"
                "content/dam/example/meetup-2/gallery/meetup-2-graphite-01.png",
            )
        )
        self.assertFalse(
            _product_relevant_url(
                item,
                "https://resource.example.com/w_150,h_220,c_limit/"
                "content/dam/example/rally-bar-huddle/gallery/rally-bar-huddle-front-01-new.png",
            )
        )
        self.assertFalse(
            _product_relevant_url(
                item,
                "https://resource.example.com/w_150,h_220,c_limit/"
                "content/dam/example/meetup/gallery/meetup-taa-gallery-global-1.png",
            )
        )

    def test_family_plus_numeric_signature_is_created(self):
        item = self._item("MeetUp 2 Video Conferencing Camera", "MeetUp 2")
        signatures = _identity_slug_signatures(item)
        self.assertIn("meetup-2", signatures)

    def test_alphanumeric_model_code_is_exact_reference_signature(self):
        item = self._item("C920e Business Webcam", "C920e")
        signatures = _identity_slug_signatures(item)
        self.assertIn("c920e", signatures)
        self.assertTrue(
            _product_relevant_url(
                item,
                "https://resource.example.com/content/dam/example/c920e/gallery/c920e-front.png",
            )
        )
        self.assertFalse(
            _product_relevant_url(
                item,
                "https://resource.example.com/content/dam/example/c920/gallery/c920-front.png",
            )
        )

    def test_exact_gallery_reference_ranks_first_after_siblings_are_removed(self):
        item = self._item("MeetUp 2 Video Conferencing Camera", "MeetUp 2")
        supplied = [
            "https://resource.example.com/content/dam/example/meetup-2/meetup-2-og-image.jpg",
            "https://resource.example.com/content/dam/example/meetup-2/gallery/meetup-2-graphite-01.png",
            "https://resource.example.com/content/dam/example/meetup-2/meetup-2-room-solution.png",
        ]
        exact = [url for url in supplied if _product_relevant_url(item, url)]
        ranked = rank_reference_urls(
            exact,
            ImportMediaCandidate.VIEW_MAIN,
            visual_score_func=lambda url: 0,
        )
        self.assertIn("/gallery/", ranked[0])
