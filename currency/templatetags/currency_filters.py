from django import template
from decimal import Decimal
from django.conf import settings
from core.local_cache import local_get_or_set

register = template.Library()

# Cache for currency data to reduce database hits
CURRENCY_CACHE_KEY = 'all_active_currencies'
CURRENCY_CACHE_TIMEOUT = 3600  # 1 hour

def get_currency_data():
    """Get all active currencies with caching"""
    return local_get_or_set(CURRENCY_CACHE_KEY, _build_currency_data, CURRENCY_CACHE_TIMEOUT)


def _build_currency_data():
    from currency.models import Currency

    currencies = Currency.objects.filter(is_active=True)
    currency_data = {}
    configured_base = (
        getattr(settings, 'AROLANA_BASE_CURRENCY', None)
        or getattr(settings, 'AROLANA_DEFAULT_CURRENCY', None)
        or getattr(settings, 'CURRENCY_DEFAULT', None)
    )
    configured_base = configured_base.upper() if configured_base else None
    flagged_base = None
    
    for curr in currencies:
        currency_data[curr.code] = {
            'code': curr.code,
            'symbol': curr.symbol,
            'exchange_rate': float(curr.exchange_rate),
            'name': curr.name,
            'is_base': curr.is_base,
            'decimal_places': curr.decimal_places,
            'thousands_separator': curr.thousands_separator,
            'decimal_separator': curr.decimal_separator,
            'symbol_position': curr.symbol_position,
        }
        if curr.is_base:
            flagged_base = curr.code

    base_currency = configured_base if configured_base in currency_data else flagged_base
    if not base_currency:
        base_currency = 'NGN' if 'NGN' in currency_data else 'USD'
    if base_currency not in currency_data and currency_data:
        base_currency = next(iter(currency_data))
    
    result = {
        'currencies': currency_data,
        'base': base_currency,
        'default': base_currency or 'NGN',
        'symbols': {code: data['symbol'] for code, data in currency_data.items()},
        'rates': {code: data['exchange_rate'] for code, data in currency_data.items()},
    }
    
    return result

@register.filter
def currency(value, request=None):
    """Format a number as currency with conversion"""
    # Handle empty or None values
    if value is None or value == '':
        return '$0.00'
    
    try:
        # Convert to float
        amount = float(value)
        
        # Get user's selected currency
        user_currency_code = None
        if request:
            # Try session
            if hasattr(request, 'session') and request.session:
                user_currency_code = request.session.get('user_currency')
            
            # Try cookie if not in session
            if not user_currency_code and hasattr(request, 'COOKIES'):
                user_currency_code = request.COOKIES.get('user_currency')
        
        # Get currency data from cache
        currency_data = get_currency_data()

        # If no currency found, use the catalog/default currency.
        if not user_currency_code:
            user_currency_code = currency_data['default']
        
        # Check if currency exists
        if user_currency_code not in currency_data['currencies']:
            user_currency_code = currency_data['default']
        
        # Convert from the catalog base currency to the visitor currency.
        base_currency_code = currency_data.get('base') or currency_data.get('default') or 'NGN'
        base_rate = Decimal(str(currency_data['rates'].get(base_currency_code, 1.0) or 1.0))
        target_rate = Decimal(str(currency_data['rates'].get(user_currency_code, 1.0) or 1.0))
        symbol = currency_data['symbols'].get(user_currency_code, '$')
        currency_settings = currency_data['currencies'].get(user_currency_code, {})

        amount_dec = Decimal(str(amount))
        converted_amount = amount_dec if base_rate == target_rate else amount_dec * target_rate / base_rate

        from currency.models import format_currency_amount
        return format_currency_amount(
            converted_amount,
            symbol=symbol,
            decimal_places=currency_settings.get('decimal_places', 2),
            thousands_separator=currency_settings.get('thousands_separator', ','),
            decimal_separator=currency_settings.get('decimal_separator', '.'),
            symbol_position=currency_settings.get('symbol_position', 'left'),
        )
            
    except (ValueError, TypeError, AttributeError, KeyError) as e:
        print(f"Currency filter error: {e}, value: {value}")
        return f"${float(value):,.2f}" if value else "$0.00"

