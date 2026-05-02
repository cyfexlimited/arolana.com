from django.contrib import admin
from django.utils.html import format_html
from .models import Cart, CartItem, Order, OrderItem

class CartItemInline(admin.TabularInline):
    model = CartItem
    extra = 0
    readonly_fields = ['product', 'quantity', 'price_at_add']

@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'total_items', 'subtotal', 'is_active', 'updated_at']
    list_filter = ['is_active']
    search_fields = ['user__username', 'user__email']
    inlines = [CartItemInline]
    readonly_fields = ['total_items', 'subtotal']
    
    def total_items(self, obj):
        return obj.total_items
    total_items.short_description = 'Items'

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ['order_number', 'user', 'total', 'status', 'created_at']
    list_filter = ['status', 'payment_status']
    search_fields = ['order_number', 'user__username', 'user__email']
    readonly_fields = ['order_number', 'created_at']
    
    fieldsets = (
        ('Order Information', {
            'fields': ('order_number', 'user', 'status', 'payment_status')
        }),
        ('Financial', {
            'fields': ('subtotal', 'shipping_cost', 'tax', 'total')
        }),
        ('Shipping', {
            'fields': ('shipping_address', 'tracking_number')
        }),
    )

@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ['order', 'product', 'quantity', 'price', 'subtotal']
    search_fields = ['order__order_number', 'product__name']
    readonly_fields = ['subtotal']
