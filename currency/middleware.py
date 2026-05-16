from django.utils.deprecation import MiddlewareMixin
from currency.geo.ip_geolocation import COUNTRY_CURRENCY_MAP
from currency.models import CountryCurrency, Currency
import logging

logger = logging.getLogger(__name__)

class CurrencyMiddleware(MiddlewareMixin):
    """Middleware to auto-detect and set user's currency based on location"""
    COUNTRY_HEADERS = (
        'HTTP_CF_IPCOUNTRY',
        'HTTP_CLOUDFRONT_VIEWER_COUNTRY',
        'HTTP_X_COUNTRY_CODE',
        'HTTP_X_FORWARDED_COUNTRY',
        'HTTP_X_APPENGINE_COUNTRY',
        'HTTP_FLY_CLIENT_IP_COUNTRY',
    )
    
    def get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR')

    def detect_country_code(self, request):
        for header in self.COUNTRY_HEADERS:
            country_code = (request.META.get(header) or '').strip().upper()
            if len(country_code) == 2 and country_code != 'XX':
                return country_code

        # Railway and many proxies preserve the visitor IP in X-Forwarded-For,
        # but external lookups can slow page loads, so they stay as a fallback.
        ip_address = self.get_client_ip(request)
        if not ip_address or ip_address.startswith(('10.', '127.', '172.16.', '192.168.')) or ip_address == '::1':
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
            mapping = CountryCurrency.objects.select_related('currency').get(
                country_code=country_code,
                is_active=True,
                currency__is_active=True,
            )
            return mapping.currency.code
        except CountryCurrency.DoesNotExist:
            return COUNTRY_CURRENCY_MAP.get(country_code)
    
    def detect_from_browser(self, request):
        accept_language = request.META.get('HTTP_ACCEPT_LANGUAGE', '')
        lang_currency = {
            'en-NG': 'NGN', 'en-GH': 'GHS', 'en-ZA': 'ZAR',
            'en-GB': 'GBP', 'en-US': 'USD', 'en-CA': 'CAD', 
            'en-AU': 'AUD', 'en-IN': 'INR', 'en-PK': 'PKR',
            'ja': 'JPY', 'ja-JP': 'JPY',
            'fr': 'EUR', 'de': 'EUR', 'es': 'EUR', 'it': 'EUR',
            'pt': 'EUR', 'nl': 'EUR', 'zh': 'CNY', 'ko': 'KRW',
        }
        if accept_language:
            primary = accept_language.split(',')[0]
            exact = lang_currency.get(primary)
            if exact:
                return exact
            language = primary.split('-')[0]
            return lang_currency.get(language, 'USD')
        return 'USD'
    
    def process_request(self, request):
        # Manual choice always wins.
        session_manual = request.session.get('user_currency_set') and request.session.get('user_currency_source') != 'auto'
        if session_manual or request.COOKIES.get('currency_manual') == '1':
            currency_code = request.COOKIES.get('user_currency') or request.session.get('user_currency')
            if currency_code:
                try:
                    currency = Currency.objects.get(code=currency_code, is_active=True)
                    request.user_currency = currency.code
                    request.currency_symbol = currency.symbol
                except:
                    pass
            return
        
        country_code = self.detect_country_code(request)
        detected_currency = self.currency_for_country(country_code) or self.detect_from_browser(request)
        
        # Set the currency automatically
        try:
            currency = Currency.objects.get(code=detected_currency, is_active=True)
            request.session['user_currency'] = currency.code
            request.session['user_currency_source'] = 'auto'
            request.session['user_country_code'] = country_code or ''
            request.user_currency = currency.code
            request.currency_symbol = currency.symbol
            
            # Also set a response cookie when we have a response
            def set_cookie(response):
                response.set_cookie('user_currency', currency.code, max_age=31536000, httponly=False, samesite='Lax')
                response.set_cookie('currency_auto', '1', max_age=31536000, httponly=False, samesite='Lax')
                return response
            
            # Store the callback for later
            request.currency_callback = set_cookie
            
        except Currency.DoesNotExist:
            request.user_currency = 'USD'
            request.currency_symbol = '$'

class CurrencyContextMiddleware(MiddlewareMixin):
    """Add currency context to all templates"""

    def process_response(self, request, response):
        if hasattr(request, 'currency_callback'):
            response = request.currency_callback(response)
        return response

    def process_template_response(self, request, response):
        if hasattr(response, 'context_data'):
            currency_code = getattr(request, 'user_currency', 'USD')
            response.context_data['user_currency'] = currency_code
            
            # Get symbol
            symbols = {'USD': '$', 'EUR': '€', 'GBP': '£', 'NGN': '₦', 'JPY': '¥', 
                      'CAD': 'C$', 'AUD': 'A$', 'CNY': '¥', 'INR': '₹'}
            response.context_data['currency_symbol'] = symbols.get(currency_code, '$')
        
        return response
