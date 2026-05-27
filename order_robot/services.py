from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from .models import OrderRobotProcess, OrderRobotVendorTask


def _order_link(order):
    try:
        return reverse("orders:detail", args=[order.order_number])
    except Exception:
        return f"/orders/{order.order_number}/"


def _vendor_robot_link():
    try:
        return reverse("dashboard:vendor_order_robot_tasks")
    except Exception:
        return "/dashboard/vendor/order-robot/"


def _site_url():
    return str(getattr(settings, "SITE_URL", "https://arolana.com") or "https://arolana.com").rstrip("/")


def _absolute_link(path):
    if not path:
        return _site_url()
    if str(path).startswith(("http://", "https://")):
        return str(path)
    return f"{_site_url()}{path}"


def _notify_user(user, notification_type, title, message, link="", metadata=None, priority=2):
    if not user:
        return None
    try:
        from notifications.models import Notification

        return Notification.send(
            user=user,
            notification_type=notification_type,
            title=title,
            message=message,
            link=link,
            metadata=metadata or {},
            priority=priority,
        )
    except Exception:
        return None


def _notify_staff(title, message, link="", metadata=None, priority=3):
    try:
        from notifications.models import Notification
    except Exception:
        return

    User = get_user_model()
    staff_users = User.objects.filter(is_active=True, is_staff=True)
    for staff in staff_users:
        Notification.send(
            user=staff,
            notification_type="order",
            title=title,
            message=message,
            link=link,
            metadata=metadata or {},
            priority=priority,
        )


def _notify_vendor(vendor, title, message, link="", metadata=None):
    _notify_user(
        vendor,
        "vendor",
        title,
        message,
        link=link,
        metadata=metadata or {},
        priority=3,
    )
    try:
        from dashboard.models import VendorNotification

        VendorNotification.objects.create(
            vendor=vendor,
            title=title,
            message=message,
            notification_type="order_new",
            action_url=link,
            metadata=metadata or {},
        )
    except Exception:
        pass


def _send_vendor_email(vendor, order, task):
    email = getattr(vendor, "email", "")
    if not email:
        return
    subject = f"New Arolana order needs confirmation - {order.order_number}"
    message = (
        f"A paid Arolana order needs your confirmation.\n\n"
        f"Order: {order.order_number}\n"
        f"Task: #{task.id}\n"
        f"Please confirm product availability, package the order, and mark it ready for pickup.\n\n"
        f"Open your robot tasks: {_absolute_link(_vendor_robot_link())}"
    )
    send_mail(
        subject,
        message,
        getattr(settings, "DEFAULT_FROM_EMAIL", None),
        [email],
        fail_silently=True,
    )


def _unique_order_vendors(order):
    vendors = []
    seen = set()
    items = order.items.select_related("product__vendor", "variant__product__vendor", "accessory").all()
    for item in items:
        vendor = getattr(getattr(item, "product", None), "vendor", None)
        if not vendor and item.variant_id:
            vendor = getattr(getattr(item.variant, "product", None), "vendor", None)
        if vendor and vendor.id not in seen:
            seen.add(vendor.id)
            vendors.append(vendor)
    return vendors


def check_product_availability(order):
    issues = []
    warnings = []
    for item in order.items.select_related("product", "variant", "variant__product").all():
        product = item.product or getattr(item.variant, "product", None)
        if not product:
            continue
        if not getattr(product, "is_active", True):
            issues.append(f"{product.name} is inactive.")
            continue
        if getattr(product, "approval_status", "approved") != "approved":
            warnings.append(f"{product.name} is not approved yet.")
        available = None
        if hasattr(product, "get_available_stock"):
            available = product.get_available_stock()
        elif hasattr(product, "available_stock"):
            available = product.available_stock
        elif hasattr(product, "stock_quantity"):
            available = product.stock_quantity
        allow_backorder = bool(getattr(product, "allow_backorder", False))
        if available is not None and available < item.quantity and not allow_backorder:
            issues.append(f"{product.name} has {available} available, but order needs {item.quantity}.")
        elif available is not None and available <= getattr(product, "low_stock_threshold", 0):
            warnings.append(f"{product.name} is low in stock ({available} left).")
    return issues, warnings


