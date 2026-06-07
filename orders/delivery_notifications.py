from django.urls import reverse
import json
import urllib.request

from django.conf import settings
from django.core.mail import send_mail



def _order_link(order):
    try:
        return reverse('orders:detail', args=[order.order_number])
    except Exception:
        return f'/orders/{order.order_number}/'


def _delivery_label(delivery):
    provider_name = delivery.provider.name if delivery.provider else 'Arolana delivery'
    return f'{delivery.get_service_level_display()} via {provider_name}'


def _customer_email(order):
    email = getattr(order, 'customer_email', '') or ''
    if email:
        return email

    user = getattr(order, 'user', None)
    if user and getattr(user, 'email', ''):
        return user.email

    return ''


def _customer_name(order):
    name = getattr(order, 'customer_name', '') or ''
    if name:
        return name

    user = getattr(order, 'user', None)
    if user:
        return user.get_full_name() or user.username

    return 'Customer'


def _status_display(delivery):
    try:
        return delivery.get_tracking_status_display()
    except Exception:
        return str(getattr(delivery, 'tracking_status', '') or 'Pending').replace('_', ' ').title()


def send_delivery_email(delivery, title, message):
    order = delivery.order
    customer_email = _customer_email(order)

    if not customer_email:
        return

    customer_name = _customer_name(order)
    tracking_status = _status_display(delivery)

    subject = f"Arolana update: {title} - {order.order_number}"

    body = (
        f"Hello {customer_name},\n\n"
        f"{message}\n\n"
        f"Order Number: {order.order_number}\n"
        f"Tracking Code: {delivery.tracking_code}\n"
        f"Delivery Status: {tracking_status}\n"
        f"Payment Status: {order.payment_status}\n"
        f"Total: ₦{order.total}\n\n"
        f"You can also open your Arolana mobile app and check the Orders tab for live tracking.\n\n"
        f"Thank you for shopping with Arolana."
    )

    send_mail(
        subject=subject,
        message=body,
        from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None),
        recipient_list=[customer_email],
        fail_silently=True,
    )




def send_expo_push_notification(order, title, message, extra_data=None):
    try:
        from .models import MobilePushToken
    except Exception:
        return

    customer_phone = getattr(order, 'customer_phone', '') or ''
    customer_email = getattr(order, 'customer_email', '') or getattr(order.user, 'email', '')

    tokens = MobilePushToken.objects.filter(is_active=True)

    if customer_phone:
        tokens = tokens.filter(phone_number__in=[customer_phone, ''.join(ch for ch in customer_phone if ch.isdigit())])
    elif customer_email:
        tokens = tokens.filter(email__iexact=customer_email)
    else:
        return

    expo_tokens = list(tokens.values_list('expo_push_token', flat=True).distinct())

    if not expo_tokens:
        return

    messages = []
    for token in expo_tokens:
        messages.append({
            'to': token,
            'sound': 'default',
            'title': title,
            'body': message,
            'data': extra_data or {},
        })

    request = urllib.request.Request(
        'https://exp.host/--/api/v2/push/send',
        data=json.dumps(messages).encode('utf-8'),
        headers={
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        },
        method='POST',
    )

    try:
        urllib.request.urlopen(request, timeout=10).read()
    except Exception:
        return


def notify_delivery_created(delivery):
    from notifications.models import Notification

    order = delivery.order
    Notification.send(
        user=order.user,
        notification_type='shipping',
        title='Delivery request created',
        message=(
            f'Your order {order.order_number} is ready for delivery planning. '
            f'Tracking code: {delivery.tracking_code}. Delivery fee: {delivery.delivery_fee}.'
        ),
        link=_order_link(order),
        metadata={
            'order_number': order.order_number,
            'tracking_code': delivery.tracking_code,
            'delivery_status': delivery.tracking_status,
        },
        priority=2,
    )

    created_message = (
        f'Your order {order.order_number} is ready for delivery planning. '
        f'Tracking code: {delivery.tracking_code}. Delivery fee: {delivery.delivery_fee}.'
    )

    send_delivery_email(
        delivery,
        title='Delivery request created',
        message=created_message,
    )

    send_expo_push_notification(
        order,
        title='Delivery request created',
        message=created_message,
        extra_data={
            'order_number': order.order_number,
            'tracking_code': delivery.tracking_code,
            'delivery_status': delivery.tracking_status,
        },
    )


def notify_delivery_location(delivery):
    if not delivery.latest_location:
        return

    from notifications.models import Notification

    order = delivery.order
    Notification.send(
        user=order.user,
        notification_type='shipping',
        title='Live delivery location updated',
        message=f'Order {order.order_number} latest delivery location: {delivery.latest_location}.',
        link=_order_link(order),
        metadata={
            'order_number': order.order_number,
            'tracking_code': delivery.tracking_code,
            'delivery_status': delivery.tracking_status,
            'latest_location': delivery.latest_location,
            'latitude': str(delivery.latest_latitude or ''),
            'longitude': str(delivery.latest_longitude or ''),
        },
        priority=2,
    )

    location_message = f'Order {order.order_number} latest delivery location: {delivery.latest_location}.'

    send_delivery_email(
        delivery,
        title='Live delivery location updated',
        message=location_message,
    )

    send_expo_push_notification(
        order,
        title='Live delivery location updated',
        message=location_message,
        extra_data={
            'order_number': order.order_number,
            'tracking_code': delivery.tracking_code,
            'delivery_status': delivery.tracking_status,
            'latest_location': delivery.latest_location,
        },
    )


