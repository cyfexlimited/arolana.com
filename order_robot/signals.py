from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender="deliveries.DeliveryRequest")
def sync_robot_from_live_delivery(sender, instance, created=False, raw=False, **kwargs):
    if raw:
        return
    try:
        from .services import sync_from_live_delivery

        sync_from_live_delivery(instance)
    except Exception:
        return


@receiver(post_save, sender="arolana_payments.PaymentTransaction")
def start_robot_when_payment_points_to_order(sender, instance, created=False, raw=False, **kwargs):
    if raw or instance.status != "success" or not instance.order_id:
        return
    update_fields = kwargs.get("update_fields")
    if update_fields and "status" not in update_fields and "paid_at" not in update_fields:
        return
    try:
        from orders.models import Order
        from .services import process_paid_order

        order = Order.objects.filter(order_number=instance.order_id, payment_status="paid").first()
        if order and order.items.exists():
            process_paid_order(order, payment=instance)
    except Exception:
        return
