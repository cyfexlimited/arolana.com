from django.test import SimpleTestCase

from catalog_imports.services.official_media_acquisition import (
    _select_media_page_queue,
)


class Phase532MediaPageQueueTests(SimpleTestCase):
    def test_verified_mirror_is_not_starved_by_canonical_evidence_urls(self):
        pages = []
        for index in range(20):
            pages.append({
                "url": f"https://pro.sony/evidence/{index}/pxw-z200",
                "kind": "evidence",
                "mirror_verified": False,
                "source": "manufacturer_web_evidence",
            })

        pages.append({
            "url": "https://www.sony.co.uk/store/product/pxw-z200",
            "kind": "store",
            "mirror_verified": True,
            "source": "verified_mirror_discovery",
        })

        selected = _select_media_page_queue(
            pages,
            canonical_hosts={"pro.sony", "sony.com"},
            expected_model="PXW-Z200",
            max_pages=12,
            max_per_host=3,
        )

        urls = [row["url"] for row in selected]
        self.assertIn(
            "https://www.sony.co.uk/store/product/pxw-z200",
            urls,
        )
        self.assertLessEqual(
            sum(1 for url in urls if "pro.sony" in url),
            3,
        )

    def test_queue_is_host_diverse_and_bounded(self):
        pages = [
            {
                "url": f"https://pro.sony/p/{i}/pxw-z200",
                "kind": "product",
                "mirror_verified": False,
            }
            for i in range(8)
        ]
        pages += [
            {
                "url": "https://www.sony.co.uk/store/pxw-z200",
                "kind": "store",
                "mirror_verified": True,
            },
            {
                "url": "https://store.sony.com.tw/product/pxw-z200",
                "kind": "store",
                "mirror_verified": True,
            },
        ]

        selected = _select_media_page_queue(
            pages,
            canonical_hosts={"pro.sony", "sony.com"},
            expected_model="PXW-Z200",
            max_pages=5,
            max_per_host=2,
        )

        self.assertLessEqual(len(selected), 5)
        hosts = [row["url"].split("/")[2] for row in selected]
        self.assertIn("www.sony.co.uk", hosts)
        self.assertIn("store.sony.com.tw", hosts)
        self.assertLessEqual(hosts.count("pro.sony"), 2)
