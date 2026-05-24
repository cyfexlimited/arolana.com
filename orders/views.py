from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render

from .models import DeliveryRequest, Order
from .services import calculate_delivery_quote, select_delivery_provider


@login_required
def orders_home(request):
    orders = list(
        Order.objects
        .filter(user=request.user)
        .prefetch_related('delivery_requests', 'items__product')
        .order_by('-created_at')
    )
    for order in orders:
        deliveries = list(order.delivery_requests.all())
        order.latest_delivery = deliveries[0] if deliveries else None
    return render(request, 'orders/list.html', {'orders': orders})


@login_required
def order_detail(request, order_number):
    queryset = (
        Order.objects
        .prefetch_related('items__product', 'delivery_requests__provider')
    )
    if not request.user.is_staff:
        queryset = queryset.filter(user=request.user)

    order = get_object_or_404(queryset, order_number=order_number)
    delivery = order.delivery_requests.order_by('-created_at').first()
    delivery_steps = DeliveryRequest.TRACKING_STATUS_CHOICES
    return render(request, 'orders/detail.html', {
        'order': order,
        'delivery': delivery,
        'delivery_steps': delivery_steps,
    })


def track_order(request):
    query = (request.GET.get('tracking_code') or request.GET.get('order_number') or request.GET.get('q') or '').strip()
    email = (request.GET.get('email') or '').strip().lower()
    order = None
    delivery = None
    error = ''

    if query:
        delivery = (
            DeliveryRequest.objects
            .select_related('order__user', 'provider')
            .prefetch_related('order__items__product')
            .filter(Q(tracking_code__iexact=query) | Q(order__order_number__iexact=query))
            .order_by('-created_at')
            .first()
        )
        order = delivery.order if delivery else (
            Order.objects
            .select_related('user')
            .prefetch_related('items__product', 'delivery_requests__provider')
            .filter(order_number__iexact=query)
            .first()
        )
        if order and not delivery:
            delivery = order.delivery_requests.order_by('-created_at').first()

        if not order:
            error = 'We could not find that order or tracking code.'
        else:
            can_view = request.user.is_authenticated and (request.user.is_staff or order.user_id == request.user.id)
            email_matches = email and order.user.email.lower() == email
            if not can_view and not email_matches:
                order = None
                delivery = None
                error = 'Enter the email address used for this order to view tracking.'

    return render(request, 'support/track_order.html', {
        'query': query,
        'email': email,
        'order': order,
        'delivery': delivery,
        'delivery_steps': DeliveryRequest.TRACKING_STATUS_CHOICES,
        'error': error,
    })


def delivery_quote(request):
    service_level = request.GET.get('delivery_service_level') or DeliveryRequest.SERVICE_STANDARD
    provider_id = request.GET.get('delivery_provider') or None
    provider = select_delivery_provider(service_level, provider_id=provider_id)
    quote = calculate_delivery_quote(
        service_level=service_level,
        provider=provider,
        address=request.GET.get('address', ''),
        city=request.GET.get('city', ''),
        state=request.GET.get('state', ''),
        postal_code=request.GET.get('postal_code', ''),
        country=request.GET.get('country', ''),
        subtotal=request.GET.get('subtotal', '0'),
    )
    live_quote = None
    try:
        from deliveries.services import calculate_live_delivery_quote
        live_quote = calculate_live_delivery_quote(
            pickup_latitude=request.GET.get('pickup_latitude'),
            pickup_longitude=request.GET.get('pickup_longitude'),
            dropoff_latitude=request.GET.get('dropoff_latitude'),
            dropoff_longitude=request.GET.get('dropoff_longitude'),
            service_level=service_level,
            fallback_fee=quote['fee'],
            package_weight_kg=request.GET.get('package_weight_kg', '0'),
        )
    except Exception:
        live_quote = None

    if live_quote:
        quote['fee'] = live_quote['fee']
        quote['message'] = live_quote['message']

    provider = quote.get('provider')
    return JsonResponse({
        'success': True,
        'fee': str(quote['fee']),
        'fee_float': float(quote['fee']),
        'provider_id': provider.id if provider else '',
        'provider_name': provider.name if provider else 'Arolana delivery partner',
        'service_level': quote['service_level'],
        'message': quote['message'],
        'distance_km': str(live_quote['distance_km']) if live_quote else '',
        'estimated_duration_minutes': live_quote['estimated_duration_minutes'] if live_quote else '',
        'package_weight_kg': str(live_quote['package_weight_kg']) if live_quote else '',
        'base_fare': str(live_quote['base_fare']) if live_quote else '',
        'distance_fee': str(live_quote['distance_fee']) if live_quote else '',
        'time_fee': str(live_quote['time_fee']) if live_quote else '',
        'weight_fee': str(live_quote['weight_fee']) if live_quote else '',
        'service_fee': str(live_quote['service_fee']) if live_quote else '',
        'express_fee': str(live_quote['express_fee']) if live_quote else '',
        'surge_multiplier': str(live_quote['surge_multiplier']) if live_quote else '',
        'pricing_subtotal': str(live_quote['pricing_subtotal']) if live_quote else '',
        'is_distance_based': live_quote['is_distance_based'] if live_quote else False,
    })
