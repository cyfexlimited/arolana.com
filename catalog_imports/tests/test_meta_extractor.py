from decimal import Decimal
from django.test import SimpleTestCase

from catalog_imports.extractors.generic import GenericStructuredProductExtractor


class MetaExtractorTests(SimpleTestCase):
    def test_open_graph_fallback(self):
        html = '''
        <html><head>
        <meta property="og:title" content="Logitech C920e" />
        <meta property="og:description" content="Full HD webcam" />
        <meta property="product:brand" content="Logitech" />
        <meta property="product:price:amount" content="90000" />
        <meta property="product:price:currency" content="NGN" />
        <meta property="og:image" content="https://example.com/c920e.jpg" />
        </head></html>
        '''
        draft = GenericStructuredProductExtractor().extract(url="https://example.com/p", html=html)
        self.assertEqual(draft.name, "Logitech C920e")
        self.assertEqual(draft.brand, "Logitech")
        self.assertEqual(draft.source_price, Decimal("90000"))
        self.assertEqual(len(draft.images), 1)