def notify_delivery_status(delivery, previous_status=''):
    from notifications.models import Notification

    order = delivery.order
    provider_name = delivery.provider.name if delivery.provider else 'Arolana delivery partner'
    location_suffix = f' Latest location: {delivery.latest_location}.' if delivery.latest_location else ''
    driver_suffix = ''
    if delivery.driver_name or delivery.driver_phone:
        driver_suffix = f' Driver: {delivery.driver_name or "Assigned rider"} {delivery.driver_phone or ""}.'.strip()

    messages = {
        delivery.STATUS_PENDING_ASSIGNMENT: (
            'Delivery being prepared',
            f'Order {order.order_number} is being prepared for dispatch through {_delivery_label(delivery)}.',
        ),
        delivery.STATUS_ASSIGNED: (
            'Driver assigned',
            f'Order {order.order_number} has been assigned for delivery through {provider_name}.{driver_suffix}',
        ),
        delivery.STATUS_ACCEPTED: (
            'Driver accepted delivery',
            f'The delivery partner accepted order {order.order_number}.{driver_suffix}',
        ),
        delivery.STATUS_PICKED_UP: (
            'Order picked up',
            f'Order {order.order_number} has been picked up from the vendor or dispatch point.{location_suffix}',
        ),
        delivery.STATUS_IN_TRANSIT: (
            'Order on the way',
            f'Order {order.order_number} is on the way to your drop-off location.{location_suffix}',
        ),
        delivery.STATUS_DELIVERED: (
            'Order delivered',
            f'Order {order.order_number} has been delivered. Thank you for buying from Arolana.',
        ),
        delivery.STATUS_FAILED: (
            'Delivery needs attention',
            f'Order {order.order_number} delivery could not be completed. Arolana support will follow up.',
        ),
        delivery.STATUS_CANCELLED: (
            'Delivery cancelled',
            f'Order {order.order_number} delivery was cancelled. Arolana support will follow up if needed.',
        ),
    }
    title, message = messages.get(delivery.tracking_status, messages[delivery.STATUS_PENDING_ASSIGNMENT])

    Notification.send(
        user=order.user,
        notification_type='shipping',
        title=title,
        message=message,
        link=_order_link(order),
        metadata={
            'order_number': order.order_number,
            'tracking_code': delivery.tracking_code,
            'previous_status': previous_status,
            'delivery_status': delivery.tracking_status,
            'provider': provider_name,
        },
        priority=3 if delivery.tracking_status in [delivery.STATUS_PICKED_UP, delivery.STATUS_IN_TRANSIT, delivery.STATUS_DELIVERED] else 2,
    )

    send_delivery_email(
        delivery,
        title=title,
        message=message,
    )

    send_expo_push_notification(
        order,
        title=title,
        message=message,
        extra_data={
            'order_number': order.order_number,
            'tracking_code': delivery.tracking_code,
            'delivery_status': delivery.tracking_status,
            'previous_status': previous_status,
        },
    )

    if delivery.tracking_status == delivery.STATUS_DELIVERED:
        Notification.send(
            user=order.user,
            notification_type='success',
            title='Thank you from Arolana',
            message='Thank you for buying from Arolana. We hope your order serves you well.',
            link=_order_link(order),
            metadata={'order_number': order.order_number, 'tracking_code': delivery.tracking_code},
            priority=2,
        )

        vendor_names = []
        vendor_users = []
        for item in order.items.select_related('product__vendor', 'accessory').all():
            vendor = getattr(getattr(item, 'product', None), 'vendor', None)
            if vendor and vendor not in vendor_users:
                vendor_users.append(vendor)
                vendor_names.append(vendor.get_full_name() or vendor.username or vendor.email)

        if vendor_names:
            Notification.send(
                user=order.user,
                notification_type='vendor',
                title='Thank you from the vendor',
                message=f"{', '.join(vendor_names[:3])} thanks you for your purchase on Arolana.",
                link=_order_link(order),
                metadata={'order_number': order.order_number, 'vendors': vendor_names},
                priority=2,
            )

        for vendor in vendor_users:
            Notification.send(
                user=vendor,
                notification_type='vendor',
                title='Order delivered',
                message=f'Order {order.order_number} has been delivered to the customer.',
                link=_order_link(order),
                metadata={'order_number': order.order_number, 'tracking_code': delivery.tracking_code},
                priority=2,
            )


def handle_delivery_saved(delivery, created=False):
    previous_status = getattr(delivery, '_previous_tracking_status', None)
    previous_location = getattr(delivery, '_previous_latest_location', None)
    previous_latitude = getattr(delivery, '_previous_latest_latitude', None)
    previous_longitude = getattr(delivery, '_previous_latest_longitude', None)

    if created:
        notify_delivery_created(delivery)
        return

    if previous_status and previous_status != delivery.tracking_status:
        notify_delivery_status(delivery, previous_status=previous_status)
        return

    location_changed = (
        previous_location != delivery.latest_location
        or previous_latitude != delivery.latest_latitude
        or previous_longitude != delivery.latest_longitude
    )
    if location_changed and delivery.tracking_status in [
        delivery.STATUS_ACCEPTED,
        delivery.STATUS_PICKED_UP,
        delivery.STATUS_IN_TRANSIT,
    ]:
        notify_delivery_location(delivery)
