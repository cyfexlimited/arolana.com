from django.contrib import admin
from django.utils.html import format_html
from .models import Cart, CartItem, DeliveryProvider, DeliveryQuoteRequest, DeliveryRequest, Order, OrderItem

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


@admin.register(DeliveryProvider)
class DeliveryProviderAdmin(admin.ModelAdmin):
    list_display = ['name', 'provider_type', 'base_fee', 'is_active', 'supports_tracking', 'supports_driver_assignment']
    list_filter = ['provider_type', 'is_active', 'supports_tracking', 'supports_driver_assignment']
    search_fields = ['name', 'code', 'contact_phone', 'contact_email']
    prepopulated_fields = {'code': ('name',)}
    fieldsets = (
        ('Provider', {
            'fields': ('name', 'code', 'provider_type', 'description', 'is_active')
        }),
        ('Delivery Settings', {
            'fields': ('base_fee', 'supports_tracking', 'supports_driver_assignment')
        }),
        ('Contact', {
            'fields': ('contact_phone', 'contact_email')
        }),
    )


@admin.register(DeliveryRequest)
class DeliveryRequestAdmin(admin.ModelAdmin):
    list_display = ['tracking_code', 'order', 'service_level', 'provider', 'tracking_status', 'driver_name', 'delivery_fee', 'created_at']
    list_filter = ['tracking_status', 'service_level', 'provider', 'created_at']
    search_fields = ['tracking_code', 'order__order_number', 'driver_name', 'driver_phone', 'dropoff_address']
    readonly_fields = ['tracking_code', 'created_at', 'updated_at', 'accepted_at', 'picked_up_at', 'delivered_at']
    autocomplete_fields = ['order', 'provider', 'driver_user']
    actions = ['mark_assigned', 'mark_picked_up', 'mark_in_transit', 'mark_delivered']
    fieldsets = (
        ('Delivery Request', {
            'fields': ('tracking_code', 'order', 'provider', 'service_level', 'tracking_status', 'provider_reference')
        }),
        ('Addresses and Fee', {
            'fields': ('pickup_address', 'dropoff_address', 'delivery_fee')
        }),
        ('Driver Assignment', {
            'fields': ('driver_user', 'driver_name', 'driver_phone')
        }),
        ('Tracking Location', {
            'fields': ('latest_location', 'latest_latitude', 'latest_longitude')
        }),
        ('Timeline', {
            'fields': ('accepted_at', 'picked_up_at', 'delivered_at', 'created_at', 'updated_at')
        }),
        ('Admin Notes', {
            'fields': ('admin_notes',)
        }),
    )

    @admin.action(description='Mark selected deliveries as assigned')
    def mark_assigned(self, request, queryset):
        for delivery in queryset:
            delivery.tracking_status = DeliveryRequest.STATUS_ASSIGNED
            delivery.save(update_fields=['tracking_status', 'updated_at'])

    @admin.action(description='Mark selected deliveries as picked up')
    def mark_picked_up(self, request, queryset):
        for delivery in queryset:
            delivery.mark_picked_up()

    @admin.action(description='Mark selected deliveries as in transit')
    def mark_in_transit(self, request, queryset):
        for delivery in queryset:
            delivery.mark_in_transit()

    @admin.action(description='Mark selected deliveries as delivered')
    def mark_delivered(self, request, queryset):
        for delivery in queryset:
            delivery.mark_delivered()


@admin.register(DeliveryQuoteRequest)
class DeliveryQuoteRequestAdmin(admin.ModelAdmin):
    list_display = ['id', 'provider', 'route_type', 'customer_email', 'customer_phone', 'status', 'admin_quote_fee', 'created_at']
    list_filter = ['status', 'route_type', 'provider', 'created_at']
    search_fields = ['customer_name', 'customer_email', 'customer_phone', 'pickup_address', 'dropoff_address', 'package_details']
    readonly_fields = ['created_at', 'updated_at']
    autocomplete_fields = ['user', 'order', 'provider']
    actions = ['mark_reviewing', 'mark_quoted']
    fieldsets = (
        ('Quote Request', {
            'fields': ('status', 'provider', 'route_type', 'service_level', 'order', 'user', 'session_key')
        }),
        ('Customer', {
            'fields': ('customer_name', 'customer_email', 'customer_phone')
        }),
        ('Route and Package', {
            'fields': ('pickup_address', 'dropoff_address', 'package_weight_kg', 'package_details')
        }),
        ('Admin Quote', {
            'fields': ('admin_quote_fee', 'admin_notes')
        }),
        ('Timeline', {
            'fields': ('created_at', 'updated_at')
        }),
    )

    @admin.action(description='Mark selected quote requests as reviewing')
    def mark_reviewing(self, request, queryset):
        queryset.update(status=DeliveryQuoteRequest.STATUS_REVIEWING)

    @admin.action(description='Mark selected quote requests as quoted')
    def mark_quoted(self, request, queryset):
        queryset.update(status=DeliveryQuoteRequest.STATUS_QUOTED)
