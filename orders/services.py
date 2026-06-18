from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.db import transaction
from django.urls import reverse

from .models import Cart, DeliveryProvider, DeliveryRequest, Order, OrderItem


NEGOTIATED_DELIVERY_PROVIDER_TYPES = {
    DeliveryProvider.PROVIDER_DHL,
    DeliveryProvider.PROVIDER_GIG_LOGISTICS,
}

CUSTOMER_CHECKOUT_SERVICE_LEVELS = {
    DeliveryRequest.SERVICE_STANDARD,
    DeliveryRequest.SERVICE_EXPRESS,
}


def normalize_checkout_service_level(service_level):
    if service_level in CUSTOMER_CHECKOUT_SERVICE_LEVELS:
        return service_level
    return DeliveryRequest.SERVICE_STANDARD


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


def requires_delivery_admin_quote(provider):
    return bool(provider and provider.provider_type in NEGOTIATED_DELIVERY_PROVIDER_TYPES)


def select_delivery_provider(service_level, provider_id=None):
    service_level = normalize_checkout_service_level(service_level)
    provider_type_map = {
        DeliveryRequest.SERVICE_STANDARD: DeliveryProvider.PROVIDER_MANUAL_DISPATCH,
        DeliveryRequest.SERVICE_EXPRESS: DeliveryProvider.PROVIDER_AROLANA_DRIVER,
    }
    provider_type = provider_type_map.get(service_level)

    if provider_id and provider_type:
        provider = DeliveryProvider.objects.filter(id=provider_id, provider_type=provider_type, is_active=True).first()
        if provider:
            return provider

    if provider_type:
        return DeliveryProvider.objects.filter(provider_type=provider_type, is_active=True).first()
    return DeliveryProvider.objects.filter(is_active=True).order_by('name').first()


