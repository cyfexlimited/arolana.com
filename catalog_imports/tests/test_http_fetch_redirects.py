from email.message import Message
from unittest import TestCase
from unittest.mock import patch

from catalog_imports.services.http_fetch import FetchBlocked, _redirect_target


class RedirectPolicyTests(TestCase):
    @patch("catalog_imports.services.http_fetch._validate_public_url")
    def test_307_relative_redirect_is_resolved(self, validate):
        headers = Message()
        headers["Location"] = "/products/example"
        target = _redirect_target(
            "https://shop.example/start",
            307,
            headers,
        )
        self.assertEqual(target, "https://shop.example/products/example")
        validate.assert_called_once_with(target)

    @patch("catalog_imports.services.http_fetch._validate_public_url")
    def test_https_downgrade_redirect_is_blocked(self, validate):
        headers = Message()
        headers["Location"] = "http://shop.example/product"
        with self.assertRaises(FetchBlocked):
            _redirect_target(
                "https://shop.example/start",
                307,
                headers,
            )

    def test_redirect_without_location_is_blocked(self):
        headers = Message()
        with self.assertRaises(FetchBlocked):
            _redirect_target(
                "https://shop.example/start",
                307,
                headers,
            )
