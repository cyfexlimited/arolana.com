from django.contrib import admin
from django.utils.html import format_html

from .models import ManualCryptoWallet, PaymentTransaction


@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = [
        "reference",
        "gateway",
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
        "order_id",
        "customer_email",
        "customer_name",
        "manual_tx_hash",
    ]
    readonly_fields = [
        "reference",
        "gateway_response",
        "webhook_payload",
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
            "fields": ("gateway_reference", "gateway_checkout_url", "gateway_response", "webhook_payload")
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