def _sync_delivery_links(process):
    order = process.order
    legacy_delivery = process.legacy_delivery or order.delivery_requests.order_by("-created_at").first()
    live_delivery = process.live_delivery or order.live_delivery_requests.order_by("-created_at").first()
    fields = []
    if legacy_delivery and process.legacy_delivery_id != legacy_delivery.id:
        process.legacy_delivery = legacy_delivery
        fields.append("legacy_delivery")
    if live_delivery and process.live_delivery_id != live_delivery.id:
        process.live_delivery = live_delivery
        fields.append("live_delivery")
    if fields:
        fields.append("updated_at")
        process.save(update_fields=fields)
    if live_delivery:
        process.set_status(
            OrderRobotProcess.STATUS_DELIVERY_CREATED,
            note=f"Live delivery created with tracking code {live_delivery.tracking_code}.",
            metadata={"live_delivery_id": live_delivery.id, "tracking_code": live_delivery.tracking_code},
        )
        if live_delivery.rider_id or live_delivery.status in {
            live_delivery.STATUS_ASSIGNED,
            live_delivery.STATUS_ACCEPTED,
            live_delivery.STATUS_PICKED_UP,
            live_delivery.STATUS_IN_TRANSIT,
            live_delivery.STATUS_ARRIVED_CUSTOMER,
            live_delivery.STATUS_DELIVERED,
        }:
            process.set_status(
                OrderRobotProcess.STATUS_RIDER_ASSIGNED,
                note="Delivery has been assigned to a rider.",
                metadata={"live_delivery_id": live_delivery.id, "rider_id": live_delivery.rider_id},
                level="success",
            )
    elif legacy_delivery:
        process.set_status(
            OrderRobotProcess.STATUS_DELIVERY_CREATED,
            note=f"Delivery request created with tracking code {legacy_delivery.tracking_code}.",
            metadata={"legacy_delivery_id": legacy_delivery.id, "tracking_code": legacy_delivery.tracking_code},
        )
    else:
        process.set_status(
            OrderRobotProcess.STATUS_NEEDS_ADMIN,
            note="Payment is confirmed, but no delivery request was found.",
            metadata={"order_number": order.order_number},
            level="warning",
        )
        _notify_staff(
            "Order Robot needs delivery setup",
            f"Order {order.order_number} is paid, but no delivery request exists.",
            link=_order_link(order),
            metadata={"order_number": order.order_number},
            priority=4,
        )
    return live_delivery or legacy_delivery


def release_delivery_to_riders(process, actor=None, note=""):
    delivery = process.live_delivery or process.order.live_delivery_requests.order_by("-created_at").first()
    if not delivery:
        return escalate_to_admin(
            process,
            "Vendor marked order ready, but no live delivery request exists.",
            metadata={"order_number": process.order.order_number},
            actor=actor,
        )
    if delivery.status in {
        delivery.STATUS_DELIVERED,
        delivery.STATUS_CANCELLED,
        delivery.STATUS_FAILED,
        delivery.STATUS_RETURNED,
    }:
        return escalate_to_admin(
            process,
            f"Vendor marked order ready, but delivery {delivery.tracking_code} is already {delivery.get_status_display()}.",
            metadata={"order_number": process.order.order_number, "live_delivery_id": delivery.id},
            actor=actor,
        )

    if not delivery.is_ready_for_rider:
        delivery.is_ready_for_rider = True
        delivery.save(update_fields=["is_ready_for_rider", "updated_at"])
        delivery.status_history.create(
            status=delivery.status,
            actor=actor,
            note=note or "Vendor confirmed package is ready. Delivery released to riders.",
        )

    process.set_status(
        OrderRobotProcess.STATUS_READY_FOR_PICKUP,
        note=note or "Order is ready for rider pickup.",
        actor=actor,
        metadata={"live_delivery_id": delivery.id, "tracking_code": delivery.tracking_code},
        level="success",
    )

    assigned_rider = None
    try:
        from deliveries.services import assign_nearest_rider

        assigned_rider = assign_nearest_rider(delivery)
    except Exception as error:
        process.activities.create(
            status=process.current_status,
            level="warning",
            actor=actor,
            message=f"Nearest-rider assignment failed: {error}",
            metadata={"live_delivery_id": delivery.id},
        )

    if assigned_rider:
        rider_phone = getattr(assigned_rider, "phone", "") or "phone pending"
        process.set_status(
            OrderRobotProcess.STATUS_RIDER_ASSIGNED,
            note=f"Nearest rider assigned: {assigned_rider}.",
            actor=actor,
            metadata={"live_delivery_id": delivery.id, "rider_id": assigned_rider.id},
            level="success",
        )
        _notify_staff(
            "Rider assigned after vendor confirmation",
            f"Order {process.order.order_number} is ready and assigned to {assigned_rider}.",
            link=_order_link(process.order),
            metadata={"order_number": process.order.order_number, "live_delivery_id": delivery.id, "rider_id": assigned_rider.id},
            priority=3,
        )
        _notify_user(
            process.order.user,
            "shipping",
            "Arolana rider assigned",
            (
                f"Order {process.order.order_number} is ready for pickup and has been assigned to "
                f"{assigned_rider}. Rider phone: {rider_phone}."
            ),
            link=_order_link(process.order),
            metadata={
                "order_number": process.order.order_number,
                "tracking_code": delivery.tracking_code,
                "live_delivery_id": delivery.id,
                "rider_id": assigned_rider.id,
            },
            priority=3,
        )
    else:
        _notify_staff(
            "Delivery ready but no nearby rider yet",
            (
                f"Order {process.order.order_number} is ready for pickup, but no approved online rider "
                "was available near the vendor pickup point."
            ),
            link=_order_link(process.order),
            metadata={"order_number": process.order.order_number, "live_delivery_id": delivery.id},
            priority=4,
        )

        _notify_user(
            process.order.user,
            "shipping",
            "Your order is ready for dispatch",
            (
                f"Order {process.order.order_number} has been confirmed by the vendor and is ready for rider pickup. "
                "We are looking for the nearest approved rider now."
            ),
            link=_order_link(process.order),
            metadata={"order_number": process.order.order_number, "tracking_code": delivery.tracking_code},
            priority=2,
        )
    return process


