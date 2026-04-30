from django.utils.deprecation import MiddlewareMixin
from currency.models import Currency

class CurrencyMiddleware(MiddlewareMixin):
    """Middleware to auto-detect and set user's currency based on location"""
    
    def get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0]
        return request.META.get('REMOTE_ADDR')
    
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
            return lang_currency.get(primary, 'USD')
        return 'USD'
    
    def process_request(self, request):
        # Skip if user already manually set currency
        if request.COOKIES.get('user_currency') or request.session.get('user_currency_set'):
            currency_code = request.COOKIES.get('user_currency') or request.session.get('user_currency')
            if currency_code:
                try:
                    currency = Currency.objects.get(code=currency_code, is_active=True)
                    request.user_currency = currency.code
                    request.currency_symbol = currency.symbol
                except:
                    pass
            return
        
        # Auto-detect from browser language
        detected_currency = self.detect_from_browser(request)
        print(f"🌍 Auto-detected currency: {detected_currency} from browser language")
        
        # Set the currency automatically
        try:
            currency = Currency.objects.get(code=detected_currency, is_active=True)
            request.session['user_currency'] = currency.code
            request.user_currency = currency.code
            request.currency_symbol = currency.symbol
            
            # Also set a response cookie when we have a response
            def set_cookie(response):
                response.set_cookie('user_currency', currency.code, max_age=31536000, httponly=False)
                return response
            
            # Store the callback for later
            request.currency_callback = set_cookie
            
            print(f"✅ Auto-set currency to: {currency.code} ({currency.symbol})")
        except Currency.DoesNotExist:
            request.user_currency = 'USD'
            request.currency_symbol = '$'

class CurrencyContextMiddleware(MiddlewareMixin):
    """Add currency context to all templates"""
    
    def process_template_response(self, request, response):
        # Set cookie if we have a callback
        if hasattr(request, 'currency_callback'):
            response = request.currency_callback(response)
        
        if hasattr(response, 'context_data'):
            currency_code = getattr(request, 'user_currency', 'USD')
            response.context_data['user_currency'] = currency_code
            
            # Get symbol
            symbols = {'USD': '$', 'EUR': '€', 'GBP': '£', 'NGN': '₦', 'JPY': '¥', 
                      'CAD': 'C$', 'AUD': 'A$', 'CNY': '¥', 'INR': '₹'}
            response.context_data['currency_symbol'] = symbols.get(currency_code, '$')
        
        return response