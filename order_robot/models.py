from django.conf import settings
from django.db import models
from django.utils import timezone

from core.models import BaseModel


class OrderRobotProcess(BaseModel):
    STATUS_NEW_ORDER = "new_order"
    STATUS_PAYMENT_CONFIRMED = "payment_confirmed"
    STATUS_VENDOR_NOTIFIED = "vendor_notified"
    STATUS_VENDOR_CONFIRMED = "vendor_confirmed"
    STATUS_PACKAGING = "packaging"
    STATUS_READY_FOR_PICKUP = "ready_for_pickup"
    STATUS_DELIVERY_CREATED = "delivery_created"
    STATUS_RIDER_ASSIGNED = "rider_assigned"
    STATUS_PICKED_UP = "picked_up"
    STATUS_IN_TRANSIT = "in_transit"
    STATUS_DELIVERED = "delivered"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"
    STATUS_NEEDS_ADMIN = "needs_admin"

    STATUS_CHOICES = [
        (STATUS_NEW_ORDER, "New Order"),
        (STATUS_PAYMENT_CONFIRMED, "Payment Confirmed"),
        (STATUS_VENDOR_NOTIFIED, "Vendor Notified"),
        (STATUS_VENDOR_CONFIRMED, "Vendor Confirmed"),
        (STATUS_PACKAGING, "Packaging"),
        (STATUS_READY_FOR_PICKUP, "Ready for Pickup"),
        (STATUS_DELIVERY_CREATED, "Delivery Created"),
        (STATUS_RIDER_ASSIGNED, "Rider Assigned"),
        (STATUS_PICKED_UP, "Picked Up"),
        (STATUS_IN_TRANSIT, "In Transit"),
        (STATUS_DELIVERED, "Delivered"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_FAILED, "Failed"),
        (STATUS_NEEDS_ADMIN, "Needs Admin"),
    ]

    order = models.OneToOneField("orders.Order", on_delete=models.CASCADE, related_name="robot_process")
    payment = models.ForeignKey(
        "arolana_payments.PaymentTransaction",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="robot_processes",
    )
    legacy_delivery = models.ForeignKey(
        "orders.DeliveryRequest",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="robot_processes",
    )
    live_delivery = models.ForeignKey(
        "deliveries.DeliveryRequest",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="robot_processes",
    )
    current_status = models.CharField(max_length=40, choices=STATUS_CHOICES, default=STATUS_NEW_ORDER, db_index=True)
    attempts = models.PositiveIntegerField(default=0)
    requires_admin = models.BooleanField(default=False, db_index=True)
    last_error = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    vendor_notified_at = models.DateTimeField(null=True, blank=True)
    vendor_confirmed_at = models.DateTimeField(null=True, blank=True)
    ready_for_pickup_at = models.DateTimeField(null=True, blank=True)
    delivery_created_at = models.DateTimeField(null=True, blank=True)
    rider_assigned_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["current_status", "-created_at"]),
            models.Index(fields=["requires_admin", "-created_at"]),
        ]
        verbose_name = "Order Robot Process"
        verbose_name_plural = "Order Robot Processes"

    def __str__(self):
        return f"Robot for {self.order.order_number} - {self.get_current_status_display()}"

    def set_status(self, status, note="", metadata=None, actor=None, level="info", save=True):
        if status not in dict(self.STATUS_CHOICES):
            raise ValueError(f"Unknown robot status: {status}")

        now = timezone.now()
        changed = self.current_status != status
        self.current_status = status
        update_fields = ["current_status", "updated_at"]

        timestamp_map = {
            self.STATUS_PAYMENT_CONFIRMED: "started_at",
            self.STATUS_VENDOR_NOTIFIED: "vendor_notified_at",
            self.STATUS_VENDOR_CONFIRMED: "vendor_confirmed_at",
            self.STATUS_READY_FOR_PICKUP: "ready_for_pickup_at",
            self.STATUS_DELIVERY_CREATED: "delivery_created_at",
            self.STATUS_RIDER_ASSIGNED: "rider_assigned_at",
            self.STATUS_COMPLETED: "completed_at",
            self.STATUS_FAILED: "failed_at",
            self.STATUS_NEEDS_ADMIN: "failed_at",
        }
        timestamp_field = timestamp_map.get(status)
        if timestamp_field and not getattr(self, timestamp_field):
            setattr(self, timestamp_field, now)
            update_fields.append(timestamp_field)

        if status in {self.STATUS_FAILED, self.STATUS_NEEDS_ADMIN}:
            self.requires_admin = True
            update_fields.append("requires_admin")
            if note:
                self.last_error = note
                update_fields.append("last_error")

        if metadata:
            merged = dict(self.metadata or {})
            merged.update(metadata)
            self.metadata = merged
            update_fields.append("metadata")

        if save:
            self.save(update_fields=update_fields)

        if changed or note:
            OrderRobotActivity.objects.create(
                process=self,
                status=status,
                level=level,
                actor=actor,
                message=note or self.get_current_status_display(),
                metadata=metadata or {},
            )


