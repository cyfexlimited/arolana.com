from django.db import transaction

from .models import Cart, Order, OrderItem


def _format_address(checkout_data):
    parts = [
        checkout_data.get('address', ''),
        checkout_data.get('city', ''),
        checkout_data.get('state', ''),
        checkout_data.get('postal_code', ''),
        checkout_data.get('country', ''),
    ]
    return "\n".join(part for part in parts if part).strip()


@transaction.atomic
def mark_order_paid(payment):
    """
    Payment success hook used by arolana_payments.

    If payment.order_id already points to an Order.order_number, mark it paid.
    During cart checkout it initially points to the active cart id, so this
    creates the order, copies cart items, marks payment paid, and closes cart.
    """
    if not payment.order_id:
        return None

    existing_order = Order.objects.filter(order_number=payment.order_id).first()
    if existing_order:
        existing_order.payment_status = 'paid'
        existing_order.payment_method = payment.gateway
        if existing_order.status == 'pending':
            existing_order.status = 'processing'
        existing_order.save(update_fields=['payment_status', 'payment_method', 'status', 'updated_at'])
        return existing_order

    if not payment.user or not str(payment.order_id).isdigit():
        return None

    cart = (
        Cart.objects
        .select_for_update()
        .filter(id=int(payment.order_id), user=payment.user, is_active=True)
        .prefetch_related('items')
        .first()
    )
    if not cart or not cart.items.exists():
        return None

    checkout_data = payment.checkout_data or {}
    shipping_address = _format_address(checkout_data) or 'Address submitted during payment'

    order = Order.objects.create(
        user=payment.user,
        status='processing',
        subtotal=cart.subtotal,
        shipping_cost=0,
        tax=0,
        total=cart.total,
        shipping_address=shipping_address,
        billing_address=shipping_address,
        payment_method=payment.gateway,
        payment_status='paid',
    )

    for item in cart.items.all():
        OrderItem.objects.create(
            order=order,
            product=item.product,
            variant=item.variant,
            accessory=item.accessory,
            quantity=item.quantity,
            price=item.price_at_add,
            subtotal=item.subtotal,
        )

    cart.is_active = False
    cart.save(update_fields=['is_active', 'updated_at'])

    payment.order_id = order.order_number
    payment.save(update_fields=['order_id', 'updated_at'])
    return order
