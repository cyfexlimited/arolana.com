from types import SimpleNamespace

from django.test import SimpleTestCase

from catalog_imports.services.media_reference_trace import (
    TRACE_KEY,
    TEXT_GROUNDING_TRACE_KEY,
    reference_trace_for_candidate,
    text_grounding_trace_for_candidate,
)


class Phase525TextGroundingTraceTests(SimpleTestCase):
    def test_zero_visual_reference_request_is_still_a_recorded_trace(self):
        candidate = SimpleNamespace(
            metadata={
                TRACE_KEY: {
                    "reference_urls": [],
                    "attempt": 1,
                    "view_role": "lifestyle",
                    "provider_key": "openai-creative-fallback",
                    "recorded_at": "2026-09-20T22:00:00+00:00",
                }
            },
            reference_urls=[],
            generation_attempts=1,
            view_role="lifestyle",
            provider_key="openai-creative-fallback",
        )
        trace = reference_trace_for_candidate(candidate)
        self.assertTrue(trace["recorded"])
        self.assertEqual(trace["reference_urls"], [])
        self.assertEqual(trace["attempt"], 1)

    def test_old_candidate_without_trace_key_is_still_legacy(self):
        candidate = SimpleNamespace(
            metadata={},
            reference_urls=[],
            generation_attempts=1,
            view_role="lifestyle",
            provider_key="openai-creative-fallback",
        )
        trace = reference_trace_for_candidate(candidate)
        self.assertFalse(trace["recorded"])

    def test_text_grounding_trace_returns_exact_identity_and_evidence(self):
        candidate = SimpleNamespace(
            metadata={
                TEXT_GROUNDING_TRACE_KEY: {
                    "mode": "verified_manufacturer_text_no_visual_reference",
                    "provider": "openai_web_search",
                    "official_product_url": "https://pro.sony/products/pxw-z200",
                    "name": "PXW-Z200",
                    "brand": "Sony",
                    "model": "PXW-Z200",
                    "evidence_urls": [
                        "https://pro.sony/products/pxw-z200",
                        "https://www.sony.com/support/pxw-z200",
                    ],
                }
            }
        )
        trace = text_grounding_trace_for_candidate(candidate)
        self.assertTrue(trace["recorded"])
        self.assertEqual(trace["brand"], "Sony")
        self.assertEqual(trace["model"], "PXW-Z200")
        self.assertEqual(len(trace["evidence_urls"]), 2)
