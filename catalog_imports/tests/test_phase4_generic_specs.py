from django.test import SimpleTestCase

from catalog_imports.extractors.generic import GenericStructuredProductExtractor


class Phase4GenericSpecificationTests(SimpleTestCase):
    def test_jsonld_additional_property_becomes_specs(self):
        html = '''
        <script type="application/ld+json">
        {
          "@context":"https://schema.org",
          "@type":"Product",
          "name":"MeetUp 2",
          "brand":{"@type":"Brand","name":"Logitech"},
          "sku":"960-001681",
          "additionalProperty":[
            {"@type":"PropertyValue","name":"Weight","value":"1.8 kg"},
            {"@type":"PropertyValue","name":"Dimensions","value":"469.2 x 73.3 x 73 mm"}
          ]
        }
        </script>
        '''
        draft = GenericStructuredProductExtractor().extract(url="https://logitech.com/product", html=html)
        self.assertEqual(draft.specifications["Weight"], "1.8 kg")
        self.assertIn("469.2", draft.specifications["Dimensions"])

    def test_generic_two_cell_spec_table_is_extracted(self):
        html = '''
        <html><head><meta property="og:title" content="MeetUp 2"></head>
        <body><table>
          <tr><th>Resolution</th><td>4K</td></tr>
          <tr><th>Weight</th><td>1.8 kg</td></tr>
        </table></body></html>
        '''
        draft = GenericStructuredProductExtractor().extract(url="https://example.com/product", html=html)
        self.assertEqual(draft.specifications["Resolution"], "4K")
        self.assertEqual(draft.specifications["Weight"], "1.8 kg")
