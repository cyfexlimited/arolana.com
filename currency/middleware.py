from django.conf import settings
from django.utils.deprecation import MiddlewareMixin
from django.db import DatabaseError

from currency.geo.ip_geolocation import COUNTRY_CURRENCY_MAP
from currency.models import CountryCurrency, Currency
from core.local_cache import local_get_or_set

import logging

logger = logging.getLogger(__name__)


class CurrencyMiddleware(MiddlewareMixin):
    """
    Auto-detect and set user's currency based on location.

    Important:
    - Normal visitors can still use geo/IP/browser currency detection.
    - Manual visitor currency choice still wins.
    - Google crawlers and Merchant Center bots are forced to NGN for Arolana Nigeria launch.
    """

    COUNTRY_HEADERS = (
        "HTTP_CF_IPCOUNTRY",
        "HTTP_CLOUDFRONT_VIEWER_COUNTRY",
        "HTTP_X_COUNTRY_CODE",
        "HTTP_X_FORWARDED_COUNTRY",
        "HTTP_X_APPENGINE_COUNTRY",
        "HTTP_FLY_CLIENT_IP_COUNTRY",
    )

    GOOGLE_BOT_KEYWORDS = (
        "googlebot",
        "google-inspectiontool",
        "adsbot-google",
        "mediapartners-google",
        "apis-google",
        "storebot-google",
        "google-site-verification",
        "google-structured-data-testing-tool",
        "google-rich-results",
        "merchant-center",
        "google merchant",
    )

    DEFAULT_CURRENCY = getattr(settings, "AROLANA_DEFAULT_CURRENCY", "NGN")
    GOOGLE_CURRENCY = getattr(settings, "GOOGLE_MERCHANT_CURRENCY", "NGN")

    def get_client_ip(self, request):
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR")

    def is_google_crawler(self, request):
        user_agent = (request.META.get("HTTP_USER_AGENT") or "").lower()
        return any(keyword in user_agent for keyword in self.GOOGLE_BOT_KEYWORDS)

    def get_currency_object(self, currency_code):
        try:
            code = str(currency_code or self.DEFAULT_CURRENCY).upper()
            return local_get_or_set(
                f"currency:middleware:{code}",
                lambda: Currency.objects.filter(code=code, is_active=True).first(),
                3600,
            )
        except Exception as exc:
            logger.warning("Currency lookup failed for %s: %s", currency_code, exc)
            return None

    def apply_currency_to_request(self, request, currency_code, source="auto", country_code=""):
        """
        Apply currency to request, session, and cookie callback.
        """

        currency = self.get_currency_object(currency_code)

        if not currency:
            currency = self.get_currency_object(self.DEFAULT_CURRENCY)

        if not currency:
            request.user_currency = "NGN"
            request.currency_symbol = "₦"
            return

        if getattr(request.user, "is_authenticated", False):
            request.session["user_currency"] = currency.code
            request.session["user_currency_source"] = source
            request.session["user_country_code"] = country_code or ""
        request.user_currency = currency.code
        request.currency_symbol = currency.symbol

        def set_cookie(response):
            response.set_cookie(
                "user_currency",
                currency.code,
                max_age=31536000,
                httponly=False,
                samesite="Lax",
            )

            if source == "auto":
                response.set_cookie(
                    "currency_auto",
                    "1",
                    max_age=31536000,
                    httponly=False,
                    samesite="Lax",
                )
            elif source == "googlebot":
                response.set_cookie(
                    "currency_auto",
                    "1",
                    max_age=31536000,
                    httponly=False,
                    samesite="Lax",
                )

            return response

        request.currency_callback = set_cookie

    def detect_country_code(self, request):
        for header in self.COUNTRY_HEADERS:
            country_code = (request.META.get(header) or "").strip().upper()
            if len(country_code) == 2 and country_code != "XX":
                return country_code

        if not getattr(settings, "CURRENCY_IP_GEOLOCATION_ENABLED", False):
            return None

        ip_address = self.get_client_ip(request)

        private_prefixes = ("10.", "127.", "172.16.", "192.168.")
        if not ip_address or ip_address.startswith(private_prefixes) or ip_address == "::1":
            return None

        try:
            from currency.geo.ip_geolocation import IPGeolocationService
            return IPGeolocationService().get_country_code(ip_address)
        except Exception as exc:
            logger.info("Currency IP detection skipped: %s", exc)
            return None

    def currency_for_country(self, country_code):
        if not country_code:
            return None

        try:
            mapping = CountryCurrency.objects.select_related("currency").get(
                country_code=country_code,
                is_active=True,
                currency__is_active=True,
            )
            return mapping.currency.code
        except CountryCurrency.DoesNotExist:
            return COUNTRY_CURRENCY_MAP.get(country_code)
        except DatabaseError as exc:
            logger.warning("Currency country lookup failed: %s", exc)
            return COUNTRY_CURRENCY_MAP.get(country_code)
        except Exception as exc:
            logger.warning("Currency country lookup skipped: %s", exc)
            return COUNTRY_CURRENCY_MAP.get(country_code)

    def detect_from_browser(self, request):
        accept_language = request.META.get("HTTP_ACCEPT_LANGUAGE", "")

        lang_currency = {
            "en-NG": "NGN",
            "en-GH": "GHS",
            "en-ZA": "ZAR",
            "en-GB": "GBP",
            "en-US": "USD",
            "en-CA": "CAD",
            "en-AU": "AUD",
            "en-IN": "INR",
            "en-PK": "PKR",
            "ja": "JPY",
            "ja-JP": "JPY",
            "fr": "EUR",
            "de": "EUR",
            "es": "EUR",
            "it": "EUR",
            "pt": "EUR",
            "nl": "EUR",
            "zh": "CNY",
            "ko": "KRW",
        }

        if accept_language:
            primary = accept_language.split(",")[0].strip()
            exact = lang_currency.get(primary)

            if exact:
                return exact

            language = primary.split("-")[0]
            return lang_currency.get(language, self.DEFAULT_CURRENCY)

        return self.DEFAULT_CURRENCY

    def process_request(self, request):
        path = request.path_info or request.path
        if (
            path == "/health/"
            or path.startswith("/api/")
            or path.startswith("/smartchat/api/")
            or path.startswith("/static/")
            or path.startswith("/media/")
        ):
            request.user_currency = self.DEFAULT_CURRENCY
            request.currency_symbol = "₦" if self.DEFAULT_CURRENCY == "NGN" else ""
            return

        # Googlebot and Merchant Center must see NGN for Nigeria launch.
        # This prevents Google search results from showing US$ due to crawler location/browser language.
        if self.is_google_crawler(request):
            self.apply_currency_to_request(
                request,
                self.GOOGLE_CURRENCY,
                source="googlebot",
                country_code=getattr(settings, "GOOGLE_MERCHANT_COUNTRY", "NG"),
            )
            return

        # Manual choice always wins for real visitors.
        session_manual = (
            request.session.get("user_currency_set")
            and request.session.get("user_currency_source") != "auto"
        )

        if session_manual or request.COOKIES.get("currency_manual") == "1":
            currency_code = request.COOKIES.get("user_currency") or request.session.get("user_currency")

            if currency_code:
                currency = self.get_currency_object(currency_code)

                if currency:
                    request.user_currency = currency.code
                    request.currency_symbol = currency.symbol
                    return

            request.user_currency = self.DEFAULT_CURRENCY
            request.currency_symbol = "₦" if self.DEFAULT_CURRENCY == "NGN" else ""
            return

        cookie_currency = request.COOKIES.get("user_currency")
        if cookie_currency:
            currency = self.get_currency_object(cookie_currency)
            if currency:
                request.user_currency = currency.code
                request.currency_symbol = currency.symbol
                return

        country_code = self.detect_country_code(request)
        detected_currency = self.currency_for_country(country_code) or self.detect_from_browser(request)

        self.apply_currency_to_request(
            request,
            detected_currency or self.DEFAULT_CURRENCY,
            source="auto",
            country_code=country_code or "",
        )


class CurrencyContextMiddleware(MiddlewareMixin):
    """Add currency context to all templates and set currency cookies."""

    def process_response(self, request, response):
        if hasattr(request, "currency_callback"):
            response = request.currency_callback(response)
        return response

    def process_template_response(self, request, response):
        if hasattr(response, "context_data"):
            currency_code = getattr(
                request,
                "user_currency",
                getattr(settings, "AROLANA_DEFAULT_CURRENCY", "NGN"),
            )

            response.context_data["user_currency"] = currency_code

            symbols = {
                "USD": "$",
                "EUR": "€",
                "GBP": "£",
                "NGN": "₦",
                "JPY": "¥",
                "CAD": "C$",
                "AUD": "A$",
                "CNY": "¥",
                "INR": "₹",
                "GHS": "₵",
                "ZAR": "R",
                "PKR": "₨",
                "KRW": "₩",
            }

            response.context_data["currency_symbol"] = symbols.get(currency_code, "₦")

        return response