@register.simple_tag(takes_context=True)
def current_currency_symbol(context):
    """Get current currency symbol"""
    request = context.get('request')
    currency_data = get_currency_data()
    currency_code = currency_data.get('default') or 'NGN'

    if request and getattr(request, 'user_currency', None):
        currency_code = request.user_currency
    elif request and hasattr(request, 'session'):
        currency_code = request.session.get('user_currency', currency_code)
    elif request and hasattr(request, 'COOKIES'):
        currency_code = request.COOKIES.get('user_currency', currency_code)
    
    try:
        return currency_data['symbols'].get(currency_code, '$')
    except:
        symbols = {'USD': '$', 'EUR': '€', 'GBP': '£', 'NGN': '₦', 'CAD': 'C$', 'AUD': 'A$'}
        return symbols.get(currency_code, '$')

@register.simple_tag(takes_context=True)
def current_currency_code(context):
    """Get current currency code"""
    request = context.get('request')
    currency_data = get_currency_data()
    default_currency = currency_data.get('default') or 'NGN'

    if request and getattr(request, 'user_currency', None):
        return request.user_currency
    if request and hasattr(request, 'session'):
        return request.session.get('user_currency', default_currency)
    elif request and hasattr(request, 'COOKIES'):
        return request.COOKIES.get('user_currency', default_currency)
    
    return default_currency

@register.filter
def convert_currency(amount, target_code):
    """Convert amount to specific currency"""
    try:
        amount = float(amount)
        
        if not target_code:
            return f"${amount:,.2f}"
        
        currency_data = get_currency_data()
        target_code = target_code.upper()
        base_currency_code = currency_data.get('base') or currency_data.get('default') or 'NGN'
        base_rate = Decimal(str(currency_data['rates'].get(base_currency_code, 1.0) or 1.0))
        target_rate = Decimal(str(currency_data['rates'].get(target_code, 1.0) or 1.0))
        symbol = currency_data['symbols'].get(target_code, '$')
        currency_settings = currency_data['currencies'].get(target_code, {})
        
        amount_dec = Decimal(str(amount))
        converted = amount_dec if base_rate == target_rate else amount_dec * target_rate / base_rate

        from currency.models import format_currency_amount
        return format_currency_amount(
            converted,
            symbol=symbol,
            decimal_places=currency_settings.get('decimal_places', 2),
            thousands_separator=currency_settings.get('thousands_separator', ','),
            decimal_separator=currency_settings.get('decimal_separator', '.'),
            symbol_position=currency_settings.get('symbol_position', 'left'),
        )
    except Exception as e:
        print(f"Convert currency error: {e}")
        return f"${amount:,.2f}"

@register.simple_tag
def get_currency_symbol(currency_code):
    """Get symbol for currency code"""
    if not currency_code:
        return '$'
    
    try:
        currency_data = get_currency_data()
        return currency_data['symbols'].get(currency_code.upper(), '$')
    except:
        symbols = {'USD': '$', 'EUR': '€', 'GBP': '£', 'NGN': '₦', 'CAD': 'C$', 'AUD': 'A$'}
        return symbols.get(currency_code.upper(), '$')

@register.simple_tag
def get_exchange_rate(currency_code):
    """Get exchange rate for currency code"""
    if not currency_code:
        return 1.0
    
    try:
        currency_data = get_currency_data()
        return currency_data['rates'].get(currency_code.upper(), 1.0)
    except:
        return 1.0


@register.simple_tag
def base_currency_code():
    """Get the catalog/base currency code used for stored prices."""
    try:
        currency_data = get_currency_data()
        return currency_data.get('base') or currency_data.get('default') or 'NGN'
    except Exception:
        return 'NGN'
