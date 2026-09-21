from django.test import SimpleTestCase

from catalog_imports.services.official_documents import (
    discover_official_documents,
    document_identity_matches,
    extract_specifications_from_text,
)


class OfficialManufacturerDocumentTests(SimpleTestCase):
    def test_discovers_only_same_official_domain_spec_documents(self):
        html = '''
        <html><body>
          <a href="/content/product-datasheet.pdf">DATASHEET</a>
          <a href="https://cdn.example.com/copy.pdf">Technical Specifications</a>
          <a href="/support/manual.pdf">Manual</a>
        </body></html>
        '''
        urls = discover_official_documents(
            html,
            "https://www.brand.example/products/model-x",
            "brand.example",
        )
        self.assertEqual(urls, ["https://www.brand.example/content/product-datasheet.pdf"])

    def test_document_text_extracts_multiple_concrete_specs(self):
        text = '''
        Model X Technical Specifications
        Resolution: 4K
        Weight: 1.8 kg
        Zoom: 4x digital
        Frequency Response: 90 Hz to 16 kHz
        https://brand.example/product
        '''
        specs = extract_specifications_from_text(text)
        self.assertEqual(specs["Resolution"], "4K")
        self.assertEqual(specs["Weight"], "1.8 kg")
        self.assertGreaterEqual(len(specs), 4)

    def test_document_identity_needs_product_specific_match(self):
        good = document_identity_matches(
            "MeetUp 2 technical data. Part number 960-001681. Resolution: 4K",
            name="MeetUp 2 Video Conferencing Camera",
            sku="960-001681",
        )
        bad = document_identity_matches(
            "Generic collaboration portfolio brochure",
            name="MeetUp 2 Video Conferencing Camera",
            sku="960-001681",
        )
        self.assertTrue(good["passed"])
        self.assertFalse(bad["passed"])
