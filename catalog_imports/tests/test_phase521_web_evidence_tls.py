import json
import ssl
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from catalog_imports.services import web_evidence


class _Response:
    def __init__(self, payload):
        self.payload = payload
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc, tb):
        return False
    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class Phase521WebEvidenceTLSTests(SimpleTestCase):
    @patch("catalog_imports.services.web_evidence.urllib.request.urlopen")
    @patch("catalog_imports.services.web_evidence._build_ssl_context")
    def test_provider_uses_certificate_verifying_importer_context(self, build_context, urlopen):
        context = ssl.create_default_context()
        build_context.return_value = context
        urlopen.return_value = _Response({"output": []})

        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}, clear=False):
            result = web_evidence._provider_request("test prompt", ["sony.com"])

        self.assertEqual(result, {"output": []})
        build_context.assert_called_once_with()
        self.assertIs(urlopen.call_args.kwargs["context"], context)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)

    def test_tls_fix_never_disables_verification(self):
        context = web_evidence._build_ssl_context()
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