def notify_vendors(process):
    order = process.order
    vendors = _unique_order_vendors(order)
    if not vendors:
        process.set_status(
            OrderRobotProcess.STATUS_NEEDS_ADMIN,
            note="No vendor was found on this order. Admin must confirm fulfillment manually.",
            metadata={"order_number": order.order_number},
            level="warning",
        )
        return []

    tasks = []
    due_at = timezone.now() + timedelta(hours=6)
    order_url = _vendor_robot_link()
    for vendor in vendors:
        task, created = OrderRobotVendorTask.objects.get_or_create(
            process=process,
            vendor=vendor,
            defaults={"due_at": due_at},
        )
        tasks.append(task)
        if created:
            _notify_vendor(
                vendor,
                "New paid order needs confirmation",
                f"Order {order.order_number} is paid. Please confirm stock and prepare items for pickup.",
                link=order_url,
                metadata={"order_number": order.order_number, "robot_task_id": task.id},
            )
            _send_vendor_email(vendor, order, task)

    process.set_status(
        OrderRobotProcess.STATUS_VENDOR_NOTIFIED,
        note=f"Robot notified {len(tasks)} vendor(s) for fulfillment confirmation.",
        metadata={"vendor_task_ids": [task.id for task in tasks]},
        level="success",
    )
    return tasks


@transaction.atomic
def process_paid_order(order, payment=None, actor=None):
    process, created = OrderRobotProcess.objects.select_for_update().get_or_create(
        order=order,
        defaults={"payment": payment},
    )
    update_fields = []
    if payment and process.payment_id != payment.id:
        process.payment = payment
        update_fields.append("payment")
    if update_fields:
        update_fields.append("updated_at")
        process.save(update_fields=update_fields)

    should_send_kickoff_notifications = not (process.metadata or {}).get("paid_order_robot_notified")

    process.attempts = process.attempts + 1
    process.save(update_fields=["attempts", "updated_at"])

    process.set_status(
        OrderRobotProcess.STATUS_PAYMENT_CONFIRMED,
        note=(
            "Order Robot started after payment confirmation."
            if created else
            "Order Robot rechecked this paid order."
        ),
        metadata={"order_number": order.order_number, "payment_id": getattr(payment, "id", None)},
        actor=actor,
        level="success",
    )

    issues, warnings = check_product_availability(order)
    if warnings:
        process.activities.create(
            status=process.current_status,
            level="warning",
            actor=actor,
            message="Inventory warning: " + " ".join(warnings),
            metadata={"warnings": warnings},
        )
    if issues:
        process.set_status(
            OrderRobotProcess.STATUS_NEEDS_ADMIN,
            note="Inventory needs admin attention: " + " ".join(issues),
            metadata={"issues": issues},
            actor=actor,
            level="warning",
        )
        _notify_staff(
            "Order Robot found inventory issue",
            f"Order {order.order_number} needs admin review. {' '.join(issues)}",
            link=_order_link(order),
            metadata={"order_number": order.order_number, "issues": issues},
            priority=4,
        )

    notify_vendors(process)
    delivery = _sync_delivery_links(process)

    if should_send_kickoff_notifications:
        _notify_user(
            order.user,
            "order",
            "Arolana Order Robot is handling your order",
            (
                f"Payment for order {order.order_number} is confirmed. "
                "We have notified the vendor and started delivery preparation."
            ),
            link=_order_link(order),
            metadata={
                "order_number": order.order_number,
                "robot_status": process.current_status,
                "delivery_id": getattr(delivery, "id", None),
            },
            priority=2,
        )
        _notify_staff(
            "Order Robot processed paid order",
            f"Order {order.order_number} payment is confirmed. Vendor and delivery coordination has started.",
            link=_order_link(order),
            metadata={"order_number": order.order_number, "robot_process_id": process.id},
            priority=2,
        )
        metadata = dict(process.metadata or {})
        metadata["paid_order_robot_notified"] = True
        process.metadata = metadata
        process.save(update_fields=["metadata", "updated_at"])
    return process


