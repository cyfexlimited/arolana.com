from django.test import SimpleTestCase

from catalog_imports.models import ImportMediaCandidate


class Phase5StatusTests(SimpleTestCase):
    def test_media_workflow_statuses_exist(self):
        values = {value for value, _label in ImportMediaCandidate.STATUS_CHOICES}
        self.assertTrue({
            ImportMediaCandidate.STATUS_PLANNED,
            ImportMediaCandidate.STATUS_GENERATING,
            ImportMediaCandidate.STATUS_READY_REVIEW,
            ImportMediaCandidate.STATUS_APPROVED,
            ImportMediaCandidate.STATUS_REJECTED,
            ImportMediaCandidate.STATUS_FAILED,
            ImportMediaCandidate.STATUS_ATTACHED,
        }.issubset(values))

    def test_no_upload_field_was_added(self):
        field_names = {field.name for field in ImportMediaCandidate._meta.fields}
        self.assertNotIn("image", field_names)
        self.assertNotIn("file", field_names)
        self.assertIn("asset_storage_name", field_names)
