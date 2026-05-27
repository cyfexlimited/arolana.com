from django.contrib import admin, messages
from django.urls import reverse
from django.utils.html import format_html

from .models import OrderRobotActivity, OrderRobotProcess, OrderRobotVendorTask
from .services import process_paid_order, vendor_mark_confirmed, vendor_mark_rejected


class OrderRobotActivityInline(admin.TabularInline):
    model = OrderRobotActivity
    extra = 0
    readonly_fields = ("status", "level", "actor", "message", "metadata", "created_at")
    can_delete = False


class OrderRobotVendorTaskInline(admin.TabularInline):
    model = OrderRobotVendorTask
    extra = 0
    readonly_fields = ("responded_at", "created_at", "updated_at")


@admin.register(OrderRobotProcess)
class OrderRobotProcessAdmin(admin.ModelAdmin):
    list_display = (
        "order_link",
        "current_status",
        "requires_admin",
        "payment",
        "delivery_summary",
        "attempts",
        "updated_at",
    )
    list_filter = ("current_status", "requires_admin", "created_at", "updated_at")
    search_fields = ("order__order_number", "payment__reference", "legacy_delivery__tracking_code", "live_delivery__tracking_code")
    readonly_fields = (
        "order",
        "payment",
        "legacy_delivery",
        "live_delivery",
        "attempts",
        "started_at",
        "vendor_notified_at",
        "vendor_confirmed_at",
        "ready_for_pickup_at",
        "delivery_created_at",
        "rider_assigned_at",
        "completed_at",
        "failed_at",
        "created_at",
        "updated_at",
    )
    inlines = [OrderRobotVendorTaskInline, OrderRobotActivityInline]
    actions = ["run_robot_now", "mark_ready_for_pickup", "escalate_for_admin"]

    def order_link(self, obj):
        url = reverse("admin:orders_order_change", args=[obj.order_id])
        return format_html('<a href="{}">{}</a>', url, obj.order.order_number)

    order_link.short_description = "Order"

    def delivery_summary(self, obj):
        if obj.live_delivery_id:
            url = reverse("admin:deliveries_deliveryrequest_change", args=[obj.live_delivery_id])
            return format_html('<a href="{}">Live: {}</a>', url, obj.live_delivery.tracking_code)
        if obj.legacy_delivery_id:
            url = reverse("admin:orders_deliveryrequest_change", args=[obj.legacy_delivery_id])
            return format_html('<a href="{}">Legacy: {}</a>', url, obj.legacy_delivery.tracking_code)
        return "No delivery"

    delivery_summary.short_description = "Delivery"

    @admin.action(description="Run Order Robot now")
    def run_robot_now(self, request, queryset):
        count = 0
        for process in queryset.select_related("order", "payment"):
            process_paid_order(process.order, payment=process.payment, actor=request.user)
            count += 1
        self.message_user(request, f"Order Robot rechecked {count} process(es).", messages.SUCCESS)

    @admin.action(description="Mark vendor flow ready for pickup")
    def mark_ready_for_pickup(self, request, queryset):
        for process in queryset:
            process.set_status(
                OrderRobotProcess.STATUS_READY_FOR_PICKUP,
                note="Admin marked order ready for pickup.",
                actor=request.user,
                level="success",
            )
        self.message_user(request, "Selected robot processes are ready for pickup.", messages.SUCCESS)

    @admin.action(description="Escalate to admin attention")
    def escalate_for_admin(self, request, queryset):
        for process in queryset:
            process.set_status(
                OrderRobotProcess.STATUS_NEEDS_ADMIN,
                note="Admin manually escalated this order.",
                actor=request.user,
                level="warning",
            )
        self.message_user(request, "Selected robot processes were escalated.", messages.WARNING)


@admin.register(OrderRobotVendorTask)
class OrderRobotVendorTaskAdmin(admin.ModelAdmin):
    list_display = ("process", "vendor", "status", "due_at", "responded_at", "updated_at")
    list_filter = ("status", "due_at", "created_at")
    search_fields = ("process__order__order_number", "vendor__email", "vendor__username")
    actions = ["mark_confirmed", "mark_ready", "mark_rejected"]

    @admin.action(description="Mark vendor confirmed")
    def mark_confirmed(self, request, queryset):
        for task in queryset.select_related("process", "vendor"):
            vendor_mark_confirmed(task, actor=request.user, note="Confirmed by admin.")
        self.message_user(request, "Vendor tasks confirmed.", messages.SUCCESS)

    @admin.action(description="Mark ready for pickup")
    def mark_ready(self, request, queryset):
        for task in queryset.select_related("process", "vendor"):
            vendor_mark_confirmed(task, ready=True, actor=request.user, note="Marked ready by admin.")
        self.message_user(request, "Vendor tasks marked ready for pickup.", messages.SUCCESS)

    @admin.action(description="Mark rejected / needs admin")
    def mark_rejected(self, request, queryset):
        for task in queryset.select_related("process", "vendor"):
            vendor_mark_rejected(task, actor=request.user, note="Rejected by admin.")
        self.message_user(request, "Vendor tasks rejected and escalated.", messages.WARNING)


@admin.register(OrderRobotActivity)
class OrderRobotActivityAdmin(admin.ModelAdmin):
    list_display = ("process", "status", "level", "actor", "created_at")
    list_filter = ("status", "level", "created_at")
    search_fields = ("process__order__order_number", "message")
    readonly_fields = ("process", "status", "level", "actor", "message", "metadata", "created_at", "updated_at")
