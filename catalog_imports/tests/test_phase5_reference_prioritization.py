from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from catalog_imports.models import ImportMediaCandidate
from catalog_imports.services.media_references import rank_reference_urls


class Phase5ReferencePrioritizationTests(SimpleTestCase):
    def test_main_view_prefers_clean_product_reference_over_lifestyle_scene(self):
        urls = [
            "https://manufacturer.example/media/meeting-room-collaboration.jpg",
            "https://manufacturer.example/media/product-hero-transparent.png",
        ]
        scores = {
            urls[0]: 0,
            urls[1]: 12,
        }
        ranked = rank_reference_urls(urls, ImportMediaCandidate.VIEW_MAIN, visual_score_func=scores.get)
        self.assertEqual(ranked[0], urls[1])

    def test_lifestyle_view_prefers_explicit_scene_reference(self):
        urls = [
            "https://manufacturer.example/media/product-hero-transparent.png",
            "https://manufacturer.example/media/meeting-room-lifestyle.jpg",
        ]
        scores = {
            urls[0]: 12,
            urls[1]: 0,
        }
        ranked = rank_reference_urls(urls, ImportMediaCandidate.VIEW_LIFESTYLE, visual_score_func=scores.get)
        self.assertEqual(ranked[0], urls[1])

    def test_view_specific_front_hint_beats_generic_lifestyle(self):
        urls = [
            "https://manufacturer.example/media/office-room.jpg",
            "https://manufacturer.example/media/device-front-gallery.jpg",
        ]
        ranked = rank_reference_urls(urls, ImportMediaCandidate.VIEW_FRONT, visual_score_func=lambda _url: 0)
        self.assertEqual(ranked[0], urls[1])

    def test_ranking_preserves_only_supplied_official_urls(self):
        urls = [
            "https://manufacturer.example/a.png",
            "https://manufacturer.example/b.png",
        ]
        ranked = rank_reference_urls(urls, ImportMediaCandidate.VIEW_MAIN, visual_score_func=lambda _url: 0)
        self.assertEqual(set(ranked), set(urls))
        self.assertEqual(len(ranked), 2)
