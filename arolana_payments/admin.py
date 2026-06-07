from django.contrib import admin
from django.utils.html import format_html

from .models import (
    ManualCryptoWallet,
    PayPalWebhookLog,
    PaymentGatewayConfig,
    PaymentRefund,
    PaymentTransaction,
)


@admin.register(PaymentGatewayConfig)
class PaymentGatewayConfigAdmin(admin.ModelAdmin):
    list_display = ["display_name", "gateway", "is_active", "display_order", "updated_at"]
    list_editable = ["is_active", "display_order"]
    list_filter = ["is_active", "gateway"]
    search_fields = ["display_name", "description", "admin_note"]
    readonly_fields = ["created_at", "updated_at"]

    fieldsets = (
        ("Gateway", {
            "fields": ("gateway", "display_name", "description", "icon_class", "is_active", "display_order")
        }),
        ("Admin Note", {
            "fields": ("admin_note",),
            "classes": ("collapse",)
        }),
        ("Dates", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",)
        }),
    )


@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = [
        "reference",
        "gateway",
        "gateway_capture_id",
        "status",
        "amount",
        "currency",
        "customer_email",
        "order_id",
        "paid_at",
        "created_at",
    ]
    list_filter = ["gateway", "status", "currency", "created_at"]
    search_fields = [
        "reference",
        "gateway_reference",
        "gateway_capture_id",
        "order_id",
        "customer_email",
        "customer_name",
        "manual_tx_hash",
    ]
    readonly_fields = [
        "reference",
        "gateway_capture_id",
        "gateway_response",
        "webhook_payload",
        "checkout_data",
        "created_at",
        "updated_at",
        "paid_at",
    ]
    actions = ["mark_success", "mark_failed", "mark_review"]

    fieldsets = (
        ("Payment", {
            "fields": (
                "reference",
                "user",
                "order_id",
                "gateway",
                "status",
                "amount",
                "currency",
                "paid_at",
            )
        }),
        ("Customer", {
            "fields": ("customer_name", "customer_email", "customer_phone")
        }),
        ("Gateway", {
            "fields": (
                "gateway_reference",
                "gateway_capture_id",
                "gateway_checkout_url",
                "gateway_response",
                "webhook_payload",
            )
        }),
        ("Checkout Data", {
            "fields": ("checkout_data",),
            "classes": ("collapse",)
        }),
        ("Manual Crypto", {
            "fields": (
                "manual_wallet_network",
                "manual_wallet_address",
                "manual_sender_wallet",
                "manual_tx_hash",
                "manual_proof",
                "manual_note",
            )
        }),
        ("Dates", {
            "fields": ("created_at", "updated_at")
        }),
    )

    def mark_success(self, request, queryset):
        for payment in queryset:
            payment.mark_success()
        self.message_user(request, f"{queryset.count()} payment(s) marked successful.")
    mark_success.short_description = "Mark selected payments successful"

    def mark_failed(self, request, queryset):
        queryset.update(status="failed")
        self.message_user(request, f"{queryset.count()} payment(s) marked failed.")
    mark_failed.short_description = "Mark selected payments failed"

    def mark_review(self, request, queryset):
        queryset.update(status="review")
        self.message_user(request, f"{queryset.count()} payment(s) moved to manual review.")
    mark_review.short_description = "Move selected payments to manual review"


@admin.register(ManualCryptoWallet)
class ManualCryptoWalletAdmin(admin.ModelAdmin):
    list_display = ["network", "currency", "address_short", "is_active", "sort_order"]
    list_filter = ["currency", "network", "is_active"]
    search_fields = ["network", "currency", "address"]

    def address_short(self, obj):
        if len(obj.address) <= 22:
            return obj.address
        return f"{obj.address[:12]}...{obj.address[-8:]}"
    address_short.short_description = "Wallet Address"


@admin.register(PayPalWebhookLog)
class PayPalWebhookLogAdmin(admin.ModelAdmin):
    list_display = [
        "event_id",
        "event_type",
        "resource_id",
        "status",
        "signature_verified",
        "payment",
        "attempts",
        "received_at",
        "processed_at",
    ]
    list_filter = ["status", "signature_verified", "event_type", "received_at"]
    search_fields = [
        "event_id",
        "event_type",
        "resource_id",
        "payment__reference",
        "payment__gateway_reference",
        "payment__gateway_capture_id",
        "last_error",
    ]
    readonly_fields = [
        "event_id",
        "event_type",
        "resource_type",
        "resource_id",
        "status",
        "signature_verified",
        "payment",
        "attempts",
        "payload",
        "request_headers",
        "last_error",
        "received_at",
        "verified_at",
        "processed_at",
        "updated_at",
    ]
    date_hierarchy = "received_at"
    list_per_page = 50


@admin.register(PaymentRefund)
class PaymentRefundAdmin(admin.ModelAdmin):
    list_display = [
        "gateway_refund_id",
        "transaction",
        "order_id",
        "amount",
        "currency",
        "status",
        "refunded_at",
    ]
    list_filter = ["gateway", "status", "currency", "refunded_at"]
    search_fields = [
        "gateway_refund_id",
        "gateway_capture_id",
        "order_id",
        "transaction__reference",
    ]
    readonly_fields = [
        "transaction",
        "gateway",
        "gateway_refund_id",
        "gateway_capture_id",
        "order_id",
        "amount",
        "currency",
        "status",
        "payload",
        "refunded_at",
        "created_at",
        "updated_at",
    ]
