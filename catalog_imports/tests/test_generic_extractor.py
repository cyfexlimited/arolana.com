from decimal import Decimal

from django.test import SimpleTestCase

from catalog_imports.extractors.generic import GenericStructuredProductExtractor


class GenericExtractorTests(SimpleTestCase):
    def test_schema_org_product(self):
        html = '''
        <script type="application/ld+json">
        {
          "@context":"https://schema.org",
          "@type":"Product",
          "name":"Logitech Example",
          "sku":"LOG-123",
          "brand":{"@type":"Brand","name":"Logitech"},
          "offers":{"@type":"Offer","price":"100000","priceCurrency":"NGN"}
        }
        </script>
        '''
        draft = GenericStructuredProductExtractor().extract(
            url="https://example.com/item",
            html=html,
        )
        self.assertEqual(draft.name, "Logitech Example")
        self.assertEqual(draft.brand, "Logitech")
        self.assertEqual(draft.manufacturer_sku, "LOG-123")
        self.assertEqual(draft.source_price, Decimal("100000"))
