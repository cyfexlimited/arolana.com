from django import template
from decimal import Decimal
from currency.models import Currency

register = template.Library()

@register.filter
def currency(value, request=None):
    """Format a number as currency with conversion"""
    # Handle empty or None values
    if value is None or value == '':
        return '$0.00'
    
    try:
        # Convert to float
        amount = float(value)
        
        # Get user's selected currency from session or request
        user_currency_code = None
        if request and hasattr(request, 'session'):
            user_currency_code = request.session.get('user_currency')
        
        # Check cookie for currency if not in session
        if not user_currency_code and request and hasattr(request, 'COOKIES'):
            user_currency_code = request.COOKIES.get('user_currency')
        
        # If no currency found, default to USD
        if not user_currency_code:
            user_currency_code = 'USD'
        
        # Get target currency
        try:
            target_currency = Currency.objects.get(code=user_currency_code, is_active=True)
        except Currency.DoesNotExist:
            target_currency = Currency.objects.get(code='USD', is_active=True)
        
        # Convert amount using exchange rate
        converted_amount = amount * float(target_currency.exchange_rate)
        
        # Format with currency symbol
        # Handle NGN (no decimals)
        if user_currency_code == 'NGN':
            return f"{target_currency.symbol}{converted_amount:,.0f}"
        return f"{target_currency.symbol}{converted_amount:,.2f}"
            
    except (ValueError, TypeError, AttributeError) as e:
        print(f"Currency filter error: {e}, value: {value}")
        return f"$0.00"

@register.simple_tag(takes_context=True)
def current_currency_symbol(context):
    """Get current currency symbol"""
    request = context.get('request')
    if request and hasattr(request, 'session'):
        currency_code = request.session.get('user_currency', 'USD')
    else:
        currency_code = 'USD'
    
    symbols = {'USD': '$', 'EUR': '€', 'GBP': '£', 'NGN': '₦', 'CAD': 'C$', 'AUD': 'A$'}
    return symbols.get(currency_code, '$')

@register.simple_tag(takes_context=True)
def current_currency_code(context):
    """Get current currency code"""
    request = context.get('request')
    if request and hasattr(request, 'session'):
        return request.session.get('user_currency', 'USD')
    return 'USD'

@register.filter
def convert_currency(amount, target_code):
    """Convert amount to specific currency"""
    try:
        amount = float(amount)
        target = Currency.objects.get(code=target_code, is_active=True)
        converted = amount * float(target.exchange_rate)
        return f"{target.symbol}{converted:,.2f}"
    except:
        return f"${amount}"