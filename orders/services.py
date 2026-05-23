from decimal import Decimal, InvalidOperation

from django.contrib.auth import get_user_model
from django.db import transaction
from django.urls import reverse

from .models import Cart, DeliveryProvider, DeliveryRequest, Order, OrderItem


def _as_money(value, default='0.00'):
    try:
        return Decimal(str(value if value not in (None, '') else default)).quantize(Decimal('0.01'))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default).quantize(Decimal('0.01'))


def _format_address(checkout_data):
    parts = [
        checkout_data.get('address', ''),
        checkout_data.get('city', ''),
        checkout_data.get('state', ''),
        checkout_data.get('postal_code', ''),
        checkout_data.get('country', ''),
    ]
    return "\n".join(part for part in parts if part).strip()


def select_delivery_provider(service_level, provider_id=None):
    if provider_id:
        provider = DeliveryProvider.objects.filter(id=provider_id, is_active=True).first()
        if provider:
            return provider

    provider_type_map = {
        DeliveryRequest.SERVICE_STANDARD: DeliveryProvider.PROVIDER_MANUAL_DISPATCH,
        DeliveryRequest.SERVICE_EXPRESS: DeliveryProvider.PROVIDER_AROLANA_DRIVER,
        DeliveryRequest.SERVICE_AROLANA_DISPATCH: DeliveryProvider.PROVIDER_AROLANA_DRIVER,
        DeliveryRequest.SERVICE_UBER_DIRECT: DeliveryProvider.PROVIDER_UBER_DIRECT,
        DeliveryRequest.SERVICE_PICKUP_VENDOR: DeliveryProvider.PROVIDER_VENDOR_PICKUP,
    }
    provider_type = provider_type_map.get(service_level)
    if provider_type:
        return DeliveryProvider.objects.filter(provider_type=provider_type, is_active=True).first()
    return DeliveryProvider.objects.filter(is_active=True).order_by('name').first()


def calculate_delivery_quote(service_level='standard', provider=None, address='', city='', state='', postal_code='', country='', subtotal=None):
    """Return a conservative delivery estimate that admin can override later."""
    service_level = service_level or DeliveryRequest.SERVICE_STANDARD
    valid_service_levels = {choice[0] for choice in DeliveryRequest.SERVICE_LEVEL_CHOICES}
    if service_level not in valid_service_levels:
        service_level = DeliveryRequest.SERVICE_STANDARD

    if provider and not isinstance(provider, DeliveryProvider):
        provider = DeliveryProvider.objects.filter(id=provider, is_active=True).first()
    if not provider:
        provider = select_delivery_provider(service_level)

    if service_level == DeliveryRequest.SERVICE_PICKUP_VENDOR:
        return {
            'fee': Decimal('0.00'),
            'provider': provider,
            'service_level': service_level,
            'message': 'Pickup from vendor is free. We will notify you when the vendor confirms pickup readiness.',
        }

    default_fee_by_service = {
        DeliveryRequest.SERVICE_STANDARD: Decimal('2500.00'),
        DeliveryRequest.SERVICE_EXPRESS: Decimal('4500.00'),
        DeliveryRequest.SERVICE_AROLANA_DISPATCH: Decimal('3500.00'),
        DeliveryRequest.SERVICE_UBER_DIRECT: Decimal('6000.00'),
    }
    base_fee = _as_money(getattr(provider, 'base_fee', None)) if provider else Decimal('0.00')
    if base_fee <= 0:
        base_fee = default_fee_by_service.get(service_level, Decimal('2500.00'))

    location_text = ' '.join([address or '', city or '', state or '', postal_code or '', country or '']).lower()
    if not location_text.strip():
        location_surcharge = Decimal('0.00')
        location_note = 'Enter your delivery location for the most accurate delivery fee.'
    elif any(term in location_text for term in ['ikeja', 'lagos', 'lekki', 'ajah', 'vi ', 'victoria island']):
        location_surcharge = Decimal('0.00')
        location_note = 'Lagos metro delivery estimate.'
    elif any(term in location_text for term in ['abuja', 'port harcourt', 'ibadan', 'kano', 'enugu']):
        location_surcharge = Decimal('1500.00')
        location_note = 'Major-city delivery estimate.'
    elif 'nigeria' in location_text or not country:
        location_surcharge = Decimal('2500.00')
        location_note = 'Nationwide delivery estimate.'
    else:
        location_surcharge = Decimal('10000.00')
        location_note = 'International or special-route delivery estimate. Admin will confirm before dispatch.'

    service_surcharge = {
        DeliveryRequest.SERVICE_STANDARD: Decimal('0.00'),
        DeliveryRequest.SERVICE_EXPRESS: Decimal('2000.00'),
        DeliveryRequest.SERVICE_AROLANA_DISPATCH: Decimal('1000.00'),
        DeliveryRequest.SERVICE_UBER_DIRECT: Decimal('3000.00'),
    }.get(service_level, Decimal('0.00'))

    fee = (base_fee + service_surcharge + location_surcharge).quantize(Decimal('0.01'))
    provider_name = provider.name if provider else 'Arolana delivery partner'
    return {
        'fee': fee,
        'provider': provider,
        'service_level': service_level,
        'message': f'{provider_name}: {location_note} Final fee may be adjusted if package size or provider availability changes.',
    }


