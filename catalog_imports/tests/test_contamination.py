from django.test import SimpleTestCase

from catalog_imports.schema import UniversalProductDraft
from catalog_imports.services.contamination import scan_source_identity


class ContaminationTests(SimpleTestCase):
    def test_source_name_in_public_copy_is_blocked(self):
        draft = UniversalProductDraft(
            source_name="Paykobo",
            source_url="https://paykobo.com/example",
            name="Logitech C920e",
            description="Buy this Logitech webcam from Paykobo.",
        )
        report = scan_source_identity(draft)
        self.assertFalse(report["passed"])

    def test_internal_source_fields_do_not_trigger_failure(self):
        draft = UniversalProductDraft(
            source_name="Paykobo",
            source_url="https://paykobo.com/example",
            name="Logitech C920e",
            description="Professional Full HD webcam for business video calls.",
        )
        report = scan_source_identity(draft)
        self.assertTrue(report["passed"])

    def test_source_name_allowed_when_it_is_the_real_brand(self):
        draft = UniversalProductDraft(
            source_name="Amazon",
            source_url="https://amazon.com/example",
            brand="Amazon",
            manufacturer="Amazon",
            name="Amazon Echo",
            description="Amazon Echo smart speaker.",
        )
        report = scan_source_identity(draft)
        self.assertTrue(report["passed"])
