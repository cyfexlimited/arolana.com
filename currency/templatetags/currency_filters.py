from django import template
from decimal import Decimal
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
    default_currency = None
    
    for curr in currencies:
        currency_data[curr.code] = {
            'code': curr.code,
            'symbol': curr.symbol,
            'exchange_rate': float(curr.exchange_rate),
            'name': curr.name,
            'is_base': curr.is_base,
        }
        if curr.is_base or curr.code == 'USD':
            default_currency = curr.code
    
    result = {
        'currencies': currency_data,
        'default': default_currency or 'USD',
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
        
        # If no currency found, default to USD
        if not user_currency_code:
            user_currency_code = 'USD'
        
        # Get currency data from cache
        currency_data = get_currency_data()
        
        # Check if currency exists
        if user_currency_code not in currency_data['currencies']:
            user_currency_code = currency_data['default']
        
        # Get exchange rate and symbol
        rate = currency_data['rates'].get(user_currency_code, 1.0)
        symbol = currency_data['symbols'].get(user_currency_code, '$')
        
        # Convert amount
        converted_amount = amount * rate
        
        # Format with currency symbol
        if user_currency_code == 'NGN':
            # Nigerian Naira - no decimals
            return f"{symbol}{converted_amount:,.0f}"
        elif user_currency_code == 'JPY':
            # Japanese Yen - no decimals
            return f"{symbol}{converted_amount:,.0f}"
        else:
            # Most currencies - 2 decimals
            return f"{symbol}{converted_amount:,.2f}"
            
    except (ValueError, TypeError, AttributeError, KeyError) as e:
        print(f"Currency filter error: {e}, value: {value}")
        return f"${float(value):,.2f}" if value else "$0.00"

@register.simple_tag(takes_context=True)
def current_currency_symbol(context):
    """Get current currency symbol"""
    request = context.get('request')
    currency_code = 'USD'
    
    if request and hasattr(request, 'session'):
        currency_code = request.session.get('user_currency', 'USD')
    elif request and hasattr(request, 'COOKIES'):
        currency_code = request.COOKIES.get('user_currency', 'USD')
    
    try:
        currency_data = get_currency_data()
        return currency_data['symbols'].get(currency_code, '$')
    except:
        symbols = {'USD': '$', 'EUR': '€', 'GBP': '£', 'NGN': '₦', 'CAD': 'C$', 'AUD': 'A$'}
        return symbols.get(currency_code, '$')

@register.simple_tag(takes_context=True)
def current_currency_code(context):
    """Get current currency code"""
    request = context.get('request')
    
    if request and hasattr(request, 'session'):
        return request.session.get('user_currency', 'USD')
    elif request and hasattr(request, 'COOKIES'):
        return request.COOKIES.get('user_currency', 'USD')
    
    return 'USD'

@register.filter
def convert_currency(amount, target_code):
    """Convert amount to specific currency"""
    try:
        amount = float(amount)
        
        if not target_code:
            return f"${amount:,.2f}"
        
        currency_data = get_currency_data()
        rate = currency_data['rates'].get(target_code.upper(), 1.0)
        symbol = currency_data['symbols'].get(target_code.upper(), '$')
        
        converted = amount * rate
        
        if target_code.upper() in ['NGN', 'JPY']:
            return f"{symbol}{converted:,.0f}"
        return f"{symbol}{converted:,.2f}"
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
