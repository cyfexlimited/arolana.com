from types import SimpleNamespace

from django.test import SimpleTestCase

from catalog_imports.services.media_reference_trace import (
    TRACE_KEY,
    build_reference_trace,
    record_reference_trace,
    reference_trace_for_candidate,
)


class Phase5ReferenceTraceTests(SimpleTestCase):
    def test_trace_deduplicates_and_preserves_exact_order(self):
        trace = build_reference_trace(
            urls=["https://official.test/a.png", "https://official.test/a.png", "https://official.test/b.png"],
            attempt=2,
            view_role="main",
            provider_key="openai",
        )
        self.assertEqual(trace["reference_urls"], ["https://official.test/a.png", "https://official.test/b.png"])
        self.assertEqual(trace["attempt"], 2)
        self.assertEqual(trace["view_role"], "main")

    def test_recorded_trace_is_used_in_review_instead_of_mutable_current_refs(self):
        candidate = SimpleNamespace(
            metadata={}, generation_attempts=3, view_role="main", provider_key="openai",
            reference_urls=["https://official.test/current.png"],
        )
        used = record_reference_trace(
            candidate,
            urls=["https://official.test/used.png"],
            provider_key="openai",
        )
        self.assertEqual(used, ["https://official.test/used.png"])
        candidate.reference_urls = ["https://official.test/changed-after-generation.png"]
        review = reference_trace_for_candidate(candidate)
        self.assertTrue(review["recorded"])
        self.assertEqual(review["reference_urls"], ["https://official.test/used.png"])
        self.assertIn(TRACE_KEY, candidate.metadata)

    def test_legacy_candidate_is_clearly_marked_unrecorded(self):
        candidate = SimpleNamespace(
            metadata={}, generation_attempts=1, view_role="front", provider_key="openai",
            reference_urls=["https://official.test/legacy.png"],
        )
        review = reference_trace_for_candidate(candidate)
        self.assertFalse(review["recorded"])
        self.assertEqual(review["reference_urls"], ["https://official.test/legacy.png"])