def calculate_delivery_quote(service_level='standard', provider=None, address='', city='', state='', postal_code='', country='', subtotal=None):
    """Return a conservative delivery estimate that admin can override later."""
    service_level = normalize_checkout_service_level(service_level or DeliveryRequest.SERVICE_STANDARD)

    if provider and not isinstance(provider, DeliveryProvider):
        selected_provider = DeliveryProvider.objects.filter(id=provider, is_active=True).first()
        provider = selected_provider if selected_provider and selected_provider == select_delivery_provider(service_level, provider_id=provider) else None
    if not provider:
        provider = select_delivery_provider(service_level)

    if requires_delivery_admin_quote(provider):
        provider_name = provider.name if provider else 'Selected carrier'
        return {
            'fee': Decimal('0.00'),
            'provider': provider,
            'service_level': service_level,
            'requires_admin_quote': True,
            'message': (
                f'{provider_name} requires an Arolana admin quote. Submit the delivery details and '
                'our team will negotiate the best carrier rate for bulky, interstate, import, or export delivery.'
            ),
        }

    default_fee_by_service = {
        DeliveryRequest.SERVICE_STANDARD: Decimal('2500.00'),
        DeliveryRequest.SERVICE_EXPRESS: Decimal('4500.00'),
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
    }.get(service_level, Decimal('0.00'))

    fee = (base_fee + service_surcharge + location_surcharge).quantize(Decimal('0.01'))
    provider_name = provider.name if provider else 'Arolana delivery partner'
    return {
        'fee': fee,
        'provider': provider,
        'service_level': service_level,
        'requires_admin_quote': False,
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


def _site_url():
    return str(getattr(settings, 'SITE_URL', 'https://arolana.com') or 'https://arolana.com').rstrip('/')


def _absolute_site_link(path):
    if not path:
        return _site_url()
    if str(path).startswith(('http://', 'https://')):
        return str(path)
    return f"{_site_url()}{path}"


def send_paid_order_emails(order, delivery):
    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', None)
    customer_email = getattr(order.user, 'email', '')
    order_url = _absolute_site_link(_order_link(order))
    tracking_url = _absolute_site_link('/orders/track/')
    delivery_label = delivery.get_service_level_display() if delivery else 'Delivery'
    tracking_code = delivery.tracking_code if delivery else ''
    delivery_fee = delivery.delivery_fee if delivery else order.shipping_cost
    delivery_fee_label = 'Pending Arolana admin quote' if requires_delivery_admin_quote(getattr(delivery, 'provider', None)) else delivery_fee

    customer_subject = f'Arolana order confirmed - {order.order_number}'
    customer_message = (
        f'Thank you for buying from Arolana.\n\n'
        f'Your payment was successful and your order is now being prepared.\n\n'
        f'Order number: {order.order_number}\n'
        f'Order total: {order.total}\n'
        f'Delivery method: {delivery_label}\n'
        f'Delivery fee: {delivery_fee_label}\n'
        f'Tracking code: {tracking_code or "Pending"}\n\n'
        f'View your order: {order_url}\n'
        f'Track delivery: {tracking_url}\n\n'
        f'You will receive updates when delivery is assigned, picked up, in transit, and delivered.'
    )

    if customer_email:
        send_mail(
            customer_subject,
            customer_message,
            from_email,
            [customer_email],
            fail_silently=True,
        )

    recipients = [
        email for email in [
            getattr(settings, 'PAYMENT_ADMIN_EMAIL', ''),
            getattr(settings, 'DEFAULT_FROM_EMAIL', ''),
        ]
        if email
    ]
    if recipients:
        admin_subject = f'Paid Arolana order ready for delivery - {order.order_number}'
        admin_message = (
            f'Order {order.order_number} has been paid and needs delivery handling.\n\n'
            f'Customer: {getattr(order.user, "email", "")}\n'
            f'Total: {order.total}\n'
            f'Delivery method: {delivery_label}\n'
            f'Delivery fee: {delivery_fee_label}\n'
            f'Tracking code: {tracking_code or "Pending"}\n'
            f'Drop-off address:\n{order.shipping_address}\n\n'
            f'Admin/order link: {order_url}'
        )
        send_mail(
            admin_subject,
            admin_message,
            from_email,
            recipients,
            fail_silently=True,
        )


def start_order_robot(order, payment=None):
    try:
        from order_robot.services import process_paid_order

        return process_paid_order(order, payment=payment)
    except Exception as error:
        notify_staff_delivery(
            title='Order Robot could not start',
            message=f'Order {order.order_number} was paid, but the robot could not start automatically: {error}',
            link=_order_link(order),
            metadata={'order_number': order.order_number, 'error': str(error)},
            priority=4,
        )
        return None


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
    if not existing_order and str(payment.order_id).isdigit():
        existing_query = Order.objects.filter(id=int(payment.order_id))
        if payment.user_id:
            existing_query = existing_query.filter(user=payment.user)
        existing_order = existing_query.first()
    if existing_order:
        existing_order.payment_status = 'paid'
        existing_order.payment_method = payment.gateway
        if existing_order.status == 'pending':
            existing_order.status = 'processing'
        existing_order.save(update_fields=['payment_status', 'payment_method', 'status', 'updated_at'])
        start_order_robot(existing_order, payment=payment)
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
    service_level = normalize_checkout_service_level(checkout_data.get('delivery_service_level') or DeliveryRequest.SERVICE_STANDARD)
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
    is_admin_quote_delivery = requires_delivery_admin_quote(provider) or quote.get('requires_admin_quote')
    delivery_fee = Decimal('0.00') if is_admin_quote_delivery else _as_money(checkout_data.get('delivery_fee'), default=str(quote['fee']))
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

    try:
        from vendors.models import VendorLead
        for item in cart.items.select_related('product', 'product__vendor', 'product__vendor__vendor_profile'):
            product = item.product
            vendor_profile = getattr(getattr(product, 'vendor', None), 'vendor_profile', None)
            if not vendor_profile:
                continue
            VendorLead.objects.create(
                vendor=vendor_profile,
                product=product,
                customer_user=payment.user,
                action_type='order_created',
                customer_name=payment.user.get_full_name() or payment.user.username,
                customer_email=payment.user.email or '',
                source='checkout',
                country=(checkout_data.get('country') or '')[:8],
                currency=(getattr(payment, 'currency', '') or checkout_data.get('currency') or '')[:10],
                metadata={'order_number': order.order_number, 'cart_id': cart.id, 'payment_id': payment.id},
                extra_data={'quantity': item.quantity, 'subtotal': str(item.subtotal)},
            )
    except Exception:
        pass

    quote_details = (checkout_data.get('delivery_quote_details') or '').strip()
    quote_route_type = (checkout_data.get('delivery_route_type') or '').strip()
    admin_notes = ''
    if is_admin_quote_delivery:
        provider_name = provider.name if provider else 'Selected carrier'
        admin_notes = (
            f'Admin delivery quote required for {provider_name}.\n'
            f'Route type: {quote_route_type or "Not specified"}\n'
            f'Customer/provider details: {quote_details or "No extra details supplied."}\n'
            f'Package weight: {checkout_data.get("package_weight_kg", "0.00")} kg\n'
            f'Pickup contact: {checkout_data.get("pickup_name", "")} {checkout_data.get("pickup_phone", "")}\n'
            f'Customer phone: {checkout_data.get("phone", "")}'
        )

    delivery = DeliveryRequest.objects.create(
        order=order,
        provider=provider,
        service_level=service_level,
        pickup_address=checkout_data.get('pickup_address') or 'Vendor pickup address to be assigned by admin',
        dropoff_address=shipping_address,
        delivery_fee=delivery_fee,
        tracking_status=DeliveryRequest.STATUS_PENDING_ASSIGNMENT,
        admin_notes=admin_notes,
    )
    try:
        from deliveries.services import create_live_delivery_for_order
        create_live_delivery_for_order(
            order,
            legacy_delivery=delivery,
            checkout_data=checkout_data,
            service_level=service_level,
            defer_assignment=True,
        )
    except Exception:
        pass

    cart.is_active = False
    cart.save(update_fields=['is_active', 'updated_at'])

    payment.order_id = order.order_number
    payment.save(update_fields=['order_id', 'updated_at'])
    notify_staff_delivery(
        title='Delivery quote needed' if is_admin_quote_delivery else 'New delivery needs assignment',
        message=(
            f'Order {order.order_number} is paid and needs an admin-negotiated carrier quote.'
            if is_admin_quote_delivery else
            f'Order {order.order_number} is paid and ready for delivery assignment.'
        ),
        link=_order_link(order),
        metadata={
            'order_number': order.order_number,
            'tracking_code': delivery.tracking_code,
            'provider_type': provider.provider_type if provider else '',
            'requires_admin_quote': is_admin_quote_delivery,
        },
        priority=4 if is_admin_quote_delivery else 3,
    )
    send_paid_order_emails(order, delivery)
    start_order_robot(order, payment=payment)
    return order
