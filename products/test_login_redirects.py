from urllib.parse import parse_qs, urlsplit

from django.test import TestCase
from django.urls import reverse


class CheckoutLoginRedirectTests(TestCase):
    def test_guest_checkout_preserves_full_path_and_query_string(self):
        checkout_url = f"{reverse('products:checkout')}?coupon=SUMMER%2026"

        response = self.client.get(checkout_url)
        parsed = urlsplit(response.url)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(parsed.path, reverse("accounts:login"))
        self.assertEqual(
            parse_qs(parsed.query)["next"],
            ["/products/checkout/?coupon=SUMMER%2026"],
        )
