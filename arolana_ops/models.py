from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from core.models import BaseModel
from products.models import Product


class OrderStatusHistory(BaseModel):
    order = models.ForeignKey(
        "orders.Order",
        on_delete=models.CASCADE,
        related_name="ops_status_history",
    )
    status = models.CharField(max_length=80)
    message = models.CharField(max_length=255, blank=True)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["order", "-created_at"]),
            models.Index(fields=["status", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.order} - {self.status}"


class PriceAlert(BaseModel):
    customer = models.ForeignKey(
        "mobile_customers.MobileCustomer",
        on_delete=models.CASCADE,
        related_name="price_alerts",
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="mobile_price_alerts",
    )
    target_price = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    last_seen_price = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    triggered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["customer", "product"], name="unique_mobile_customer_price_alert"),
        ]
        indexes = [
            models.Index(fields=["customer", "is_active"]),
            models.Index(fields=["product", "is_active"]),
        ]

    def __str__(self):
        return f"{self.customer} - {self.product}"

    def update_last_seen_price(self):
        price = getattr(self.product, "price", None) or Decimal("0.00")
        self.last_seen_price = Decimal(str(price or 0)).quantize(Decimal("0.01"))
        self.save(update_fields=["last_seen_price", "updated_at"])


class ProductInteraction(BaseModel):
    customer = models.ForeignKey(
        "mobile_customers.MobileCustomer",
        on_delete=models.CASCADE,
        related_name="product_interactions",
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="mobile_interactions",
    )
    view_count = models.PositiveIntegerField(default=0)
    last_viewed_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-last_viewed_at"]
        constraints = [
            models.UniqueConstraint(fields=["customer", "product"], name="unique_mobile_customer_product_interaction"),
        ]
        indexes = [
            models.Index(fields=["customer", "-last_viewed_at"]),
            models.Index(fields=["customer", "-view_count"]),
            models.Index(fields=["product", "-last_viewed_at"]),
        ]

    def __str__(self):
        return f"{self.customer} viewed {self.product} ({self.view_count})"
