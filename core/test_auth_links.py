from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from django.template import Context, Template
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.urls import reverse


class LoginUrlTemplateTagTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.template = Template(
            "{% load auth_links %}{% login_url_with_next fragment %}"
        )

    def render_login_url(self, path, fragment=""):
        request = self.factory.get(path)
        return self.template.render(
            Context(
                {
                    "request": request,
                    "fragment": fragment,
                }
            )
        )

    def test_current_full_path_and_query_string_are_preserved(self):
        rendered = self.render_login_url(
            "/products/conference-camera/?variant=graphite&bundle=room",
        )
        parsed = urlsplit(rendered)

        self.assertEqual(parsed.path, reverse("accounts:login"))
        self.assertEqual(
            parse_qs(parsed.query)["next"],
            ["/products/conference-camera/?variant=graphite&bundle=room"],
        )

    def test_action_fragment_is_preserved_inside_next(self):
        rendered = self.render_login_url(
            "/products/conference-camera/?variant=graphite",
            fragment="#review-form",
        )

        self.assertEqual(
            parse_qs(urlsplit(rendered).query)["next"],
            ["/products/conference-camera/?variant=graphite#review-form"],
        )

    def test_explicit_safe_action_destination_is_supported(self):
        template = Template(
            "{% load auth_links %}"
            "{% login_url_with_next '' '/installers/acme-av/review/' %}"
        )

        rendered = template.render(
            Context({"request": self.factory.get("/installers/acme-av/")})
        )

        self.assertEqual(
            parse_qs(urlsplit(rendered).query)["next"],
            ["/installers/acme-av/review/"],
        )

    def test_missing_request_falls_back_to_home(self):
        rendered = self.template.render(Context({"fragment": ""}))

        self.assertEqual(
            parse_qs(urlsplit(rendered).query)["next"],
            ["/"],
        )

    def test_protocol_relative_request_path_is_not_emitted(self):
        request = SimpleNamespace(
            get_full_path=lambda: "//malicious-site.example/landing",
        )

        rendered = self.template.render(
            Context(
                {
                    "request": request,
                    "fragment": "",
                }
            )
        )

        self.assertEqual(
            parse_qs(urlsplit(rendered).query)["next"],
            ["/"],
        )


class PublicLoginEntryPointTests(TestCase):
    def test_desktop_navigation_and_mobile_drawer_preserve_public_page(self):
        response = self.client.get("/sitemap/?section=account")
        expected_url = (
            f"{reverse('accounts:login')}"
            "?next=%2Fsitemap%2F%3Fsection%3Daccount"
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'href="{expected_url}" '
            'class="hover:text-brand transition text-sm font-medium"',
        )
        self.assertContains(
            response,
            f'href="{expected_url}" @click="mobileMenuOpen = false"',
        )
