import math
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.db import transaction
from django.utils import timezone

from ..models import (
    DeliveryLocationPing,
    DeliveryPricingRule,
    DeliveryRequest,
    DeliveryVehicle,
    RiderProfile,
    RiderWallet,
)
from .pricing import calculate_delivery_price


SERVICE_LEVEL_MULTIPLIERS = {
    "standard": Decimal("1.00"),
    "express": Decimal("1.00"),
    "arolana_dispatch": Decimal("1.00"),
    "pickup_vendor": Decimal("0.00"),
    "pickup_from_vendor": Decimal("0.00"),
}


def money(value, default="0.00"):
    try:
        return Decimal(str(value if value not in (None, "") else default)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default).quantize(Decimal("0.01"))


def decimal_or_none(value):
    try:
        if value in (None, ""):
            return None
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def haversine_km(lat1, lon1, lat2, lon2):
    lat1 = decimal_or_none(lat1)
    lon1 = decimal_or_none(lon1)
    lat2 = decimal_or_none(lat2)
    lon2 = decimal_or_none(lon2)
    if None in (lat1, lon1, lat2, lon2):
        return None

    radius_km = 6371.0088
    phi1 = math.radians(float(lat1))
    phi2 = math.radians(float(lat2))
    delta_phi = math.radians(float(lat2 - lat1))
    delta_lambda = math.radians(float(lon2 - lon1))
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    return Decimal(str(radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))).quantize(Decimal("0.01"))


def _default_vehicle():
    vehicle = DeliveryVehicle.objects.filter(vehicle_type=DeliveryVehicle.VEHICLE_MOTORCYCLE, is_active=True).first()
    if vehicle:
        return vehicle
    return DeliveryVehicle.objects.filter(is_active=True).order_by("id").first()


def _pricing_rule(vehicle=None, service_level="standard"):
    rule = (
        DeliveryPricingRule.objects
        .filter(is_active=True, vehicle=vehicle)
        .order_by("-is_default", "id")
        .first()
    )
    if rule:
        return rule
    return DeliveryPricingRule.objects.filter(is_active=True, is_default=True).order_by("id").first()


