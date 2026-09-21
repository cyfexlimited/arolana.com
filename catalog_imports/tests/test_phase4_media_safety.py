from django.test import SimpleTestCase

from catalog_imports.models import ImportMediaCandidate
from catalog_imports.services.media_publish import _candidate_is_safe


class DummyCandidate:
    kind = ImportMediaCandidate.KIND_GENERATION
    asset_storage_alias = "private_import_review"
    asset_storage_name = "catalog-imports/review/item-1/front.webp"
    selected_for_product = True
    status = ImportMediaCandidate.STATUS_APPROVED
    exact_identity_verified = True
    source_identity_check_passed = True
    watermark_status = ImportMediaCandidate.WATERMARK_CLEAR
    rights_status = ImportMediaCandidate.RIGHTS_CONFIRMED


class Phase4MediaSafetyTests(SimpleTestCase):
    def test_fully_verified_materialized_media_is_attachable(self):
        self.assertTrue(_candidate_is_safe(DummyCandidate()))

    def test_reference_only_media_is_rejected(self):
        candidate = DummyCandidate()
        candidate.kind = ImportMediaCandidate.KIND_REFERENCE
        self.assertFalse(_candidate_is_safe(candidate))

    def test_unmaterialized_media_is_rejected(self):
        candidate = DummyCandidate()
        candidate.asset_storage_name = ""
        self.assertFalse(_candidate_is_safe(candidate))

    def test_watermarked_media_is_rejected(self):
        candidate = DummyCandidate()
        candidate.watermark_status = ImportMediaCandidate.WATERMARK_DETECTED
        self.assertFalse(_candidate_is_safe(candidate))

    def test_unverified_identity_is_rejected(self):
        candidate = DummyCandidate()
        candidate.exact_identity_verified = False
        self.assertFalse(_candidate_is_safe(candidate))

    def test_source_identity_check_is_required(self):
        candidate = DummyCandidate()
        candidate.source_identity_check_passed = False
        self.assertFalse(_candidate_is_safe(candidate))

    def test_import_media_candidate_adds_no_new_upload_field(self):
        names = {field.name for field in ImportMediaCandidate._meta.fields}
        self.assertNotIn("image", names)
        self.assertIn("asset_storage_name", names)
