from django.test import SimpleTestCase

from catalog_imports.extractors.paykobo import PaykoboExtractor


class PaykoboAdapterTests(SimpleTestCase):
    def test_enriches_logitech_identity(self):
        html = '''
        <html><head>
        <meta property="og:title" content="Logitech Rally Bar Mini 960-001336" />
        <meta property="product:price:amount" content="3060500" />
        <meta property="product:price:currency" content="NGN" />
        </head></html>
        '''
        draft = PaykoboExtractor().extract(url="https://paykobo.com/example", html=html)
        self.assertEqual(draft.brand, "Logitech")
        self.assertEqual(draft.manufacturer_sku, "960-001336")
        self.assertEqual(draft.source_name, "Paykobo")
