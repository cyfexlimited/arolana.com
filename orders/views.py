import json
import logging
from io import BytesIO
import re
from decimal import Decimal, InvalidOperation
from django.http import JsonResponse, HttpResponse
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from .models import DeliveryProvider, DeliveryQuoteRequest, DeliveryRequest, Order, OrderItem, MobilePushToken
from .services import calculate_delivery_quote, notify_staff_delivery, requires_delivery_admin_quote, select_delivery_provider
from products.models import Accessory, Product
from ads.contracts import InvalidAdsDelivery, campaign_asset_matches_product, verified_ads_delivery
from core.media_optimization import get_optimized_image_url

try:
    from mobile_customers.models import MobileCustomer
except ImportError:
    MobileCustomer = None

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
        .prefetch_related('items__product__vendor', 'items__variant__product__vendor', 'delivery_requests__provider', 'live_delivery_requests__rider__user')
    )
    is_staff = request.user.is_staff
    if not is_staff:
        queryset = queryset.filter(user=request.user)
        involved_order = (
            Order.objects
            .filter(order_number=order_number)
            .filter(
                Q(items__product__vendor=request.user)
                | Q(items__variant__product__vendor=request.user)
                | Q(delivery_requests__driver_user=request.user)
                | Q(live_delivery_requests__rider__user=request.user)
            )
            .distinct()
            .exists()
        )
        if involved_order:
            queryset = (
                Order.objects
                .prefetch_related('items__product__vendor', 'items__variant__product__vendor', 'delivery_requests__provider', 'live_delivery_requests__rider__user')
                .filter(order_number=order_number)
                .filter(
                    Q(user=request.user)
                    | Q(items__product__vendor=request.user)
                    | Q(items__variant__product__vendor=request.user)
                    | Q(delivery_requests__driver_user=request.user)
                    | Q(live_delivery_requests__rider__user=request.user)
                )
                .distinct()
            )

    order = get_object_or_404(queryset, order_number=order_number)
    delivery = order.delivery_requests.order_by('-created_at').first()
    delivery_steps = DeliveryRequest.TRACKING_STATUS_CHOICES
    is_customer = order.user_id == request.user.id
    is_vendor = order.items.filter(Q(product__vendor=request.user) | Q(variant__product__vendor=request.user)).exists()
    is_rider = (
        order.delivery_requests.filter(driver_user=request.user).exists()
        or order.live_delivery_requests.filter(rider__user=request.user).exists()
    )
    visible_items = order.items.all()
    if is_vendor and not (is_staff or is_customer or is_rider):
        visible_items = visible_items.filter(Q(product__vendor=request.user) | Q(variant__product__vendor=request.user))

    if is_vendor and not is_customer and not is_staff:
        back_url = reverse('dashboard:vendor_order_robot_tasks')
        back_label = 'Back to Order Robot'
    else:
        back_url = reverse('orders:list')
        back_label = 'Back to orders'

    return render(request, 'orders/detail.html', {
        'order': order,
        'delivery': delivery,
        'delivery_steps': delivery_steps,
        'visible_items': visible_items,
        'back_url': back_url,
        'back_label': back_label,
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
    if not quote.get('requires_admin_quote'):
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
        'requires_admin_quote': bool(quote.get('requires_admin_quote')),
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


def _json_body(request):
    try:
        return json.loads(request.body.decode('utf-8') or '{}')
    except Exception:
        return {}


def _joined_address(data):
    parts = [
        data.get('address', ''),
        data.get('city', ''),
        data.get('state', ''),
        data.get('postal_code', ''),
        data.get('country', ''),
    ]
    return ', '.join(str(part).strip() for part in parts if str(part).strip())



def _optional_positive_int(value):
    """Return a positive integer or None for empty/invalid analytics metadata."""
    if value in (None, ""):
        return None

    try:
        cleaned = int(value)
    except (TypeError, ValueError):
        return None

    return cleaned if cleaned >= 0 else None


def _optional_recommendation_score(value):
    """Normalize an optional recommendation score for OrderItem.DecimalField."""
    if value in (None, ""):
        return None

    try:
        score = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None

    # OrderItem.recommendation_score uses decimal_places=4.
    try:
        return score.quantize(Decimal("0.0001"))
    except InvalidOperation:
        return None


def _recommendation_metadata_from_item(item):
    """
    Accept recommendation attribution from either flat item fields or a nested
    ``recommendation`` object.

    Supported flat keys:
      recommendation_section
      recommendation_position
      recommendation_source_product_id / source_product_id
      recommendation_algorithm
      recommendation_score

    Supported nested keys:
      section, position, source_product_id, algorithm, score
    """
    item = item or {}
    recommendation = item.get("recommendation") or {}

    if not isinstance(recommendation, dict):
        recommendation = {}

    section = str(
        item.get("recommendation_section")
        or recommendation.get("section")
        or ""
    ).strip()[:100]

    algorithm = str(
        item.get("recommendation_algorithm")
        or recommendation.get("algorithm")
        or ""
    ).strip()[:100]

    position = _optional_positive_int(
        item.get("recommendation_position")
        if item.get("recommendation_position") not in (None, "")
        else recommendation.get("position")
    )

    source_product_id = _optional_positive_int(
        item.get("recommendation_source_product_id")
        or item.get("source_product_id")
        or recommendation.get("source_product_id")
    )

    score = _optional_recommendation_score(
        item.get("recommendation_score")
        if item.get("recommendation_score") not in (None, "")
        else recommendation.get("score")
    )

    # Do not preserve orphaned numeric metadata when no recommendation context
    # was supplied. This keeps direct purchases analytically clean.
    if not section and not algorithm and source_product_id is None:
        position = None
        score = None

    return {
        "recommendation_section": section,
        "recommendation_position": position,
        "recommendation_source_product_id": source_product_id,
        "recommendation_algorithm": algorithm,
        "recommendation_score": score,
    }


def _verified_ads_delivery_id(delivery_id, delivery_token, product):
    try:
        verified_id, asset = verified_ads_delivery(delivery_token, delivery_id)
        return verified_id if campaign_asset_matches_product(asset, product) else None
    except InvalidAdsDelivery:
        return None


@require_POST
def delivery_quote_request(request):
    data = _json_body(request)
    provider_id = data.get('delivery_provider') or data.get('provider_id')
    provider = DeliveryProvider.objects.filter(id=provider_id, is_active=True).first()
    if not provider or not requires_delivery_admin_quote(provider):
        return JsonResponse({
            'success': False,
            'error': 'Choose DHL or GIG Logistics to request an admin-negotiated delivery quote.',
        }, status=400)

    if not request.session.session_key:
        request.session.create()

    user = request.user if request.user.is_authenticated else None
    customer_name = (data.get('name') or data.get('customer_name') or '').strip()
    customer_email = (data.get('email') or '').strip().lower()
    customer_phone = (data.get('phone') or '').strip()
    if user:
        customer_name = customer_name or user.get_full_name() or user.username
        customer_email = customer_email or user.email

    if not customer_email:
        return JsonResponse({
            'success': False,
            'error': 'Enter your email so Arolana admin can send the delivery quote.',
        }, status=400)

    route_type = data.get('delivery_route_type') or DeliveryQuoteRequest.ROUTE_DOMESTIC
    valid_route_types = {choice[0] for choice in DeliveryQuoteRequest.ROUTE_TYPE_CHOICES}
    if route_type not in valid_route_types:
        route_type = DeliveryQuoteRequest.ROUTE_DOMESTIC

    service_level = data.get('delivery_service_level') or DeliveryRequest.SERVICE_STANDARD
    valid_service_levels = {choice[0] for choice in DeliveryRequest.SERVICE_LEVEL_CHOICES}
    if service_level not in valid_service_levels:
        service_level = DeliveryRequest.SERVICE_STANDARD

    quote_request = DeliveryQuoteRequest.objects.create(
        user=user,
        provider=provider,
        session_key=request.session.session_key or '',
        service_level=service_level,
        route_type=route_type,
        customer_name=customer_name[:160],
        customer_email=customer_email,
        customer_phone=customer_phone[:50],
        pickup_address=(data.get('pickup_address') or '').strip(),
        dropoff_address=_joined_address(data),
        package_weight_kg=data.get('package_weight_kg') or '0.00',
        package_details=(data.get('delivery_quote_details') or data.get('package_details') or '').strip(),
    )

    admin_link = f'/admin/orders/deliveryquoterequest/{quote_request.id}/change/'
    notify_staff_delivery(
        title=f'{provider.name} delivery quote request',
        message=(
            f'{customer_name or customer_email} requested a {provider.name} quote. '
            f'Route: {quote_request.get_route_type_display()}. Drop-off: {quote_request.dropoff_address or "Not supplied"}.'
        ),
        link=admin_link,
        metadata={
            'quote_request_id': quote_request.id,
            'provider_type': provider.provider_type,
            'customer_email': customer_email,
        },
        priority=4,
    )

    return JsonResponse({
        'success': True,
        'quote_request_id': quote_request.id,
        'message': (
            f'Your {provider.name} quote request has been sent to Arolana admin. '
            'We will confirm the carrier cost, route, and timing with you before dispatch.'
        ),
    })

@csrf_exempt
@require_POST
def mobile_create_order_api(request):
    """
    Mobile checkout endpoint.

    Creates:
    - a guest/mobile customer user if the request is not authenticated
    - a real Order
    - real OrderItem rows
    - a DeliveryRequest for tracking
    """
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        return JsonResponse(
            {"success": False, "message": "Invalid JSON payload."},
            status=400,
        )

    customer = payload.get("customer") or {}
    mobile_customer_payload = payload.get("mobile_customer") or {}
    items = payload.get("items") or []
    payment_method = str(payload.get("payment_method") or "paystack").strip().lower()

    full_name = str(customer.get("full_name") or "").strip()
    phone_number = str(customer.get("phone_number") or "").strip()
    email = str(customer.get("email") or "").strip().lower()
    delivery_address = str(customer.get("delivery_address") or "").strip()
    city_state = str(customer.get("city_state") or "").strip()

    if not full_name or not phone_number or not delivery_address or not city_state:
        return JsonResponse(
            {
                "success": False,
                "message": "Please complete your delivery information.",
            },
            status=400,
        )

    if not items:
        return JsonResponse(
            {"success": False, "message": "Cart is empty."},
            status=400,
        )

    mobile_customer = None

    if not request.user.is_authenticated:
        from mobile_customers.token_auth import (
            authenticate_mobile_customer_token,
            extract_bearer_token,
        )

        raw_token = str(
            extract_bearer_token(request)
            or mobile_customer_payload.get("api_token")
            or mobile_customer_payload.get("apiToken")
            or payload.get("api_token")
            or payload.get("apiToken")
            or ""
        ).strip()

        auth_phone = str(
            mobile_customer_payload.get("phone_number")
            or mobile_customer_payload.get("phoneNumber")
            or payload.get("phone_number")
            or payload.get("phoneNumber")
            or phone_number
            or ""
        ).strip()

        if raw_token:
            try:
                authentication = authenticate_mobile_customer_token(
                    raw_token,
                    request=request,
                    allow_legacy=True,
                )
                mobile_customer = authentication.customer
            except PermissionError:
                mobile_customer = None

        if mobile_customer and auth_phone:
            normalize = lambda value: "".join(
                ch
                for ch in str(value or "")
                if ch.isdigit()
            )

            if normalize(mobile_customer.phone_number) != normalize(auth_phone):
                mobile_customer = None

        if not mobile_customer:
            return JsonResponse(
                {
                    "success": False,
                    "message": "Please sign in to continue checkout.",
                    "login_required": True,
                },
                status=401,
            )

    clean_items = []
    subtotal = Decimal("0.00")

    for item in items:
        product_id = item.get("product_id")
        accessory_id = item.get("accessory_id")

        try:
            quantity = int(item.get("quantity") or 1)
        except (TypeError, ValueError):
            quantity = 1

        if quantity < 1:
            quantity = 1

        product = (
            Product.objects.filter(id=product_id, is_active=True).first()
            if product_id
            else None
        )
        accessory = (
            Accessory.objects.filter(id=accessory_id, is_active=True).first()
            if accessory_id
            else None
        )

        if not product and not accessory:
            continue

        try:
            purchasable = product or accessory
            price = Decimal(str(getattr(purchasable, "price", "0") or "0")).quantize(Decimal("0.01"))
        except (InvalidOperation, TypeError, ValueError):
            price = Decimal("0.00")

        line_total = (price * quantity).quantize(Decimal("0.01"))
        subtotal += line_total

        recommendation_metadata = _recommendation_metadata_from_item(item)

        clean_items.append(
            {
                "product": product,
                "accessory": accessory,
                "product_id": product.id if product else None,
                "accessory_id": accessory.id if accessory else None,
                "name": getattr(purchasable, "name", ""),
                "slug": getattr(purchasable, "slug", ""),
                "price": price,
                "quantity": quantity,
                "line_total": line_total,
                "ads_delivery_id": _verified_ads_delivery_id(
                    item.get("ads_delivery_id"),
                    item.get("ads_delivery_token"),
                    product,
                ),
                **recommendation_metadata,
            }
        )

    if not clean_items:
        return JsonResponse(
            {"success": False, "message": "No valid products found."},
            status=400,
        )

    shipping_cost = Decimal("0.00")
    tax = Decimal("0.00")
    total = (subtotal + shipping_cost + tax).quantize(Decimal("0.01"))

    shipping_address = (
        f"Customer: {full_name}\\n"
        f"Phone: {phone_number}\\n"
        f"Email: {email or 'Not provided'}\\n"
        f"Address: {delivery_address}\\n"
        f"City/State: {city_state}"
    )

    try:
        with transaction.atomic():
            if getattr(request, "user", None) and request.user.is_authenticated:
                user = request.user
            elif mobile_customer and mobile_customer.user_id:
                user = mobile_customer.user
            else:
                User = get_user_model()
                clean_phone = "".join(ch for ch in phone_number if ch.isdigit())
                username = f"mobile_{clean_phone}" if clean_phone else "mobile_customer"

                user = User.objects.filter(username=username).first()

                # Email can be unique in your User model.
                # Do not force the mobile phone user to take an email that already
                # belongs to another account, otherwise checkout fails with:
                # UNIQUE constraint failed: users.email
                email_owner = None
                if email and hasattr(User, "email"):
                    email_owner = User.objects.filter(email__iexact=email).first()

                safe_user_email = email
                if email_owner and (not user or email_owner.pk != user.pk):
                    safe_user_email = ""

                if not user:
                    name_parts = full_name.split(" ", 1)
                    first_name = name_parts[0] if name_parts else ""
                    last_name = name_parts[1] if len(name_parts) > 1 else ""

                    user = User(
                        username=username,
                        first_name=first_name[:150],
                        last_name=last_name[:150],
                    )

                    if hasattr(user, "email"):
                        user.email = safe_user_email or f"{username}@mobile.arolana.local"

                    if hasattr(user, "phone_number"):
                        user.phone_number = phone_number

                    if hasattr(user, "phone"):
                        user.phone = phone_number

                    user.set_unusable_password()
                    user.save()
                else:
                    update_fields = []

                    if full_name:
                        name_parts = full_name.split(" ", 1)
                        first_name = name_parts[0] if name_parts else ""
                        last_name = name_parts[1] if len(name_parts) > 1 else ""

                        if hasattr(user, "first_name") and user.first_name != first_name[:150]:
                            user.first_name = first_name[:150]
                            update_fields.append("first_name")

                        if hasattr(user, "last_name") and user.last_name != last_name[:150]:
                            user.last_name = last_name[:150]
                            update_fields.append("last_name")

                    if (
                        safe_user_email
                        and hasattr(user, "email")
                        and user.email != safe_user_email
                    ):
                        user.email = safe_user_email
                        update_fields.append("email")

                    if hasattr(user, "phone_number") and getattr(user, "phone_number", "") != phone_number:
                        user.phone_number = phone_number
                        update_fields.append("phone_number")

                    if hasattr(user, "phone") and getattr(user, "phone", "") != phone_number:
                        user.phone = phone_number
                        update_fields.append("phone")

                    if update_fields:
                        user.save(update_fields=update_fields)

            order_data = {
                "user": user,
                "status": "pending",
                "subtotal": subtotal.quantize(Decimal("0.01")),
                "shipping_cost": shipping_cost,
                "tax": tax,
                "total": total,
                "shipping_address": shipping_address,
                "billing_address": shipping_address,
                "payment_method": payment_method,
                "payment_status": "pending",
            }

            order_field_names = {field.name for field in Order._meta.fields}

            if "customer_name" in order_field_names:
                order_data["customer_name"] = full_name[:160]

            if "customer_email" in order_field_names:
                order_data["customer_email"] = email

            if "customer_phone" in order_field_names:
                order_data["customer_phone"] = phone_number[:50]

            order = Order.objects.create(**order_data)

            order_items_response = []

            for item in clean_items:
                order_item = OrderItem.objects.create(
                    order=order,
                    product=item["product"],
                    accessory=item["accessory"],
                    quantity=item["quantity"],
                    price=item["price"],
                    subtotal=item["line_total"],

                    recommendation_section=item.get(
                        "recommendation_section",
                        "",
                    ),
                    recommendation_position=item.get(
                        "recommendation_position",
                    ),
                    recommendation_source_product_id=item.get(
                        "recommendation_source_product_id",
                    ),
                    recommendation_algorithm=item.get(
                        "recommendation_algorithm",
                        "",
                    ),
                    recommendation_score=item.get(
                        "recommendation_score",
                    ),
                    ads_delivery_id=item.get("ads_delivery_id"),
                )

                order_items_response.append(
                    {
                        "id": order_item.id,
                        "product_id": item["product_id"],
                        "accessory_id": item["accessory_id"],
                        "name": item["name"],
                        "slug": item["slug"],
                        "price": str(item["price"]),
                        "quantity": item["quantity"],
                        "line_total": str(item["line_total"]),
                        "recommendation_section": item["recommendation_section"],
                        "recommendation_position": item["recommendation_position"],
                        "recommendation_source_product_id": item[
                            "recommendation_source_product_id"
                        ],
                        "recommendation_algorithm": item[
                            "recommendation_algorithm"
                        ],
                        "recommendation_score": (
                            str(item["recommendation_score"])
                            if item["recommendation_score"] is not None
                            else None
                        ),
                    }
                )

            delivery = DeliveryRequest.objects.create(
                order=order,
                service_level=DeliveryRequest.SERVICE_STANDARD,
                dropoff_address=shipping_address,
                delivery_fee=shipping_cost,
                tracking_status=DeliveryRequest.STATUS_PENDING_ASSIGNMENT,
                admin_notes=(
                    "Mobile checkout order.\\n"
                    f"Customer: {full_name}\\n"
                    f"Phone: {phone_number}\\n"
                    f"Email: {email or 'Not provided'}\\n"
                    f"Payment method: {payment_method}"
                ),
            )

    except Exception as error:
        return JsonResponse(
            {
                "success": False,
                "message": f"Could not create order: {str(error)}",
            },
            status=500,
        )

    return JsonResponse(
        {
            "success": True,
            "message": "Order created successfully.",
            "order": {
                "id": order.id,
                "order_number": order.order_number,
                "status": order.status,
                "payment_method": order.payment_method,
                "payment_status": order.payment_status,
                "customer_name": getattr(order, "customer_name", "") or order.user.get_full_name() or order.user.username,
                "customer_email": getattr(order, "customer_email", "") or getattr(order.user, "email", ""),
                "customer_phone": getattr(order, "customer_phone", ""),
                "tracking_code": delivery.tracking_code,
                "customer": {
                    "full_name": full_name,
                    "phone_number": phone_number,
                    "email": email,
                    "delivery_address": delivery_address,
                    "city_state": city_state,
                },
                "items": order_items_response,
                "subtotal": str(order.subtotal),
                "delivery_fee": str(order.shipping_cost),
                "tax": str(order.tax),
                "total": str(order.total),
            },
        },
        status=201,
    )

@require_GET
def mobile_orders_history_api(request):
    phone_number = str(request.GET.get("phone") or "").strip()
    clean_phone = "".join(ch for ch in phone_number if ch.isdigit())

    if not clean_phone:
        return JsonResponse(
            {
                "success": False,
                "message": "Phone number is required.",
                "orders": [],
            },
            status=400,
        )

    username = f"mobile_{clean_phone}"

    orders = (
        Order.objects
        .filter(Q(user__username=username) | Q(customer_phone=phone_number) | Q(customer_phone=clean_phone))
        .prefetch_related("items__product", "delivery_requests")
        .order_by("-created_at")[:30]
    )

    order_list = []

    for order in orders:
        delivery = order.delivery_requests.order_by("-created_at").first()

        items = []
        for item in order.items.all():
            product = item.product

            image_url = None
            if product:
                raw_image = (
                    getattr(product, "image", None)
                    or getattr(product, "main_image", None)
                    or getattr(product, "thumbnail", None)
                )

                if raw_image:
                    try:
                        image_url = request.build_absolute_uri(raw_image.url)
                    except Exception:
                        image_url = None

            items.append(
                {
                    "id": item.id,
                    "product_id": product.id if product else None,
                    "name": item.item_name,
                    "quantity": item.quantity,
                    "price": str(item.price),
                    "subtotal": str(item.subtotal),
                    "image": image_url,
                }
            )

        order_list.append(
            {
                "id": order.id,
                "order_number": order.order_number,
                "status": order.status,
                "payment_method": order.payment_method,
                "payment_status": order.payment_status,
                "subtotal": str(order.subtotal),
                "shipping_cost": str(order.shipping_cost),
                "tax": str(order.tax),
                "total": str(order.total),
                "tracking_code": delivery.tracking_code if delivery else "",
                "tracking_status": delivery.tracking_status if delivery else "",
                "created_at": order.created_at.isoformat() if order.created_at else "",
                "items": items,
            }
        )

    return JsonResponse(
        {
            "success": True,
            "orders": order_list,
        }
    )

@csrf_exempt
@require_POST
def mobile_register_push_token_api(request):
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        return JsonResponse(
            {"success": False, "message": "Invalid JSON payload."},
            status=400,
        )

    phone_number = str(payload.get("phone_number") or "").strip()
    email = str(payload.get("email") or "").strip().lower()
    expo_push_token = str(payload.get("expo_push_token") or "").strip()
    device_name = str(payload.get("device_name") or "").strip()
    platform = str(payload.get("platform") or "").strip()

    if not phone_number:
        return JsonResponse(
            {"success": False, "message": "Phone number is required."},
            status=400,
        )

    if not expo_push_token:
        return JsonResponse(
            {"success": False, "message": "Expo push token is required."},
            status=400,
        )

    token, created = MobilePushToken.objects.update_or_create(
        expo_push_token=expo_push_token,
        defaults={
            "phone_number": phone_number,
            "email": email,
            "device_name": device_name,
            "platform": platform,
            "is_active": True,
            "last_registered_at": timezone.now(),
        },
    )

    return JsonResponse(
        {
            "success": True,
            "message": "Push token registered.",
            "created": created,
            "token_id": token.id,
        }
    )



def _mobile_notification_context(phone_number, api_token="", request=None):
    clean_phone = "".join(ch for ch in str(phone_number or "") if ch.isdigit())
    username = f"mobile_{clean_phone}"

    User = get_user_model()
    user_ids = []
    linked_customer = None

    raw_token = str(api_token or "").strip()

    if request is not None:
        from mobile_customers.token_auth import extract_bearer_token
        raw_token = extract_bearer_token(request) or raw_token

    if not raw_token:
        return clean_phone, [], [], []

    try:
        from mobile_customers.token_auth import authenticate_mobile_customer_token

        authentication = authenticate_mobile_customer_token(
            raw_token,
            request=request,
            allow_legacy=True,
        )
        linked_customer = authentication.customer
    except PermissionError:
        return clean_phone, [], [], []
    except Exception:
        logger.exception("Could not resolve mobile notification account token")
        return clean_phone, [], [], []

    linked_clean_phone = "".join(
        ch
        for ch in str(linked_customer.phone_number or "")
        if ch.isdigit()
    )

    if clean_phone and linked_clean_phone != clean_phone:
        return clean_phone, [], [], []

    if linked_customer.user_id and linked_customer.user_id not in user_ids:
        user_ids.append(linked_customer.user_id)

    if linked_customer:
        linked_phone = str(linked_customer.phone_number or "")
        linked_clean_phone = "".join(ch for ch in linked_phone if ch.isdigit())
        order_filter = (
            Q(user_id=linked_customer.user_id)
            | Q(customer_phone=linked_phone)
            | Q(customer_phone=linked_clean_phone)
        )
    else:
        order_filter = (
            Q(user__username=username)
            | Q(customer_phone=phone_number)
            | Q(customer_phone=clean_phone)
        )

    matching_orders = (
        Order.objects
        .filter(order_filter)
        .select_related("user")
        .prefetch_related("delivery_requests")
        .order_by("-created_at")[:80]
    )

    order_numbers = []
    tracking_codes = []

    for order in matching_orders:
        if order.user_id and order.user_id not in user_ids:
            user_ids.append(order.user_id)

        order_numbers.append(order.order_number)

        delivery = order.delivery_requests.order_by("-created_at").first()
        if delivery:
            tracking_codes.append(delivery.tracking_code)

    return clean_phone, user_ids, order_numbers, tracking_codes


def _mobile_notification_queryset(phone_number, api_token="", request=None):
    try:
        from notifications.models import Notification
    except Exception:
        return None

    clean_phone, user_ids, order_numbers, tracking_codes = _mobile_notification_context(phone_number, api_token, request=request)

    if not clean_phone:
        return Notification.objects.none()

    notifications_query = Notification.objects.none()

    if user_ids:
        notifications_query = Notification.objects.filter(user_id__in=user_ids)

    metadata_query = Q()

    for order_number in order_numbers:
        metadata_query |= Q(metadata__order_number=order_number)

    for tracking_code in tracking_codes:
        metadata_query |= Q(metadata__tracking_code=tracking_code)

    if metadata_query:
        notifications_query = notifications_query | Notification.objects.filter(metadata_query)

    return notifications_query.distinct()

@require_GET
def mobile_notifications_api(request):
    phone_number = str(request.GET.get("phone") or "").strip()
    api_token = str(request.GET.get("api_token") or "").strip()
    clean_phone = "".join(ch for ch in phone_number if ch.isdigit())

    if not clean_phone:
        return JsonResponse(
            {
                "success": False,
                "message": "Phone number is required.",
                "notifications": [],
            },
            status=400,
        )

    try:
        from notifications.models import Notification
    except Exception:
        return JsonResponse(
            {
                "success": True,
                "notifications": [],
                "message": "Notifications app is not available.",
            }
        )

    notifications_query = _mobile_notification_queryset(
        phone_number,
        api_token,
    ).order_by("-created_at")[:50]

    notifications = []

    for notification in notifications_query:
        metadata = getattr(notification, "metadata", None) or {}

        notifications.append(
            {
                "id": notification.id,
                "notification_type": getattr(notification, "notification_type", ""),
                "title": getattr(notification, "title", ""),
                "message": getattr(notification, "message", ""),
                "link": getattr(notification, "link", ""),
                "metadata": metadata,
                "order_number": metadata.get("order_number", ""),
                "tracking_code": metadata.get("tracking_code", ""),
                "delivery_status": metadata.get("delivery_status", ""),
                "is_read": bool(getattr(notification, "is_read", False)),
                "created_at": notification.created_at.isoformat() if getattr(notification, "created_at", None) else "",
            }
        )

    return JsonResponse(
        {
            "success": True,
            "notifications": notifications,
        }
    )


@csrf_exempt
@require_POST
def mobile_notifications_mark_read_api(request):
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        return JsonResponse(
            {"success": False, "message": "Invalid JSON payload."},
            status=400,
        )

    phone_number = str(payload.get("phone") or payload.get("phone_number") or "").strip()
    api_token = str(payload.get("api_token") or "").strip()
    notification_id = payload.get("notification_id")
    mark_as_read = payload.get("is_read", True) not in (False, "false", "0", 0)
    clean_phone = "".join(ch for ch in phone_number if ch.isdigit())

    if not clean_phone:
        return JsonResponse(
            {"success": False, "message": "Phone number is required."},
            status=400,
        )

    try:
        from notifications.models import Notification
    except Exception:
        return JsonResponse(
            {
                "success": True,
                "message": "Notifications app is not available.",
                "updated": 0,
            }
        )

    notifications_query = _mobile_notification_queryset(phone_number, api_token, request=request)
    if notification_id:
        notifications_query = notifications_query.filter(id=notification_id)

    updated = 0

    # Support common field names used by notification models.
    sample = notifications_query.first()
    if sample:
        if hasattr(sample, "is_read"):
            updated = notifications_query.update(
                is_read=mark_as_read,
                read_at=timezone.now() if mark_as_read else None,
            )
        elif hasattr(sample, "read"):
            updated = notifications_query.filter(read=False).update(read=True)
        else:
            updated = 0

    return JsonResponse(
        {
            "success": True,
            "message": "Notifications marked as read.",
            "updated": updated,
        }
    )


@csrf_exempt
@require_POST
def mobile_notifications_delete_api(request):
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        return JsonResponse(
            {"success": False, "message": "Invalid JSON payload."},
            status=400,
        )

    phone_number = str(payload.get("phone") or payload.get("phone_number") or "").strip()
    api_token = str(payload.get("api_token") or "").strip()
    clean_phone = "".join(ch for ch in phone_number if ch.isdigit())
    notification_id = payload.get("notification_id")

    if not clean_phone:
        return JsonResponse(
            {"success": False, "message": "Phone number is required."},
            status=400,
        )

    if not notification_id:
        return JsonResponse(
            {"success": False, "message": "Notification ID is required."},
            status=400,
        )

    try:
        from notifications.models import Notification
    except Exception:
        return JsonResponse(
            {
                "success": True,
                "message": "Notifications app is not available.",
                "deleted": 0,
            }
        )

    notifications_query = _mobile_notification_queryset(phone_number, api_token, request=request).filter(id=notification_id)
    deleted_count, _ = notifications_query.delete()

    return JsonResponse(
        {
            "success": True,
            "message": "Notification deleted.",
            "deleted": deleted_count,
        }
    )

def _mobile_order_clean_phone(value):
    return "".join(ch for ch in str(value or "") if ch.isdigit() or ch == "+").strip()


def _mobile_order_clean_text(value):
    return str(value or "").strip()


def _mobile_order_json_body(request):
    try:
        return json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        return {}


def _mobile_order_json_error(message, status=400):
    return JsonResponse(
        {
            "success": False,
            "message": str(message),
            "error": str(message),
        },
        status=status,
    )


def _mobile_order_auth_customer(payload_or_request):
    # Authenticate through the shared hashed-token service.
    from mobile_customers.token_auth import (
        authenticate_mobile_customer_token,
        extract_bearer_token,
    )

    request = payload_or_request if hasattr(payload_or_request, "GET") else None
    payload = request.GET if request is not None else (payload_or_request or {})

    mobile_customer_payload = payload.get("mobile_customer") or {}
    customer_payload = payload.get("customer") or {}

    phone_number = _mobile_order_clean_phone(
        payload.get("phone")
        or payload.get("phone_number")
        or payload.get("phoneNumber")
        or mobile_customer_payload.get("phone_number")
        or mobile_customer_payload.get("phoneNumber")
        or customer_payload.get("phone_number")
        or customer_payload.get("phoneNumber")
    )

    raw_token = _mobile_order_clean_text(
        (extract_bearer_token(request) if request is not None else "")
        or payload.get("api_token")
        or payload.get("apiToken")
        or mobile_customer_payload.get("api_token")
        or mobile_customer_payload.get("apiToken")
        or customer_payload.get("api_token")
        or customer_payload.get("apiToken")
    )

    if not phone_number:
        raise ValueError("Phone number is required.")

    if not raw_token:
        raise PermissionError("Login token is required. Login/register again.")

    authentication = authenticate_mobile_customer_token(
        raw_token,
        request=request,
        allow_legacy=True,
    )
    customer = authentication.customer

    if _mobile_order_clean_phone(customer.phone_number) != phone_number:
        raise PermissionError("Invalid login token. Login/register again.")

    return customer

def _mobile_order_set_field(obj, field_name, value):
    if hasattr(obj, field_name) and value not in [None, ""]:
        setattr(obj, field_name, value)
        return True
    return False


def _mobile_order_decimal(value):
    try:
        return Decimal(str(value or "0").replace(",", ""))
    except Exception:
        return Decimal("0")


def _mobile_order_image_url(request, product):
    if not product:
        return ""

    for field_name in ["image", "main_image", "thumbnail", "photo", "featured_image", "product_image"]:
        image = getattr(product, field_name, None)
        if image:
            try:
                image_url = get_optimized_image_url(image, "product_card")
                return image_url if image_url.startswith(("http://", "https://")) else request.build_absolute_uri(image_url)
            except Exception:
                try:
                    return request.build_absolute_uri(image.url)
                except Exception:
                    return ""

    try:
        first_image = product.images.first()
        if first_image:
            for attr in ["image", "url", "file", "photo"]:
                image = getattr(first_image, attr, None)
                if image:
                    try:
                        image_url = get_optimized_image_url(image, "product_card")
                        return image_url if image_url.startswith(("http://", "https://")) else request.build_absolute_uri(image_url)
                    except Exception:
                        try:
                            return request.build_absolute_uri(image.url)
                        except Exception:
                            return ""
    except Exception:
        pass

    return ""


def _mobile_order_item_payload(request, item):
    product = getattr(item, "product", None)
    accessory = getattr(item, "accessory", None)
    purchasable = product or accessory

    price = (
        getattr(item, "price", None)
        or getattr(item, "unit_price", None)
        or getattr(item, "amount", None)
        or getattr(item, "price_at_order", None)
        or getattr(item, "price_at_add", None)
        or 0
    )
    quantity = getattr(item, "quantity", 1) or 1
    subtotal = getattr(item, "subtotal", None)

    try:
        subtotal_value = subtotal() if callable(subtotal) else subtotal
    except Exception:
        subtotal_value = None

    if subtotal_value in [None, ""]:
        subtotal_value = _mobile_order_decimal(price) * _mobile_order_decimal(quantity)

    return {
        "id": getattr(item, "id", None),
        "product_id": getattr(product, "id", None),
        "accessory_id": getattr(accessory, "id", None),
        "item_type": "accessory" if accessory else "product",
        "name": getattr(purchasable, "name", "") or getattr(purchasable, "title", "") or str(purchasable or "Product"),
        "quantity": quantity,
        "price": str(price or 0),
        "unit_price": str(price or 0),
        "subtotal": str(subtotal_value or 0),
        "line_total": str(subtotal_value or 0),
        "image": _mobile_order_image_url(request, purchasable),
        "recommendation_section": getattr(
            item,
            "recommendation_section",
            "",
        ),
        "recommendation_position": getattr(
            item,
            "recommendation_position",
            None,
        ),
        "recommendation_source_product_id": getattr(
            item,
            "recommendation_source_product_id",
            None,
        ),
        "recommendation_algorithm": getattr(
            item,
            "recommendation_algorithm",
            "",
        ),
        "recommendation_score": (
            str(getattr(item, "recommendation_score", ""))
            if getattr(item, "recommendation_score", None) is not None
            else None
        ),
    }


def _mobile_order_items_for_order(order):
    if hasattr(order, "items"):
        try:
            return order.items.select_related("product", "accessory").all()
        except Exception:
            pass

    try:
        return order.orderitem_set.select_related("product", "accessory").all()
    except Exception:
        return []


def _mobile_order_delivery_payload(order):
    delivery = None
    is_live_delivery = False

    for related_name in ["live_delivery_requests", "delivery_requests", "deliveryrequest_set"]:
        try:
            manager = getattr(order, related_name)
            delivery = manager.order_by("-created_at").first()
            if delivery:
                is_live_delivery = related_name == "live_delivery_requests"
                break
        except Exception:
            continue

    if not delivery:
        return {}

    raw_status = (
        getattr(delivery, "status", "")
        or getattr(delivery, "tracking_status", "")
        or getattr(delivery, "delivery_status", "")
    )
    status_map = {
        "pending_assignment": "pending",
        "pending": "pending",
        "assigned": "confirmed",
        "accepted": "ready_for_pickup",
        "arrived_pickup": "ready_for_pickup",
        "picked_up": "dispatched",
        "shipped": "dispatched",
        "in_transit": "in_transit",
        "arrived_customer": "out_for_delivery",
        "out_for_delivery": "out_for_delivery",
        "delivered": "delivered",
        "failed": "failed_delivery",
        "cancelled": "cancelled",
        "returned": "returned",
    }
    tracking_status = status_map.get(str(raw_status or "").lower(), str(raw_status or "pending").lower())

    history = []
    if is_live_delivery:
        try:
            history = [
                {
                    "status": status_map.get(item.status, item.status),
                    "raw_status": item.status,
                    "label": item.get_status_display(),
                    "note": item.note,
                    "location": item.location_label,
                    "created_at": item.created_at.isoformat() if item.created_at else "",
                }
                for item in delivery.status_history.order_by("created_at")
            ]
        except Exception:
            history = []

    rider = getattr(delivery, "rider", None)
    rider_user = getattr(rider, "user", None) if rider else None
    return {
        "tracking_code": getattr(delivery, "tracking_code", "") or getattr(order, "tracking_number", ""),
        "delivery_status": tracking_status,
        "tracking_status": tracking_status,
        "tracking_status_raw": str(raw_status or ""),
        "tracking_status_display": str(tracking_status).replace("_", " ").title(),
        "delivery_fee": str(getattr(delivery, "delivery_fee", "") or getattr(delivery, "fee", "") or getattr(order, "shipping_cost", "") or 0),
        "rider_name": str(
            getattr(rider, "full_name", "")
            or (rider_user.get_full_name() if rider_user else "")
            or getattr(delivery, "driver_name", "")
        ),
        "rider_phone": str(getattr(rider, "phone", "") or getattr(delivery, "driver_phone", "") or ""),
        "delivery_address": str(getattr(delivery, "dropoff_address", "") or getattr(order, "shipping_address", "") or ""),
        "tracking_history": history,
        "tracking_updated_at": delivery.updated_at.isoformat() if getattr(delivery, "updated_at", None) else "",
    }


def _mobile_order_payload(request, order):
    items = [_mobile_order_item_payload(request, item) for item in _mobile_order_items_for_order(order)]
    delivery_payload = _mobile_order_delivery_payload(order)

    customer = {
        "full_name": getattr(order, "customer_name", "") or getattr(getattr(order, "user", None), "get_full_name", lambda: "")(),
        "phone_number": getattr(order, "customer_phone", ""),
        "email": getattr(order, "customer_email", "") or getattr(getattr(order, "user", None), "email", ""),
    }

    payload = {
        "id": getattr(order, "id", None),
        "order_number": getattr(order, "order_number", "") or str(getattr(order, "id", "")),
        "status": getattr(order, "status", ""),
        "payment_status": getattr(order, "payment_status", ""),
        "payment_method": getattr(order, "payment_method", "") or getattr(order, "payment_type", "") or "paystack",
        "subtotal": str(getattr(order, "subtotal", "") or 0),
        "shipping_cost": str(getattr(order, "shipping_cost", "") or getattr(order, "delivery_fee", "") or 0),
        "delivery_fee": str(getattr(order, "shipping_cost", "") or getattr(order, "delivery_fee", "") or 0),
        "tax": str(getattr(order, "tax", "") or 0),
        "total": str(getattr(order, "total", "") or getattr(order, "grand_total", "") or 0),
        "tracking_code": delivery_payload.get("tracking_code") or getattr(order, "tracking_number", ""),
        "delivery_status": delivery_payload.get("delivery_status", ""),
        "tracking_status": delivery_payload.get("tracking_status", ""),
        "customer": customer,
        "items": items,
        "created_at": order.created_at.isoformat() if getattr(order, "created_at", None) else "",
        "updated_at": order.updated_at.isoformat() if getattr(order, "updated_at", None) else "",
    }

    payload.update(delivery_payload)
    return payload


def _mobile_find_order_from_response(data):
    order_data = data.get("order") or {}
    order_id = order_data.get("id") or data.get("order_id")
    order_number = order_data.get("order_number") or data.get("order_number")

    queryset = Order.objects.all()

    if order_id:
        order = queryset.filter(id=order_id).first()
        if order:
            return order

    if order_number:
        order = queryset.filter(order_number=order_number).first()
        if order:
            return order

    return None


def _mobile_attach_customer_to_order(order, customer, payload):
    if not order or not customer:
        return order

    mobile_customer_payload = payload.get("mobile_customer") or {}
    customer_payload = payload.get("customer") or {}

    full_name = (
        _mobile_order_clean_text(mobile_customer_payload.get("full_name"))
        or _mobile_order_clean_text(customer_payload.get("full_name"))
        or getattr(customer, "full_name", "")
    )
    email = (
        _mobile_order_clean_text(mobile_customer_payload.get("email"))
        or _mobile_order_clean_text(customer_payload.get("email"))
        or getattr(customer, "email", "")
        or getattr(customer.user, "email", "")
    )

    changed_fields = []

    if hasattr(order, "user") and customer.user_id and order.user_id != customer.user_id:
        order.user = customer.user
        changed_fields.append("user")

    if _mobile_order_set_field(order, "customer_name", full_name):
        changed_fields.append("customer_name")

    if _mobile_order_set_field(order, "customer_email", email):
        changed_fields.append("customer_email")

    if _mobile_order_set_field(order, "customer_phone", customer.phone_number):
        changed_fields.append("customer_phone")

    if changed_fields:
        order.save(update_fields=list(set(changed_fields)))

    return order


def _mobile_original_create_view():
    """
    Finds your existing mobile order create function without requiring us to know
    the exact name. Add your exact function name here if your project uses a different one.
    """
    current = globals().get("mobile_authenticated_order_create_api")

    for function_name in [
        "mobile_create_order_api",
        "mobile_order_create_api",
        "mobile_create_order",
        "api_mobile_create_order",
        "create_mobile_order_api",
        "api_mobile_orders_create",
    ]:
        view = globals().get(function_name)
        if view and view is not current:
            return view

    return None


@csrf_exempt
@require_POST
def mobile_authenticated_order_create_api(request):
    payload = _mobile_order_json_body(request)

    try:
        customer = _mobile_order_auth_customer(payload)
    except PermissionError as error:
        return _mobile_order_json_error(error, status=403)
    except Exception as error:
        return _mobile_order_json_error(error, status=400)

    original_view = _mobile_original_create_view()

    if not original_view:
        return _mobile_order_json_error(
            "Existing mobile order create view was not found. Add your current create function name inside _mobile_original_create_view().",
            status=500,
        )

    response = original_view(request)

    try:
        data = json.loads(response.content.decode("utf-8") or "{}")
    except Exception:
        return response

    if getattr(response, "status_code", 500) >= 400 or not data.get("success"):
        return response

    order = _mobile_find_order_from_response(data)

    if order:
        order = _mobile_attach_customer_to_order(order, customer, payload)
        data["order"] = _mobile_order_payload(request, order)

        return JsonResponse(data, status=getattr(response, "status_code", 201))

    return response


@require_GET
def mobile_authenticated_orders_history_api(request):
    try:
        customer = _mobile_order_auth_customer(request)
    except PermissionError as error:
        return _mobile_order_json_error(error, status=403)
    except Exception as error:
        return _mobile_order_json_error(error, status=400)

    queryset = Order.objects.all().order_by("-created_at")

    lookup = Q()
    if getattr(customer, "user_id", None):
        lookup |= Q(user=customer.user)

    if hasattr(Order, "customer_phone"):
        lookup |= Q(customer_phone=customer.phone_number)

    orders = queryset.filter(lookup).distinct()[:80]

    return JsonResponse(
        {
            "success": True,
            "customer": {
                "id": customer.id,
                "full_name": customer.full_name,
                "phone_number": customer.phone_number,
                "email": customer.email,
            },
            "orders": [_mobile_order_payload(request, order) for order in orders],
            "count": orders.count() if hasattr(orders, "count") else len(orders),
        }
    )


def _mobile_customer_order_queryset(customer):
    ownership = Q()
    if getattr(customer, "user_id", None):
        ownership |= Q(user=customer.user)
    if hasattr(Order, "customer_phone"):
        ownership |= Q(customer_phone=customer.phone_number)
    return (
        Order.objects.filter(ownership)
        .prefetch_related(
            "items__product",
            "delivery_requests",
            "live_delivery_requests__rider__user",
            "live_delivery_requests__status_history",
        )
        .distinct()
    )


@require_GET
def mobile_authenticated_order_detail_api(request, order_id):
    try:
        customer = _mobile_order_auth_customer(request)
    except PermissionError as error:
        return _mobile_order_json_error(error, status=403)
    except Exception as error:
        return _mobile_order_json_error(error, status=400)

    order = _mobile_customer_order_queryset(customer).filter(id=order_id).first()
    if not order:
        return _mobile_order_json_error("Order not found for this customer.", status=404)
    return JsonResponse({"success": True, "order": _mobile_order_payload(request, order)})


@require_GET
def mobile_authenticated_order_tracking_api(request, order_id):
    try:
        customer = _mobile_order_auth_customer(request)
    except PermissionError as error:
        return _mobile_order_json_error(error, status=403)
    except Exception as error:
        return _mobile_order_json_error(error, status=400)

    order = _mobile_customer_order_queryset(customer).filter(id=order_id).first()
    if not order:
        return _mobile_order_json_error("Order not found for this customer.", status=404)
    payload = _mobile_order_payload(request, order)
    if payload.get("payment_status") == "paid" and payload.get("tracking_status") in {"", "pending"}:
        payload["tracking_message"] = "Payment is confirmed. Your order is pending pickup/dispatch."
    elif payload.get("tracking_status") in {"", "pending"}:
        payload["tracking_message"] = "Your order is pending pickup/dispatch."
    else:
        payload["tracking_message"] = f"Delivery is {payload.get('tracking_status_display', 'being updated').lower()}."
    return JsonResponse({"success": True, "tracking": payload, "order": payload})


@require_GET
def mobile_authenticated_tracking_code_api(request, tracking_code):
    try:
        customer = _mobile_order_auth_customer(request)
    except PermissionError as error:
        return _mobile_order_json_error(error, status=403)
    except Exception as error:
        return _mobile_order_json_error(error, status=400)

    order = (
        _mobile_customer_order_queryset(customer)
        .filter(
            Q(live_delivery_requests__tracking_code__iexact=tracking_code)
            | Q(delivery_requests__tracking_code__iexact=tracking_code)
            | Q(tracking_number__iexact=tracking_code)
        )
        .first()
    )
    if not order:
        return _mobile_order_json_error("Tracking code not found for this customer.", status=404)
    payload = _mobile_order_payload(request, order)
    return JsonResponse({"success": True, "tracking": payload, "order": payload})


def _mobile_cancel_json_body(request):
    try:
        return json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        return {}


def _mobile_cancel_error(message, status=400):
    return JsonResponse({"success": False, "message": str(message)}, status=status)


def _mobile_cancel_status_value():
    try:
        field = Order._meta.get_field("status")
        choice_values = [choice[0] for choice in getattr(field, "choices", []) or []]

        if "cancelled" in choice_values:
            return "cancelled"

        if "canceled" in choice_values:
            return "canceled"

        if "cancelled_by_customer" in choice_values:
            return "cancelled_by_customer"
    except Exception:
        pass

    return "cancelled"


def _mobile_cancel_order_allowed(order):
    status = str(getattr(order, "status", "") or "").strip().lower()

    if any(word in status for word in ["deliver", "complete", "cancel", "fail", "refund", "return"]):
        return False

    # If a delivery request already progressed, do not allow customer cancellation.
    try:
        delivery = order.delivery_requests.order_by("-created_at").first()
        delivery_status = str(getattr(delivery, "status", "") or "").strip().lower()

        if any(word in delivery_status for word in ["assigned", "picked", "transit", "deliver", "ship"]):
            return False
    except Exception:
        pass

    return status in ["", "pending", "pending_assignment", "processing"]


@csrf_exempt
@require_POST
def mobile_authenticated_order_cancel_api(request):
    payload = _mobile_cancel_json_body(request)

    try:
        customer = _mobile_order_auth_customer(payload)
    except PermissionError as error:
        return _mobile_cancel_error(error, status=403)
    except Exception as error:
        return _mobile_cancel_error(error, status=400)

    order_id = payload.get("order_id") or payload.get("id")
    order_number = payload.get("order_number")

    if not order_id and not order_number:
        return _mobile_cancel_error("Order ID or order number is required.", status=400)

    lookup = Q()
    if order_id:
        lookup |= Q(id=order_id)
    if order_number:
        lookup |= Q(order_number=order_number)

    ownership = Q()
    if getattr(customer, "user_id", None):
        ownership |= Q(user=customer.user)

    if hasattr(Order, "customer_phone"):
        ownership |= Q(customer_phone=customer.phone_number)

    order = Order.objects.filter(lookup).filter(ownership).first()

    if not order:
        return _mobile_cancel_error("Order not found for this customer.", status=404)

    if not _mobile_cancel_order_allowed(order):
        return _mobile_cancel_error(
            "This order can no longer be cancelled because delivery has already started.",
            status=400,
        )

    cancel_status = _mobile_cancel_status_value()
    order.status = cancel_status

    changed_fields = ["status"]

    if hasattr(order, "cancel_reason"):
        order.cancel_reason = str(payload.get("reason") or "Cancelled from mobile app")
        changed_fields.append("cancel_reason")

    if hasattr(order, "cancelled_by"):
        order.cancelled_by = "customer"
        changed_fields.append("cancelled_by")

    order.save(update_fields=list(set(changed_fields)))

    return JsonResponse(
        {
            "success": True,
            "message": "Order cancelled successfully.",
            "order": _mobile_order_payload(request, order),
        }
    )



def _receipt_error(message, status=400):
    return JsonResponse({"success": False, "message": str(message)}, status=status)


def _receipt_model_has_field(model, field_name):
    try:
        model._meta.get_field(field_name)
        return True
    except Exception:
        return False


def _receipt_clean_filename(value):
    value = str(value or "arolana-receipt").strip()
    value = re.sub(r"[^A-Za-z0-9_.-]+", "-", value)
    return value[:80] or "arolana-receipt"


def _receipt_money(value):
    try:
        amount = Decimal(str(value or "0").replace(",", ""))
    except Exception:
        amount = Decimal("0")

    return f"NGN {amount:,.2f}"


def _receipt_get_order_for_customer(request):
    if "_mobile_order_auth_customer" not in globals():
        raise RuntimeError(
            "Authenticated orders patch is required before PDF receipts. "
            "Paste orders_mobile_customer_auth_patch.py first."
        )

    customer = _mobile_order_auth_customer(request)

    order_id = request.GET.get("order_id") or request.GET.get("id")
    order_number = request.GET.get("order_number")

    if not order_id and not order_number:
        raise ValueError("Order ID or order number is required.")

    lookup = Q()
    if order_id:
        lookup |= Q(id=order_id)
    if order_number and _receipt_model_has_field(Order, "order_number"):
        lookup |= Q(order_number=order_number)

    ownership = Q()
    if getattr(customer, "user_id", None) and _receipt_model_has_field(Order, "user"):
        ownership |= Q(user=customer.user)

    if _receipt_model_has_field(Order, "customer_phone"):
        ownership |= Q(customer_phone=customer.phone_number)

    order = Order.objects.filter(lookup).filter(ownership).first()

    if not order:
        raise PermissionError("Order not found for this customer.")

    return customer, order


def _receipt_order_items(order):
    if hasattr(order, "items"):
        try:
            return list(order.items.select_related("product").all())
        except Exception:
            pass

    try:
        return list(order.orderitem_set.select_related("product").all())
    except Exception:
        return []


def _receipt_item_values(item):
    product = getattr(item, "product", None)
    name = (
        getattr(product, "name", "")
        or getattr(product, "title", "")
        or getattr(item, "name", "")
        or str(product or "Product")
    )

    quantity = getattr(item, "quantity", 1) or 1

    unit_price = (
        getattr(item, "price", None)
        or getattr(item, "unit_price", None)
        or getattr(item, "amount", None)
        or getattr(item, "price_at_order", None)
        or getattr(item, "price_at_add", None)
        or 0
    )

    subtotal = getattr(item, "subtotal", None)

    try:
        subtotal_value = subtotal() if callable(subtotal) else subtotal
    except Exception:
        subtotal_value = None

    if subtotal_value in [None, ""]:
        try:
            subtotal_value = Decimal(str(unit_price or "0")) * Decimal(str(quantity or "0"))
        except Exception:
            subtotal_value = Decimal("0")

    return name, quantity, unit_price, subtotal_value


def _receipt_order_field(order, *field_names, default=""):
    for field_name in field_names:
        value = getattr(order, field_name, None)
        if value not in [None, ""]:
            return value
    return default


def _receipt_effective_tracking_status(order):
    for field_name in ["delivery_status", "tracking_status", "shipment_status"]:
        value = getattr(order, field_name, None)
        if value:
            return value

    try:
        delivery = order.delivery_requests.order_by("-created_at").first()
        if delivery:
            return getattr(delivery, "status", "") or getattr(delivery, "delivery_status", "")
    except Exception:
        pass

    return getattr(order, "status", "")


@require_GET
def mobile_authenticated_order_receipt_pdf_api(request):
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER, TA_RIGHT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except Exception:
        return _receipt_error(
            "ReportLab is not installed. Run: pip install reportlab",
            status=500,
        )

    try:
        customer, order = _receipt_get_order_for_customer(request)
    except PermissionError as error:
        return _receipt_error(error, status=403)
    except Exception as error:
        return _receipt_error(error, status=400)

    buffer = BytesIO()

    order_number = _receipt_order_field(order, "order_number", default=str(order.id))
    filename = _receipt_clean_filename(f"arolana-receipt-{order_number}.pdf")

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=16 * mm,
        leftMargin=16 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title=f"Arolana Receipt {order_number}",
        author="Arolana",
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "ArolanaTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=24,
        leading=28,
        textColor=colors.HexColor("#071B3A"),
        spaceAfter=8,
    )

    section_style = ParagraphStyle(
        "ArolanaSection",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=16,
        textColor=colors.HexColor("#071B3A"),
        spaceBefore=10,
        spaceAfter=8,
    )

    small_style = ParagraphStyle(
        "ArolanaSmall",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#64748B"),
    )

    normal_style = ParagraphStyle(
        "ArolanaNormal",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#0F172A"),
    )

    right_style = ParagraphStyle(
        "ArolanaRight",
        parent=normal_style,
        alignment=TA_RIGHT,
    )

    center_style = ParagraphStyle(
        "ArolanaCenter",
        parent=normal_style,
        alignment=TA_CENTER,
    )

    story = []

    created_at = getattr(order, "created_at", None)
    created_text = created_at.strftime("%d %b %Y, %I:%M %p") if created_at else ""

    status = _receipt_order_field(order, "status", default="Pending")
    tracking_status = _receipt_effective_tracking_status(order) or status
    tracking_code = _receipt_order_field(order, "tracking_code", "tracking_number", default="Not assigned")
    payment_status = _receipt_order_field(order, "payment_status", default="Pending")
    payment_method = _receipt_order_field(order, "payment_method", "payment_type", default="paystack")

    header_table = Table(
        [
            [
                Paragraph("<b>AROLANA</b><br/><font size='9'>Secure Marketplace Receipt</font>", title_style),
                Paragraph(
                    f"<b>Receipt / Invoice</b><br/>Order: {order_number}<br/>Date: {created_text}",
                    right_style,
                ),
            ]
        ],
        colWidths=[105 * mm, 72 * mm],
    )
    header_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
            ]
        )
    )
    story.append(header_table)

    status_table = Table(
        [
            [
                Paragraph(f"<b>Order Status</b><br/>{status}", normal_style),
                Paragraph(f"<b>Delivery Status</b><br/>{tracking_status}", normal_style),
                Paragraph(f"<b>Payment Status</b><br/>{payment_status}", normal_style),
            ]
        ],
        colWidths=[59 * mm, 59 * mm, 59 * mm],
    )
    status_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FFF7ED")),
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#FED7AA")),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#FED7AA")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("PADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(status_table)
    story.append(Spacer(1, 8))

    customer_name = (
        getattr(order, "customer_name", "")
        or getattr(customer, "full_name", "")
        or "Customer"
    )
    customer_phone = getattr(order, "customer_phone", "") or customer.phone_number
    customer_email = getattr(order, "customer_email", "") or customer.email

    delivery_address = (
        getattr(order, "delivery_address", "")
        or getattr(order, "shipping_address", "")
        or getattr(getattr(order, "customer", None), "delivery_address", "")
        or "Delivery address saved with order"
    )

    info_table = Table(
        [
            [
                Paragraph("<b>Customer</b>", section_style),
                Paragraph("<b>Delivery / Tracking</b>", section_style),
            ],
            [
                Paragraph(
                    f"{customer_name}<br/>Phone: {customer_phone}<br/>Email: {customer_email or 'Not provided'}",
                    normal_style,
                ),
                Paragraph(
                    f"Tracking Code: {tracking_code}<br/>Payment Method: {payment_method}<br/>Deliver to: {delivery_address}",
                    normal_style,
                ),
            ],
        ],
        colWidths=[88 * mm, 89 * mm],
    )
    info_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F8FAFC")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#E2E8F0")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("PADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(info_table)
    story.append(Spacer(1, 10))

    story.append(Paragraph("Items", section_style))

    item_rows = [
        [
            Paragraph("<b>#</b>", normal_style),
            Paragraph("<b>Product</b>", normal_style),
            Paragraph("<b>Qty</b>", center_style),
            Paragraph("<b>Unit Price</b>", right_style),
            Paragraph("<b>Total</b>", right_style),
        ]
    ]

    for index, item in enumerate(_receipt_order_items(order), start=1):
        name, quantity, unit_price, subtotal_value = _receipt_item_values(item)
        item_rows.append(
            [
                str(index),
                Paragraph(str(name), normal_style),
                Paragraph(str(quantity), center_style),
                Paragraph(_receipt_money(unit_price), right_style),
                Paragraph(_receipt_money(subtotal_value), right_style),
            ]
        )

    if len(item_rows) == 1:
        item_rows.append(["1", Paragraph("No item details found.", normal_style), "", "", ""])

    item_table = Table(
        item_rows,
        colWidths=[10 * mm, 78 * mm, 18 * mm, 35 * mm, 36 * mm],
        repeatRows=1,
    )
    item_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#071B3A")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#E2E8F0")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("PADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    story.append(item_table)
    story.append(Spacer(1, 10))

    subtotal = _receipt_order_field(order, "subtotal", default=0)
    delivery_fee = _receipt_order_field(order, "delivery_fee", "shipping_cost", default=0)
    tax = _receipt_order_field(order, "tax", default=0)
    total = _receipt_order_field(order, "total", "grand_total", default=0)

    totals_table = Table(
        [
            ["Subtotal", _receipt_money(subtotal)],
            ["Delivery Fee", _receipt_money(delivery_fee)],
            ["Tax", _receipt_money(tax)],
            [Paragraph("<b>Total</b>", normal_style), Paragraph(f"<b>{_receipt_money(total)}</b>", right_style)],
        ],
        colWidths=[130 * mm, 47 * mm],
    )
    totals_table.setStyle(
        TableStyle(
            [
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#FFF7ED")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#E2E8F0")),
                ("PADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(totals_table)
    story.append(Spacer(1, 12))

    story.append(
        Paragraph(
            "Thank you for shopping with Arolana. This receipt was generated securely from your logged-in mobile customer account.",
            small_style,
        )
    )
    story.append(
        Paragraph(
            "For support, open Arolana Smart Chat in the mobile app or contact Arolana customer service.",
            small_style,
        )
    )

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#94A3B8"))
        canvas.drawString(16 * mm, 9 * mm, "Arolana Secure Marketplace")
        canvas.drawRightString(194 * mm, 9 * mm, f"Page {doc.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)

    pdf_value = buffer.getvalue()
    buffer.close()

    response = HttpResponse(pdf_value, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    response["Content-Length"] = str(len(pdf_value))
    return response
