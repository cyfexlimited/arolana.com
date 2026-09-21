import ssl
from unittest import TestCase

from catalog_imports.services.http_fetch import _build_ssl_context


class SSLContextTests(TestCase):
    def test_ssl_context_keeps_certificate_verification_enabled(self):
        context = _build_ssl_context()
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
