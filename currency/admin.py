from django.contrib import admin
from django.utils.html import format_html
from .models import Currency, CountryCurrency, CurrencyConversionLog

@admin.register(Currency)
class CurrencyAdmin(admin.ModelAdmin):
    list_display = ['code', 'symbol', 'name', 'exchange_rate', 'is_base', 'is_active', 'preview']
    list_editable = ['exchange_rate', 'is_base', 'is_active']
    list_filter = ['is_base', 'is_active']
    search_fields = ['code', 'name']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('code', 'symbol', 'name', 'exchange_rate', 'is_base', 'is_active')
        }),
        ('Formatting', {
            'fields': ('symbol_position', 'decimal_places', 'thousands_separator', 'decimal_separator'),
            'classes': ('collapse',)
        }),
    )
    
    def preview(self, obj):
        return format_html('<span style="background: #f3f4f6; padding: 4px 8px; border-radius: 4px;">{}</span>', 
                          obj.format_amount(1234.56))
    preview.short_description = 'Preview'

@admin.register(CountryCurrency)
class CountryCurrencyAdmin(admin.ModelAdmin):
    list_display = ['country_code', 'country_name', 'currency', 'is_active']
    list_editable = ['is_active']
    list_filter = ['currency', 'is_active']
    search_fields = ['country_code', 'country_name']

@admin.register(CurrencyConversionLog)
class CurrencyConversionLogAdmin(admin.ModelAdmin):
    list_display = ['from_currency', 'to_currency', 'amount', 'converted_amount', 'created_at']
    list_filter = ['from_currency', 'to_currency', 'created_at']
    readonly_fields = ['from_currency', 'to_currency', 'amount', 'converted_amount', 'ip_address', 'country_code', 'session_id', 'created_at']
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False
