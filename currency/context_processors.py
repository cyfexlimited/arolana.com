from .models import Currency

def currency_processor(request):
    """Add currency information to all templates"""
    # Get currency from session or default to USD
    user_currency = request.session.get('user_currency', 'USD')
    
    # Validate that currency exists
    try:
        currency_obj = Currency.objects.filter(code=user_currency, is_active=True).first()
        if not currency_obj:
            user_currency = 'USD'
    except:
        user_currency = 'USD'
    
    # Currency symbols
    symbols = {
        'USD': '$', 'EUR': '€', 'GBP': '£', 'NGN': '₦',
        'CAD': 'C$', 'AUD': 'A$', 'JPY': '¥', 'CNY': '¥', 'INR': '₹'
    }
    
    # Exchange rates (fallback)
    rates = {
        'USD': 1.0, 'EUR': 0.92, 'GBP': 0.79, 'NGN': 1512.50,
        'CAD': 1.37, 'AUD': 1.52, 'JPY': 150.25, 'CNY': 7.24, 'INR': 83.50
    }
    
    return {
        'user_currency': user_currency,
        'currency_symbol': symbols.get(user_currency, '$'),
        'currency_rate': rates.get(user_currency, 1.0),
        'all_currencies': [
            {'code': 'USD', 'symbol': '$', 'name': 'US Dollar'},
            {'code': 'EUR', 'symbol': '€', 'name': 'Euro'},
            {'code': 'GBP', 'symbol': '£', 'name': 'British Pound'},
            {'code': 'NGN', 'symbol': '₦', 'name': 'Nigerian Naira'},
            {'code': 'CAD', 'symbol': 'C$', 'name': 'Canadian Dollar'},
            {'code': 'AUD', 'symbol': 'A$', 'name': 'Australian Dollar'},
        ]
    }