def calculate_live_delivery_quote(
    pickup_latitude=None,
    pickup_longitude=None,
    dropoff_latitude=None,
    dropoff_longitude=None,
    service_level="standard",
    vehicle=None,
    fallback_fee=None,
    package_weight_kg=0,
    weather_bad=False,
    is_rainy=False,
):
    """Distance-based delivery quote. Uses Haversine when map pins exist."""
    if service_level in {"pickup_vendor", "pickup_from_vendor"}:
        return {
            "fee": Decimal("0.00"),
            "distance_km": Decimal("0.00"),
            "estimated_duration_minutes": 0,
            "package_weight_kg": Decimal("0.00"),
            "base_fare": Decimal("0.00"),
            "distance_fee": Decimal("0.00"),
            "time_fee": Decimal("0.00"),
            "weight_fee": Decimal("0.00"),
            "service_fee": Decimal("0.00"),
            "express_fee": Decimal("0.00"),
            "surge_multiplier": Decimal("1.00"),
            "pricing_subtotal": Decimal("0.00"),
            "rider_earning": Decimal("0.00"),
            "is_distance_based": False,
            "message": "Pickup from vendor is free after vendor confirmation.",
        }

    vehicle = vehicle or _default_vehicle()
    rule = _pricing_rule(vehicle=vehicle, service_level=service_level)
    distance = haversine_km(pickup_latitude, pickup_longitude, dropoff_latitude, dropoff_longitude)
    is_distance_based = distance is not None

    if rule:
        base_fee = money(rule.base_fee)
        per_km_fee = money(rule.per_km_fee)
        minimum_fee = money(rule.minimum_fee)
        maximum_fee = money(rule.maximum_fee) if rule.maximum_fee else None
        commission_percent = money(rule.rider_commission_percent, "70.00")
    elif vehicle:
        base_fee = money(vehicle.base_fee, "1000.00")
        per_km_fee = money(vehicle.per_km_fee, "250.00")
        minimum_fee = Decimal("1500.00")
        maximum_fee = None
        commission_percent = money(vehicle.rider_commission_percent, "70.00")
    else:
        base_fee = Decimal("1000.00")
        per_km_fee = Decimal("250.00")
        minimum_fee = Decimal("1500.00")
        maximum_fee = None
        commission_percent = Decimal("70.00")

    speed = money(getattr(vehicle, "base_speed_kmph", None), "30.00") if vehicle else Decimal("30.00")
    duration = 0
    if distance and distance > 0 and speed > 0:
        duration = int(((distance / speed) * Decimal("60")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    pricing = {
        "base_fare": base_fee,
        "distance_fee": Decimal("0.00"),
        "time_fee": Decimal("0.00"),
        "weight_fee": Decimal("0.00"),
        "service_fee": Decimal("0.00"),
        "express_fee": Decimal("0.00"),
        "surge_multiplier": Decimal("1.00"),
        "subtotal": Decimal("0.00"),
        "final_price": Decimal("0.00"),
    }

    if not is_distance_based:
        fallback = money(fallback_fee, "2500.00")
        fee = max(minimum_fee, fallback)
        distance = Decimal("0.00")
        duration = 0
        has_pickup = all(decimal_or_none(value) is not None for value in (pickup_latitude, pickup_longitude))
        has_dropoff = all(decimal_or_none(value) is not None for value in (dropoff_latitude, dropoff_longitude))
        if has_dropoff and not has_pickup:
            message = "Vendor pickup map pin is missing. Add vendor pickup coordinates in admin for exact vendor-to-customer delivery pricing."
        elif has_pickup and not has_dropoff:
            message = "Use your current location or choose a drop-off map pin for exact vendor-to-customer delivery pricing."
        else:
            message = "Add pickup and drop-off map pins for exact distance pricing. This is the zone minimum for now."
    else:
        active_delivery_requests = DeliveryRequest.objects.filter(
            status__in=[
                DeliveryRequest.STATUS_PENDING,
                DeliveryRequest.STATUS_ASSIGNED,
                DeliveryRequest.STATUS_ACCEPTED,
                DeliveryRequest.STATUS_PICKED_UP,
                DeliveryRequest.STATUS_IN_TRANSIT,
            ]
        ).count()
        available_riders = RiderProfile.objects.filter(
            is_online=True,
            is_available=True,
            is_suspended=False,
            kyc_status=RiderProfile.KYC_APPROVED,
        ).count()
        pricing = calculate_delivery_price(
            distance_km=distance,
            estimated_minutes=duration,
            package_weight_kg=package_weight_kg,
            active_delivery_requests=active_delivery_requests,
            available_riders=available_riders,
            weather_bad=weather_bad,
            is_rainy=is_rainy,
            express=service_level == "express",
            base_fare=base_fee,
            per_km_rate=per_km_fee,
        )
        multiplier = SERVICE_LEVEL_MULTIPLIERS.get(service_level, Decimal("1.00"))
        fee = (pricing["final_price"] * multiplier).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        fee = max(minimum_fee, fee).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if maximum_fee:
            fee = min(maximum_fee, fee)
        message = "Delivery fee calculated from pickup to drop-off distance, travel time, package weight, service fee, and live rider demand."

    rider_earning = (fee * (commission_percent / Decimal("100"))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {
        "fee": fee,
        "distance_km": distance,
        "estimated_duration_minutes": duration,
        "package_weight_kg": money(package_weight_kg),
        "base_fare": money(pricing["base_fare"]),
        "distance_fee": money(pricing["distance_fee"]),
        "time_fee": money(pricing["time_fee"]),
        "weight_fee": money(pricing["weight_fee"]),
        "service_fee": money(pricing["service_fee"]),
        "express_fee": money(pricing["express_fee"]),
        "surge_multiplier": money(pricing["surge_multiplier"], "1.00"),
        "pricing_subtotal": money(pricing["subtotal"]),
        "rider_earning": rider_earning,
        "is_distance_based": is_distance_based,
        "message": message,
    }


def vendor_pickup_context_from_user(vendor_user):
    profile = getattr(vendor_user, "vendor_profile", None)
    if not profile:
        return {}

    return {
        "pickup_name": profile.pickup_contact_name or profile.store_name,
        "pickup_phone": profile.pickup_phone or "",
        "pickup_address": profile.pickup_address or "",
        "pickup_latitude": str(profile.pickup_latitude or ""),
        "pickup_longitude": str(profile.pickup_longitude or ""),
        "pickup_vendor_id": str(profile.id),
        "pickup_vendor_name": profile.store_name,
    }


def cart_pickup_context(cart):
    """Return a single vendor pickup context for checkout.

    If a cart has products from multiple vendors, use the first vendor for now and
    flag the response. A later multi-vendor checkout should split the cart into
    per-vendor delivery requests.
    """
    if not cart:
        return {}

    vendor_users = []
    for item in cart.items.select_related("product__vendor", "accessory").all():
        product = getattr(item, "product", None)
        if product and product.vendor_id and product.vendor not in vendor_users:
            vendor_users.append(product.vendor)

    if not vendor_users:
        return {}

    context = vendor_pickup_context_from_user(vendor_users[0])
    context["pickup_is_multi_vendor"] = len(vendor_users) > 1
    if context.get("pickup_is_multi_vendor"):
        context["pickup_warning"] = "This cart has multiple vendors. Delivery is calculated from the first vendor for now."
    return context


def product_weight_kg(product):
    if not product or not getattr(product, "weight", None):
        return Decimal("0.00")

    weight = money(product.weight)
    unit = (getattr(product, "weight_unit", "kg") or "kg").lower()
    if unit == "g":
        return (weight / Decimal("1000")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if unit == "lbs":
        return (weight * Decimal("0.45359237")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if unit == "oz":
        return (weight * Decimal("0.0283495231")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return weight


def cart_package_weight_kg(cart):
    if not cart:
        return Decimal("0.00")

    total = Decimal("0.00")
    for item in cart.items.select_related("product", "variant__product").all():
        product = getattr(item, "product", None) or getattr(getattr(item, "variant", None), "product", None)
        total += product_weight_kg(product) * Decimal(str(getattr(item, "quantity", 1) or 1))
    return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def create_live_delivery_for_order(order, legacy_delivery=None, checkout_data=None, service_level="standard"):
    checkout_data = checkout_data or {}
    existing = DeliveryRequest.objects.filter(order=order).order_by("-created_at").first()
    if existing:
        return existing

    pickup_address = checkout_data.get("pickup_address") or "Vendor pickup address to be assigned"
    dropoff_address = order.shipping_address or checkout_data.get("address") or "Customer drop-off address"
    quote = calculate_live_delivery_quote(
        pickup_latitude=checkout_data.get("pickup_latitude"),
        pickup_longitude=checkout_data.get("pickup_longitude"),
        dropoff_latitude=checkout_data.get("dropoff_latitude"),
        dropoff_longitude=checkout_data.get("dropoff_longitude"),
        service_level=service_level,
        fallback_fee=getattr(order, "shipping_cost", None),
        package_weight_kg=checkout_data.get("package_weight_kg", 0),
    )
    delivery = DeliveryRequest.objects.create(
        order=order,
        legacy_delivery=legacy_delivery,
        pickup_name=checkout_data.get("pickup_name", "Vendor"),
        pickup_phone=checkout_data.get("pickup_phone", ""),
        pickup_address=pickup_address,
        pickup_latitude=decimal_or_none(checkout_data.get("pickup_latitude")),
        pickup_longitude=decimal_or_none(checkout_data.get("pickup_longitude")),
        dropoff_name=(order.user.get_full_name() or order.user.email or "Customer") if order.user_id else "Customer",
        dropoff_phone=checkout_data.get("phone", ""),
        dropoff_address=dropoff_address,
        dropoff_latitude=decimal_or_none(checkout_data.get("dropoff_latitude")),
        dropoff_longitude=decimal_or_none(checkout_data.get("dropoff_longitude")),
        distance_km=quote["distance_km"],
        estimated_duration_minutes=quote["estimated_duration_minutes"],
        package_weight_kg=quote["package_weight_kg"],
        base_fare=quote["base_fare"],
        distance_fee=quote["distance_fee"],
        time_fee=quote["time_fee"],
        weight_fee=quote["weight_fee"],
        service_fee=quote["service_fee"],
        express_fee=quote["express_fee"],
        surge_multiplier=quote["surge_multiplier"],
        delivery_fee=quote["fee"],
        rider_earning=quote["rider_earning"],
        customer_note=checkout_data.get("delivery_note", ""),
    )
    DeliveryRequest.objects.filter(pk=delivery.pk).update(updated_at=timezone.now())
    delivery.set_status(DeliveryRequest.STATUS_PENDING, note="Delivery created after payment.")
    return delivery


@transaction.atomic
def accept_delivery(delivery, rider):
    if not rider.can_accept_deliveries:
        raise ValueError("Rider must be approved, online, available, and not suspended.")
    if delivery.status not in {DeliveryRequest.STATUS_PENDING, DeliveryRequest.STATUS_ASSIGNED}:
        raise ValueError("This delivery is no longer available.")
    delivery.rider = rider
    delivery.save(update_fields=["rider", "updated_at"])
    delivery.set_status(DeliveryRequest.STATUS_ACCEPTED, actor=rider.user, note="Rider accepted delivery.")
    RiderWallet.objects.get_or_create(rider=rider)
    return delivery


def update_rider_location(delivery, rider, latitude, longitude, heading=None, speed_kmph=None, accuracy_meters=None):
    lat = decimal_or_none(latitude)
    lon = decimal_or_none(longitude)
    if lat is None or lon is None:
        raise ValueError("Valid latitude and longitude are required.")
    rider.current_latitude = lat
    rider.current_longitude = lon
    rider.last_location_at = timezone.now()
    rider.save(update_fields=["current_latitude", "current_longitude", "last_location_at", "updated_at"])
    return DeliveryLocationPing.objects.create(
        delivery=delivery,
        rider=rider,
        latitude=lat,
        longitude=lon,
        heading=decimal_or_none(heading),
        speed_kmph=decimal_or_none(speed_kmph),
        accuracy_meters=decimal_or_none(accuracy_meters),
    )
