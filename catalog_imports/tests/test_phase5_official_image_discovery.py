from django.test import SimpleTestCase

from catalog_imports.models import ImportMediaCandidate
from catalog_imports.services.media_references import (
    extract_official_image_urls,
    rank_reference_urls,
)


class Phase505OfficialImageDiscoveryTests(SimpleTestCase):
    def test_extracts_same_official_domain_gallery_sources(self):
        html = """
        <html><head>
          <meta property="og:image" content="https://resource.example.com/product/hero.png">
          <script type="application/ld+json">
            {"@type":"Product","image":["https://cdn.example.com/product/front-transparent.webp"]}
          </script>
        </head><body>
          <img src="/images/product-left-angle.jpg">
          <picture>
            <source srcset="/images/product-front-800.webp 800w, /images/product-front-1600.webp 1600w">
          </picture>
          <img src="https://evil.example.net/copied.jpg">
          <img src="/assets/favicon.svg">
        </body></html>
        """
        urls = extract_official_image_urls(
            html,
            page_url="https://www.example.com/products/widget",
            official_domain="example.com",
        )
        self.assertIn("https://resource.example.com/product/hero.png", urls)
        self.assertIn("https://cdn.example.com/product/front-transparent.webp", urls)
        self.assertIn("https://www.example.com/images/product-left-angle.jpg", urls)
        self.assertIn("https://www.example.com/images/product-front-1600.webp", urls)
        self.assertNotIn("https://evil.example.net/copied.jpg", urls)
        self.assertFalse(any(url.endswith("favicon.svg") for url in urls))

    def test_clean_product_reference_ranks_ahead_of_lifestyle_for_main(self):
        urls = [
            "https://resource.example.com/media/conference-room-lifestyle.jpg",
            "https://resource.example.com/products/widget-front-transparent.webp",
        ]
        ranked = rank_reference_urls(
            urls,
            ImportMediaCandidate.VIEW_MAIN,
            visual_score_func=lambda url: 10 if "transparent" in url else 0,
        )
        self.assertEqual(
            ranked[0],
            "https://resource.example.com/products/widget-front-transparent.webp",
        )

    def test_lifestyle_still_ranks_scene_first_for_lifestyle_job(self):
        urls = [
            "https://resource.example.com/products/widget-front-transparent.webp",
            "https://resource.example.com/media/meeting-room-lifestyle.jpg",
        ]
        ranked = rank_reference_urls(
            urls,
            ImportMediaCandidate.VIEW_LIFESTYLE,
            visual_score_func=lambda url: 10 if "transparent" in url else 0,
        )
        self.assertEqual(
            ranked[0],
            "https://resource.example.com/media/meeting-room-lifestyle.jpg",
        )
