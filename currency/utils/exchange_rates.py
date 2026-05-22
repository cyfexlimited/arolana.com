from decimal import Decimal, InvalidOperation
from django.core.cache import cache
from currency.models import Currency

class ExchangeRateService:
    """Service to fetch and manage exchange rates"""
    
    @classmethod
    def update_all_rates(cls):
        """Update exchange rates for all currencies"""
        # For now, use hardcoded rates
        rates = {
            'USD': Decimal('1.0'),
            'EUR': Decimal('0.92'),
            'GBP': Decimal('0.79'),
            'NGN': Decimal('1500.0'),
            'CAD': Decimal('1.35'),
            'AUD': Decimal('1.52'),
        }
        
        for code, rate in rates.items():
            currency = Currency.objects.filter(code=code).first()
            if currency:
                currency.exchange_rate = rate
                currency.save()
        
        return True

class CurrencyConverter:
    """Handle currency conversions"""

    @staticmethod
    def _as_decimal(value):
        try:
            return Decimal(str(value or '0'))
        except (InvalidOperation, TypeError, ValueError):
            return Decimal('0')
    
    @staticmethod
    def convert(amount, from_currency, to_currency):
        """Convert amount from one currency to another"""
        if not from_currency or not to_currency:
            return CurrencyConverter._as_decimal(amount)
        
        if from_currency.code == to_currency.code:
            return CurrencyConverter._as_decimal(amount)
        
        try:
            amount_dec = CurrencyConverter._as_decimal(amount)
            from_rate = CurrencyConverter._as_decimal(from_currency.exchange_rate)
            to_rate = CurrencyConverter._as_decimal(to_currency.exchange_rate)

            if from_rate == 0:
                return amount_dec

            amount_in_base = amount_dec / from_rate
            return amount_in_base * to_rate
        except Exception as e:
            print(f"Conversion error: {e}")
            return CurrencyConverter._as_decimal(amount)