def _order_link(order):
    try:
        return reverse('orders:detail', args=[order.order_number])
    except Exception:
        return f'/orders/{order.order_number}/'


def notify_staff_delivery(title, message, link='', metadata=None, priority=3):
    try:
        from notifications.models import Notification
    except Exception:
        return

    User = get_user_model()
    staff_users = User.objects.filter(is_active=True, is_staff=True)
    for staff in staff_users:
        Notification.send(
            user=staff,
            notification_type='shipping',
            title=title,
            message=message,
            link=link,
            metadata=metadata or {},
            priority=priority,
        )


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
    provider_id = checkout_data.get('delivery_provider')
    service_level = checkout_data.get('delivery_service_level') or DeliveryRequest.SERVICE_STANDARD
    provider = select_delivery_provider(service_level, provider_id=provider_id)
    quote = calculate_delivery_quote(
        service_level=service_level,
        provider=provider,
        address=checkout_data.get('address', ''),
        city=checkout_data.get('city', ''),
        state=checkout_data.get('state', ''),
        postal_code=checkout_data.get('postal_code', ''),
        country=checkout_data.get('country', ''),
        subtotal=cart.subtotal,
    )
    delivery_fee = _as_money(checkout_data.get('delivery_fee'), default=str(quote['fee']))
    order_total = (cart.subtotal + delivery_fee).quantize(Decimal('0.01'))

    order = Order.objects.create(
        user=payment.user,
        status='processing',
        subtotal=cart.subtotal,
        shipping_cost=delivery_fee,
        tax=0,
        total=order_total,
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

    valid_service_levels = {choice[0] for choice in DeliveryRequest.SERVICE_LEVEL_CHOICES}
    if service_level not in valid_service_levels:
        service_level = DeliveryRequest.SERVICE_STANDARD

    delivery = DeliveryRequest.objects.create(
        order=order,
        provider=provider,
        service_level=service_level,
        pickup_address='Vendor pickup address to be assigned by admin',
        dropoff_address=shipping_address,
        delivery_fee=delivery_fee,
        tracking_status=DeliveryRequest.STATUS_PENDING_ASSIGNMENT,
    )

    cart.is_active = False
    cart.save(update_fields=['is_active', 'updated_at'])

    payment.order_id = order.order_number
    payment.save(update_fields=['order_id', 'updated_at'])
    notify_staff_delivery(
        title='New delivery needs assignment',
        message=f'Order {order.order_number} is paid and ready for delivery assignment.',
        link=_order_link(order),
        metadata={'order_number': order.order_number, 'tracking_code': delivery.tracking_code},
        priority=3,
    )
    return order