class OrderRobotActivity(BaseModel):
    LEVEL_INFO = "info"
    LEVEL_SUCCESS = "success"
    LEVEL_WARNING = "warning"
    LEVEL_ERROR = "error"

    LEVEL_CHOICES = [
        (LEVEL_INFO, "Info"),
        (LEVEL_SUCCESS, "Success"),
        (LEVEL_WARNING, "Warning"),
        (LEVEL_ERROR, "Error"),
    ]

    process = models.ForeignKey(OrderRobotProcess, on_delete=models.CASCADE, related_name="activities")
    status = models.CharField(max_length=40, choices=OrderRobotProcess.STATUS_CHOICES, db_index=True)
    level = models.CharField(max_length=20, choices=LEVEL_CHOICES, default=LEVEL_INFO)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="order_robot_activities",
    )
    message = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Order Robot Activity"
        verbose_name_plural = "Order Robot Activities"

    def __str__(self):
        return f"{self.process.order.order_number} - {self.get_status_display()}"


class OrderRobotVendorTask(BaseModel):
    STATUS_PENDING = "pending"
    STATUS_CONFIRMED = "confirmed"
    STATUS_REJECTED = "rejected"
    STATUS_READY_FOR_PICKUP = "ready_for_pickup"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending Vendor"),
        (STATUS_CONFIRMED, "Vendor Confirmed"),
        (STATUS_REJECTED, "Vendor Rejected"),
        (STATUS_READY_FOR_PICKUP, "Ready for Pickup"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    process = models.ForeignKey(OrderRobotProcess, on_delete=models.CASCADE, related_name="vendor_tasks")
    vendor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="order_robot_vendor_tasks",
    )
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    due_at = models.DateTimeField(null=True, blank=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = [("process", "vendor")]
        indexes = [
            models.Index(fields=["vendor", "status", "-created_at"]),
            models.Index(fields=["status", "-created_at"]),
        ]
        verbose_name = "Order Robot Vendor Task"
        verbose_name_plural = "Order Robot Vendor Tasks"

    def __str__(self):
        return f"{self.process.order.order_number} - {self.vendor}"

    def mark(self, status, note="", actor=None):
        if status not in dict(self.STATUS_CHOICES):
            raise ValueError(f"Unknown vendor task status: {status}")
        self.status = status
        self.note = note or self.note
        self.responded_at = timezone.now()
        self.save(update_fields=["status", "note", "responded_at", "updated_at"])
        self.process.activities.create(
            status=OrderRobotProcess.STATUS_VENDOR_CONFIRMED if status != self.STATUS_REJECTED else OrderRobotProcess.STATUS_NEEDS_ADMIN,
            level="warning" if status == self.STATUS_REJECTED else "success",
            actor=actor,
            message=f"Vendor {self.vendor} marked task as {self.get_status_display()}. {note}".strip(),
            metadata={"vendor_task_id": self.id, "vendor_id": self.vendor_id},
        )
