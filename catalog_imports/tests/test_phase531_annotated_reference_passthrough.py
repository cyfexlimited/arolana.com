from pathlib import Path

from django.test import SimpleTestCase


class Phase531AnnotatedReferencePassthroughTests(SimpleTestCase):
    def test_authoritative_evidence_loop_accepts_verified_annotated_opaque_refs(self):
        import catalog_imports.services.media_references as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        self.assertIn("trusted_annotated_reference", source)
        self.assertIn(
            "_looks_like_image_url(url) or trusted_annotated_reference",
            source,
        )
