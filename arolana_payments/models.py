import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone


class PaymentMethod(models.TextChoices):
    FLUTTERWAVE = "flutterwave", "Flutterwave"
    PAYPAL = "paypal", "PayPal"
    STRIPE = "stripe", "Stripe / Card"
    COINBASE = "coinbase", "Coinbase Commerce Crypto"
    MANUAL_CRYPTO = "manual_crypto", "Manual Crypto Wallet Transfer"


class PaymentStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PROCESSING = "processing", "Processing"
    SUCCESS = "success", "Success"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"
    REVIEW = "review", "Manual Review"
    REFUNDED = "refunded", "Refunded"


class PaymentTransaction(models.Model):
    """
    Gateway-neutral payment record.

    order_id is intentionally stored as text so this app can work even if your
    Arolana Order model lives in a different app or uses a custom primary key.
    """

    reference = models.CharField(max_length=80, unique=True, db_index=True, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="arolana_payment_transactions",
    )
    order_id = models.CharField(max_length=120, blank=True, db_index=True)

    gateway = models.CharField(max_length=30, choices=PaymentMethod.choices)
    status = models.CharField(max_length=30, choices=PaymentStatus.choices, default=PaymentStatus.PENDING)

    amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=10, default="NGN")

    customer_email = models.EmailField(blank=True)
    customer_name = models.CharField(max_length=180, blank=True)
    customer_phone = models.CharField(max_length=40, blank=True)

    gateway_reference = models.CharField(max_length=220, blank=True, db_index=True)
    gateway_checkout_url = models.URLField(blank=True, max_length=1000)
    gateway_response = models.JSONField(default=dict, blank=True)
    webhook_payload = models.JSONField(default=dict, blank=True)

    manual_wallet_network = models.CharField(max_length=80, blank=True)
    manual_wallet_address = models.CharField(max_length=255, blank=True)
    manual_sender_wallet = models.CharField(max_length=255, blank=True)
    manual_tx_hash = models.CharField(max_length=255, blank=True)
    manual_proof = models.FileField(upload_to="payment_proofs/", blank=True, null=True)
    manual_note = models.TextField(blank=True)

    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["gateway", "status"]),
            models.Index(fields=["order_id", "status"]),
        ]

    def __str__(self):
        return f"{self.reference} - {self.gateway} - {self.status}"

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = f"AROLANA-{timezone.now():%Y%m%d}-{uuid.uuid4().hex[:12].upper()}"
        super().save(*args, **kwargs)

    @property
    def amount_as_decimal(self):
        return Decimal(str(self.amount))

    def mark_success(self, gateway_reference="", payload=None):
        self.status = PaymentStatus.SUCCESS
        self.paid_at = timezone.now()
        if gateway_reference:
            self.gateway_reference = gateway_reference
        if payload is not None:
            self.webhook_payload = payload
        self.save(update_fields=["status", "paid_at", "gateway_reference", "webhook_payload", "updated_at"])

    def mark_failed(self, payload=None):
        self.status = PaymentStatus.FAILED
        if payload is not None:
            self.webhook_payload = payload
        self.save(update_fields=["status", "webhook_payload", "updated_at"])


class ManualCryptoWallet(models.Model):
    network = models.CharField(max_length=80, help_text="Example: USDT TRC20, USDT ERC20, BTC, ETH")
    currency = models.CharField(max_length=20, default="USDT")
    address = models.CharField(max_length=255)
    qr_code = models.ImageField(upload_to="crypto_wallet_qr/", blank=True, null=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "network"]

    def __str__(self):
        return f"{self.currency} - {self.network}"
