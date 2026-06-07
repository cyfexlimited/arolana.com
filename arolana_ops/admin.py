from django.contrib import admin

from .models import OrderStatusHistory, PriceAlert, ProductInteraction


@admin.register(OrderStatusHistory)
class OrderStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ["order", "status", "message", "changed_by", "created_at"]
    list_filter = ["status", "created_at"]
    search_fields = ["order__order_number", "message"]
    autocomplete_fields = ["order", "changed_by"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(PriceAlert)
class PriceAlertAdmin(admin.ModelAdmin):
    list_display = ["customer", "product", "target_price", "last_seen_price", "is_active", "triggered_at", "created_at"]
    list_filter = ["is_active", "triggered_at", "created_at"]
    search_fields = ["customer__full_name", "customer__phone_number", "product__name", "product__slug"]
    autocomplete_fields = ["customer", "product"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(ProductInteraction)
class ProductInteractionAdmin(admin.ModelAdmin):
    list_display = ["customer", "product", "view_count", "last_viewed_at", "updated_at"]
    list_filter = ["last_viewed_at", "created_at"]
    search_fields = ["customer__full_name", "customer__phone_number", "product__name", "product__slug"]
    autocomplete_fields = ["customer", "product"]
    readonly_fields = ["created_at", "updated_at"]