@transaction.atomic
def vendor_mark_confirmed(task, ready=False, actor=None, note=""):
    task.mark(
        OrderRobotVendorTask.STATUS_READY_FOR_PICKUP if ready else OrderRobotVendorTask.STATUS_CONFIRMED,
        note=note,
        actor=actor,
    )
    process = task.process
    all_confirmed = not process.vendor_tasks.exclude(
        status__in=[
            OrderRobotVendorTask.STATUS_CONFIRMED,
            OrderRobotVendorTask.STATUS_READY_FOR_PICKUP,
        ]
    ).exists()
    all_ready = not process.vendor_tasks.exclude(status=OrderRobotVendorTask.STATUS_READY_FOR_PICKUP).exists()

    if all_confirmed:
        process.set_status(
            OrderRobotProcess.STATUS_READY_FOR_PICKUP if all_ready else OrderRobotProcess.STATUS_VENDOR_CONFIRMED,
            note="All vendors have confirmed this order." if not all_ready else "All vendors marked the order ready for rider pickup.",
            actor=actor,
            level="success",
        )
        if all_ready:
            release_delivery_to_riders(
                process,
                actor=actor,
                note=note or "All vendor packages are ready for rider pickup.",
            )
    return process


@transaction.atomic
def vendor_mark_rejected(task, actor=None, note=""):
    task.mark(OrderRobotVendorTask.STATUS_REJECTED, note=note, actor=actor)
    process = task.process
    delivery = process.live_delivery or process.order.live_delivery_requests.order_by("-created_at").first()
    if delivery:
        delivery.is_ready_for_rider = False
        delivery.save(update_fields=["is_ready_for_rider", "updated_at"])
        if delivery.status in {
            delivery.STATUS_PENDING,
            delivery.STATUS_ASSIGNED,
            delivery.STATUS_ACCEPTED,
        }:
            delivery.set_status(
                delivery.STATUS_CANCELLED,
                actor=actor,
                note="Vendor rejected fulfillment before pickup. Delivery dispatch paused for admin review.",
            )

    reason = note or "Vendor rejected fulfillment because stock or package availability needs review."
    _notify_user(
        process.order.user,
        "warning",
        "Arolana is reviewing your order availability",
        (
            f"The vendor reported an availability issue for order {process.order.order_number}. "
            "Arolana admin has been notified and will resolve it with a replacement, updated timeline, or refund option."
        ),
        link=_order_link(process.order),
        metadata={"order_number": process.order.order_number, "vendor_task_id": task.id},
        priority=3,
    )
    return escalate_to_admin(
        process,
        reason,
        metadata={"vendor_task_id": task.id, "vendor_id": task.vendor_id},
        actor=actor,
    )


@transaction.atomic
def escalate_to_admin(process, reason, metadata=None, actor=None):
    process.set_status(
        OrderRobotProcess.STATUS_NEEDS_ADMIN,
        note=reason,
        metadata=metadata or {},
        actor=actor,
        level="warning",
    )
    _notify_staff(
        "Order Robot needs admin action",
        f"Order {process.order.order_number}: {reason}",
        link=_order_link(process.order),
        metadata={"order_number": process.order.order_number, "robot_process_id": process.id, **(metadata or {})},
        priority=4,
    )
    return process


