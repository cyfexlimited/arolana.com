from django.db import models
from core.models import BaseModel
from django.core.cache import cache
import requests

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
        """Format amount with proper currency formatting"""
        if not amount:
            return f"{self.symbol}0"
        
        # Convert amount to this currency
        converted = float(amount) * float(self.exchange_rate)
        
        # Format with proper decimal places
        formatted = f"{converted:.{self.decimal_places}f}"
        
        # Add thousands separators
        if self.thousands_separator:
            parts = formatted.split('.')
            parts[0] = f"{int(float(parts[0])):{self.thousands_separator}d}"
            formatted = '.'.join(parts)
        
        # Position the symbol
        if self.symbol_position == 'left':
            return f"{self.symbol}{formatted}"
        elif self.symbol_position == 'right':
            return f"{formatted}{self.symbol}"
        elif self.symbol_position == 'space_left':
            return f"{self.symbol} {formatted}"
        else:
            return f"{formatted} {self.symbol}"

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
