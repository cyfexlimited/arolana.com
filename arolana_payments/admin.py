from django.contrib import admin, messages
from django.utils import timezone

from .models import (
    ManualCryptoWallet,
    PayPalWebhookLog,
    PaymentGatewayConfig,
    PaymentRefund,
    PaymentStatus,
    PaymentTransaction,
)

from .manual_crypto_services import (
    approve_manual_crypto_payment,
    reject_manual_crypto_payment,
)


# =============================================================================
# PAYMENT GATEWAY CONFIG
# =============================================================================


@admin.register(PaymentGatewayConfig)
class PaymentGatewayConfigAdmin(admin.ModelAdmin):
    list_display = (
        "display_name",
        "gateway",
        "is_active",
        "display_order",
        "updated_at",
    )

    list_editable = (
        "is_active",
        "display_order",
    )

    list_filter = (
        "is_active",
        "gateway",
    )

    search_fields = (
        "display_name",
        "description",
        "admin_note",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    ordering = (
        "display_order",
        "display_name",
    )

    fieldsets = (
        (
            "Gateway",
            {
                "fields": (
                    "gateway",
                    "display_name",
                    "description",
                    "icon_class",
                    "is_active",
                    "display_order",
                ),
            },
        ),
        (
            "Admin Note",
            {
                "fields": (
                    "admin_note",
                ),
                "classes": (
                    "collapse",
                ),
            },
        ),
        (
            "Dates",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                ),
                "classes": (
                    "collapse",
                ),
            },
        ),
    )


# =============================================================================
# PAYMENT TRANSACTION
# =============================================================================


@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = (
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
    )

    list_filter = (
        "gateway",
        "status",
        "currency",
        "created_at",
        "paid_at",
    )

    search_fields = (
        "reference",
        "gateway_reference",
        "gateway_capture_id",
        "order_id",
        "customer_email",
        "customer_name",
        "customer_phone",
        "manual_tx_hash",
        "manual_sender_wallet",
    )

    readonly_fields = (
        "reference",
        "gateway_capture_id",
        "gateway_response",
        "webhook_payload",
        "checkout_data",
        "created_at",
        "updated_at",
        "paid_at",
        "manual_reviewed_by",
        "manual_reviewed_at",
        "manual_review_decision",
        "manual_review_note",
    )

    list_select_related = (
        "user",
    )

    ordering = (
        "-created_at",
    )

    date_hierarchy = "created_at"

    list_per_page = 100

    actions = (
        "approve_manual_crypto",
        "reject_manual_crypto",
    )

    fieldsets = (
        (
            "Payment",
            {
                "fields": (
                    "reference",
                    "user",
                    "order_id",
                    "gateway",
                    "status",
                    "amount",
                    "currency",
                    "paid_at",
                ),
            },
        ),
        (
            "Customer",
            {
                "fields": (
                    "customer_name",
                    "customer_email",
                    "customer_phone",
                ),
            },
        ),
        (
            "Gateway",
            {
                "fields": (
                    "gateway_reference",
                    "gateway_capture_id",
                    "gateway_checkout_url",
                    "gateway_response",
                    "webhook_payload",
                ),
            },
        ),
        (
            "Checkout Data",
            {
                "fields": (
                    "checkout_data",
                ),
                "classes": (
                    "collapse",
                ),
            },
        ),
        (
            "Manual Crypto",
            {
                "fields": (
                    "manual_wallet_network",
                    "manual_wallet_address",
                    "manual_sender_wallet",
                    "manual_tx_hash",
                    "manual_proof",
                    "manual_note",
                    "manual_reviewed_by",
                    "manual_reviewed_at",
                    "manual_review_decision",
                    "manual_review_note",
                ),
            },
        ),
        (
            "Dates",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                ),
                "classes": (
                    "collapse",
                ),
            },
        ),
    )

    def get_readonly_fields(
        self,
        request,
        obj=None,
    ):
        """
        Payment proof is immutable after the transaction exists.

        New records:
            manual_proof is editable and validated through the ModelForm.

        Existing records:
            manual_proof is read-only and cannot be silently replaced.
        """

        readonly = list(
            super().get_readonly_fields(
                request,
                obj,
            )
        )

        if obj is not None:
            readonly.extend(
                [
                    "user",
                    "order_id",
                    "gateway",
                    "status",
                    "amount",
                    "currency",
                    "customer_email",
                    "customer_name",
                    "customer_phone",
                    "gateway_reference",
                    "gateway_checkout_url",
                    "manual_wallet_network",
                    "manual_wallet_address",
                    "manual_sender_wallet",
                    "manual_tx_hash",
                    "manual_proof",
                    "manual_note",
                ]
            )

        return tuple(
            readonly
        )

    def has_add_permission(
        self,
        request,
    ):
        return False

    def has_delete_permission(
        self,
        request,
        obj=None,
    ):
        """
        Prevent deletion of payment audit records from Django Admin.

        Financial transaction records should be preserved and changed
        through explicit statuses rather than removed.
        """

        return False

    @admin.action(
        description="Approve selected manual crypto payments"
    )
    def approve_manual_crypto(
        self,
        request,
        queryset,
    ):
        approved = 0
        skipped = 0

        for payment in queryset.iterator():
            try:
                approve_manual_crypto_payment(
                    payment.pk,
                    request.user,
                )
                approved += 1
            except Exception:
                skipped += 1

        if approved:
            self.message_user(
                request,
                f"{approved} manual crypto payment(s) approved.",
                level=messages.SUCCESS,
            )

        if skipped:
            self.message_user(
                request,
                f"{skipped} payment(s) were not eligible for approval.",
                level=messages.WARNING,
            )

    @admin.action(
        description="Reject selected manual crypto payments"
    )
    def reject_manual_crypto(
        self,
        request,
        queryset,
    ):
        rejected = 0
        skipped = 0

        for payment in queryset.iterator():
            try:
                reject_manual_crypto_payment(
                    payment.pk,
                    request.user,
                )
                rejected += 1
            except Exception:
                skipped += 1

        if rejected:
            self.message_user(
                request,
                f"{rejected} manual crypto payment(s) rejected.",
                level=messages.SUCCESS,
            )

        if skipped:
            self.message_user(
                request,
                f"{skipped} payment(s) were not eligible for rejection.",
                level=messages.WARNING,
            )