@transaction.atomic
def sync_from_live_delivery(delivery):
    order = delivery.order
    process = OrderRobotProcess.objects.filter(order=order).first()
    if not process:
        process = OrderRobotProcess.objects.create(order=order, live_delivery=delivery)
    elif process.live_delivery_id != delivery.id:
        process.live_delivery = delivery
        process.save(update_fields=["live_delivery", "updated_at"])

    status_map = {
        delivery.STATUS_PENDING: OrderRobotProcess.STATUS_DELIVERY_CREATED,
        delivery.STATUS_ASSIGNED: OrderRobotProcess.STATUS_RIDER_ASSIGNED,
        delivery.STATUS_ACCEPTED: OrderRobotProcess.STATUS_RIDER_ASSIGNED,
        delivery.STATUS_ARRIVED_PICKUP: OrderRobotProcess.STATUS_RIDER_ASSIGNED,
        delivery.STATUS_PICKED_UP: OrderRobotProcess.STATUS_PICKED_UP,
        delivery.STATUS_IN_TRANSIT: OrderRobotProcess.STATUS_IN_TRANSIT,
        delivery.STATUS_ARRIVED_CUSTOMER: OrderRobotProcess.STATUS_IN_TRANSIT,
        delivery.STATUS_DELIVERED: OrderRobotProcess.STATUS_DELIVERED,
        delivery.STATUS_CANCELLED: OrderRobotProcess.STATUS_NEEDS_ADMIN,
        delivery.STATUS_FAILED: OrderRobotProcess.STATUS_FAILED,
        delivery.STATUS_RETURNED: OrderRobotProcess.STATUS_NEEDS_ADMIN,
    }
    robot_status = status_map.get(delivery.status)
    if robot_status:
        process.set_status(
            robot_status,
            note=f"Delivery {delivery.tracking_code} moved to {delivery.get_status_display()}.",
            metadata={"live_delivery_id": delivery.id, "delivery_status": delivery.status},
            level="success" if delivery.status == delivery.STATUS_DELIVERED else "info",
        )

    if delivery.status == delivery.STATUS_DELIVERED:
        if order.status != "delivered":
            order.status = "delivered"
            order.save(update_fields=["status", "updated_at"])
        process.set_status(
            OrderRobotProcess.STATUS_COMPLETED,
            note="Order completed after delivery confirmation.",
            metadata={"live_delivery_id": delivery.id},
            level="success",
        )
        metadata = dict(process.metadata or {})
        notify_key = f"delivered_notified_{delivery.id}"
        if not metadata.get(notify_key):
            _notify_user(
                order.user,
                "success",
                "Order delivered",
                f"Order {order.order_number} has been delivered. Thank you for buying from Arolana.",
                link=_order_link(order),
                metadata={"order_number": order.order_number, "tracking_code": delivery.tracking_code},
                priority=3,
            )
            metadata[notify_key] = True
            process.metadata = metadata
            process.save(update_fields=["metadata", "updated_at"])
    elif delivery.status in {delivery.STATUS_FAILED, delivery.STATUS_CANCELLED, delivery.STATUS_RETURNED}:
        escalate_to_admin(
            process,
            f"Delivery {delivery.tracking_code} is {delivery.get_status_display()} and needs review.",
            metadata={"live_delivery_id": delivery.id, "delivery_status": delivery.status},
        )
    elif delivery.status == delivery.STATUS_ARRIVED_CUSTOMER:
        metadata = dict(process.metadata or {})
        notify_key = f"arrived_customer_notified_{delivery.id}"
        if not metadata.get(notify_key):
            customer_message = (
                f"Your Arolana rider has arrived at your delivery location for order {order.order_number}. "
                "Please be available to receive your package and confirm the handoff."
            )
            _notify_user(
                order.user,
                "shipping",
                "Rider has arrived at your location",
                customer_message,
                link=_order_link(order),
                metadata={"order_number": order.order_number, "tracking_code": delivery.tracking_code, "live_delivery_id": delivery.id},
                priority=4,
            )
            _notify_staff(
                "Rider arrived at customer location",
                f"Rider has arrived at the customer location for order {order.order_number}. Monitor the handoff until delivery is marked complete.",
                link=_order_link(order),
                metadata={"order_number": order.order_number, "tracking_code": delivery.tracking_code, "live_delivery_id": delivery.id},
                priority=3,
            )
            metadata[notify_key] = True
            process.metadata = metadata
            process.save(update_fields=["metadata", "updated_at"])
    return process


def run_robot_for_paid_orders(limit=25):
    from orders.models import Order

    results = []
    orders = Order.objects.filter(payment_status="paid").order_by("-created_at")[:limit]
    for order in orders:
        results.append(process_paid_order(order))
    return results
