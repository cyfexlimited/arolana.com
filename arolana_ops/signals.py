from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from .models import OrderStatusHistory


def _notify_order_status(order, previous_status=""):
    try:
        from notifications.models import Notification
        from orders.delivery_notifications import send_expo_push_notification
    except Exception:
        return

    status = str(getattr(order, "status", "") or "pending")
    order_number = getattr(order, "order_number", order.id)
    title = "Order status updated"
    message = f"Your order {order_number} is now {status.replace('_', ' ').title()}."

    if getattr(order, "user_id", None):
        Notification.send(
            user=order.user,
            notification_type="order",
            title=title,
            message=message,
            link=f"/orders/{order_number}/",
            metadata={
                "order_number": order_number,
                "previous_status": previous_status,
                "order_status": status,
            },
            priority=3,
        )

    send_expo_push_notification(
        order,
        title=title,
        message=message,
        extra_data={
            "order_number": order_number,
            "previous_status": previous_status,
            "order_status": status,
        },
    )


@receiver(pre_save, sender="orders.Order")
def remember_previous_order_status(sender, instance, **kwargs):
    if not instance.pk:
        instance._ops_previous_status = None
        return

    previous = sender.objects.filter(pk=instance.pk).only("status").first()
    instance._ops_previous_status = previous.status if previous else None


@receiver(post_save, sender="orders.Order")
def order_status_history_and_push(sender, instance, created, raw=False, **kwargs):
    if raw:
        return

    previous_status = getattr(instance, "_ops_previous_status", None)
    status = str(getattr(instance, "status", "") or "")

    if created:
        OrderStatusHistory.objects.get_or_create(
            order=instance,
            status=status,
            message=f"Order created with status {status}",
        )
        return

    if previous_status == status:
        return

    OrderStatusHistory.objects.create(
        order=instance,
        status=status,
        message=f"Order status changed from {previous_status or 'unknown'} to {status}",
    )
    _notify_order_status(instance, previous_status=previous_status or "")
