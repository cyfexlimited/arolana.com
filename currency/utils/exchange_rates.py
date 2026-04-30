from decimal import Decimal
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
    def convert(amount, from_currency, to_currency):
        """Convert amount from one currency to another"""
        if not from_currency or not to_currency:
            return amount
        
        if from_currency.code == to_currency.code:
            return amount
        
        try:
            # Convert to Decimal
            amount_dec = Decimal(str(amount))
            
            # Convert to USD first (base currency)
            usd = Currency.objects.filter(is_base=True).first()
            if not usd:
                usd = Currency.objects.filter(code='USD').first()
            
            # Convert from source to USD
            amount_in_usd = amount_dec / Decimal(str(from_currency.exchange_rate))
            
            # Convert from USD to target
            converted = amount_in_usd * Decimal(str(to_currency.exchange_rate))
            
            return float(converted)
        except Exception as e:
            print(f"Conversion error: {e}")
            return amount
