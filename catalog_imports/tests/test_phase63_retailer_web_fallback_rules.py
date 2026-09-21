from types import SimpleNamespace

from django.test import SimpleTestCase

from catalog_imports.services.web_evidence import (
    _product_path_signatures,
    _retailer_domain,
)


class Phase63RetailerWebFallbackRuleTests(SimpleTestCase):
    def test_long_product_id_is_extracted_from_blocked_retailer_url(self):
        item = SimpleNamespace(
            source_url="https://www.office.co.uk/view/product/office_catalog/21/2675013086",
            input_value="",
            source_external_id="",
        )
        self.assertIn("2675013086", _product_path_signatures(item))

    def test_configured_source_domain_is_used_as_search_allowlist(self):
        item = SimpleNamespace(source_url="https://www.office.co.uk/x", input_value="")
        source = SimpleNamespace(domain="office.co.uk")
        self.assertEqual(_retailer_domain(item, source=source), "office.co.uk")