# =============================================================================
# MANUAL CRYPTO WALLET
# =============================================================================


@admin.register(ManualCryptoWallet)
class ManualCryptoWalletAdmin(admin.ModelAdmin):
    list_display = (
        "network",
        "currency",
        "address_short",
        "is_active",
        "sort_order",
    )

    list_filter = (
        "currency",
        "network",
        "is_active",
    )

    search_fields = (
        "network",
        "currency",
        "address",
    )

    list_editable = (
        "is_active",
        "sort_order",
    )

    ordering = (
        "sort_order",
        "network",
    )

    fieldsets = (
        (
            "Wallet",
            {
                "fields": (
                    "network",
                    "currency",
                    "address",
                    "qr_code",
                ),
            },
        ),
        (
            "Visibility",
            {
                "fields": (
                    "is_active",
                    "sort_order",
                ),
            },
        ),
    )

    @admin.display(
        description="Wallet Address"
    )
    def address_short(
        self,
        obj,
    ):
        if len(obj.address) <= 22:
            return obj.address

        return (
            f"{obj.address[:12]}"
            "..."
            f"{obj.address[-8:]}"
        )


# =============================================================================
# PAYPAL WEBHOOK LOG
# =============================================================================


@admin.register(PayPalWebhookLog)
class PayPalWebhookLogAdmin(admin.ModelAdmin):
    list_display = (
        "event_id",
        "event_type",
        "resource_id",
        "status",
        "signature_verified",
        "payment",
        "attempts",
        "received_at",
        "processed_at",
    )

    list_filter = (
        "status",
        "signature_verified",
        "event_type",
        "received_at",
    )

    search_fields = (
        "event_id",
        "event_type",
        "resource_id",
        "payment__reference",
        "payment__gateway_reference",
        "payment__gateway_capture_id",
        "last_error",
    )

    readonly_fields = (
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
    )

    list_select_related = (
        "payment",
    )

    date_hierarchy = (
        "received_at"
    )

    ordering = (
        "-received_at",
    )

    list_per_page = 50

    fieldsets = (
        (
            "Event",
            {
                "fields": (
                    "event_id",
                    "event_type",
                    "resource_type",
                    "resource_id",
                    "status",
                    "signature_verified",
                    "payment",
                ),
            },
        ),
        (
            "Processing",
            {
                "fields": (
                    "attempts",
                    "last_error",
                    "verified_at",
                    "processed_at",
                ),
            },
        ),
        (
            "Payload",
            {
                "fields": (
                    "payload",
                    "request_headers",
                ),
                "classes": (
                    "collapse",
                ),
            },
        ),
        (
            "Dates",
            {
                "fields": (
                    "received_at",
                    "updated_at",
                ),
                "classes": (
                    "collapse",
                ),
            },
        ),
    )

    def has_add_permission(
        self,
        request,
    ):
        return False

    def has_change_permission(
        self,
        request,
        obj=None,
    ):
        """
        Allow viewing the change page but prevent submitted edits.

        GET is permitted so admins can inspect webhook records.
        POST/PUT/PATCH operations are blocked.
        """

        if request.method in {
            "GET",
            "HEAD",
            "OPTIONS",
        }:
            return True

        return False

    def has_delete_permission(
        self,
        request,
        obj=None,
    ):
        return False


# =============================================================================
# PAYMENT REFUNDS
# =============================================================================


@admin.register(PaymentRefund)
class PaymentRefundAdmin(admin.ModelAdmin):
    list_display = (
        "gateway_refund_id",
        "transaction",
        "order_id",
        "amount",
        "currency",
        "status",
        "refunded_at",
    )

    list_filter = (
        "gateway",
        "status",
        "currency",
        "refunded_at",
    )

    search_fields = (
        "gateway_refund_id",
        "gateway_capture_id",
        "order_id",
        "transaction__reference",
    )

    readonly_fields = (
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
    )

    list_select_related = (
        "transaction",
    )

    ordering = (
        "-refunded_at",
    )

    date_hierarchy = (
        "refunded_at"
    )

    list_per_page = 100

    fieldsets = (
        (
            "Refund",
            {
                "fields": (
                    "transaction",
                    "gateway",
                    "gateway_refund_id",
                    "gateway_capture_id",
                    "order_id",
                    "amount",
                    "currency",
                    "status",
                    "refunded_at",
                ),
            },
        ),
        (
            "Gateway Payload",
            {
                "fields": (
                    "payload",
                ),
                "classes": (
                    "collapse",
                ),
            },
        ),
        (
            "Dates",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                ),
                "classes": (
                    "collapse",
                ),
            },
        ),
    )

    def has_add_permission(
        self,
        request,
    ):
        return False

    def has_change_permission(
        self,
        request,
        obj=None,
    ):
        if request.method in {
            "GET",
            "HEAD",
            "OPTIONS",
        }:
            return True

        return False

    def has_delete_permission(
        self,
        request,
        obj=None,
    ):
        return False