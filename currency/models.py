from django.db import models
from core.models import BaseModel
from django.core.cache import cache
import requests
from decimal import Decimal, InvalidOperation


def format_currency_amount(
    amount,
    symbol='',
    decimal_places=2,
    thousands_separator=',',
    decimal_separator='.',
    symbol_position='left',
):
    """Format an already-converted currency amount using admin settings."""
    if amount is None:
        amount = 0

    try:
        decimal_places = max(int(decimal_places or 0), 0)
    except (TypeError, ValueError):
        decimal_places = 2

    try:
        amount_dec = Decimal(str(amount))
    except (InvalidOperation, TypeError, ValueError):
        amount_dec = Decimal('0')

    # Arolana storefront uses comma grouping consistently so prices read like
    # ₦598,500.00 instead of ₦598.500.00 even if older currency rows still
    # have a dot saved as the thousands separator.
    if thousands_separator == '.':
        thousands_separator = ','
    if not decimal_separator or decimal_separator == thousands_separator:
        decimal_separator = '.'

    number = f"{amount_dec:.{decimal_places}f}"
    integer_part, _, fraction = number.partition('.')

    sign = ''
    if integer_part.startswith('-'):
        sign = '-'
        integer_part = integer_part[1:]

    if thousands_separator:
        groups = []
        while len(integer_part) > 3:
            groups.insert(0, integer_part[-3:])
            integer_part = integer_part[:-3]
        groups.insert(0, integer_part or '0')
        integer_part = thousands_separator.join(groups)

    formatted = f"{sign}{integer_part}"
    if decimal_places > 0:
        formatted = f"{formatted}{decimal_separator}{fraction}"

    if symbol_position == 'right':
        return f"{formatted}{symbol}"
    if symbol_position == 'space_left':
        return f"{symbol} {formatted}"
    if symbol_position == 'space_right':
        return f"{formatted} {symbol}"
    return f"{symbol}{formatted}"

class Currency(BaseModel):
    """Currency model with exchange rates"""
    code = models.CharField(max_length=3, unique=True)  # USD, EUR, GBP, NGN, etc.
    symbol = models.CharField(max_length=10)  # $, €, £, ₦, etc.
    name = models.CharField(max_length=100)
    exchange_rate = models.DecimalField(max_digits=20, decimal_places=6, default=1.0)
    is_base = models.BooleanField(default=False, help_text="Base currency for conversions")
    is_active = models.BooleanField(default=True)
    
    # Display settings
    symbol_position = models.CharField(max_length=20, choices=[
        ('left', 'Left (e.g., $100)'),
        ('right', 'Right (e.g., 100$)'),
        ('space_left', 'Space Left (e.g., $ 100)'),
        ('space_right', 'Space Right (e.g., 100 $)'),
    ], default='left')
    decimal_places = models.IntegerField(default=2)
    thousands_separator = models.CharField(max_length=1, default=',')
    decimal_separator = models.CharField(max_length=1, default='.')
    
    class Meta:
        ordering = ['code']
        verbose_name_plural = "Currencies"
    
    def __str__(self):
        return f"{self.code} ({self.symbol})"
    
    def format_amount(self, amount):
        """Format an amount that is already in this currency."""
        return format_currency_amount(
            amount,
            symbol=self.symbol,
            decimal_places=self.decimal_places,
            thousands_separator=self.thousands_separator,
            decimal_separator=self.decimal_separator,
            symbol_position=self.symbol_position,
        )

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        from core.local_cache import local_delete
        local_delete('all_active_currencies')

    def delete(self, *args, **kwargs):
        result = super().delete(*args, **kwargs)
        from core.local_cache import local_delete
        local_delete('all_active_currencies')
        return result

class CountryCurrency(BaseModel):
    """Map countries to their local currencies"""
    country_code = models.CharField(max_length=2, unique=True)  # ISO 3166-1 alpha-2
    country_name = models.CharField(max_length=100)
    currency = models.ForeignKey(Currency, on_delete=models.CASCADE, related_name='countries')
    is_active = models.BooleanField(default=True)
    
    class Meta:
        verbose_name_plural = "Country Currencies"
        ordering = ['country_name']
    
    def __str__(self):
        return f"{self.country_name} - {self.currency.code}"

class CurrencyConversionLog(BaseModel):
    """Log currency conversion requests"""
    from_currency = models.ForeignKey(Currency, on_delete=models.CASCADE, related_name='conversions_from')
    to_currency = models.ForeignKey(Currency, on_delete=models.CASCADE, related_name='conversions_to')
    amount = models.DecimalField(max_digits=20, decimal_places=6)
    converted_amount = models.DecimalField(max_digits=20, decimal_places=6)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    country_code = models.CharField(max_length=2, blank=True)
    session_id = models.CharField(max_length=200, blank=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.amount} {self.from_currency.code} → {self.converted_amount} {self.to_currency.code}"
