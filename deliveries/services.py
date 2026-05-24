import math
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.db import transaction
from django.utils import timezone

from .models import (
    DeliveryLocationPing,
    DeliveryPricingRule,
    DeliveryRequest,
    DeliveryVehicle,
    RiderWallet,
)


SERVICE_LEVEL_MULTIPLIERS = {
    "standard": Decimal("1.00"),
    "express": Decimal("1.35"),
    "arolana_dispatch": Decimal("1.15"),
    "uber_direct": Decimal("1.55"),
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
):
    """Distance-based delivery quote. Uses Haversine when map pins exist."""
    if service_level in {"pickup_vendor", "pickup_from_vendor"}:
        return {
            "fee": Decimal("0.00"),
            "distance_km": Decimal("0.00"),
            "estimated_duration_minutes": 0,
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
        surge = money(rule.surge_multiplier, "1.00")
        commission_percent = money(rule.rider_commission_percent, "70.00")
    elif vehicle:
        base_fee = money(vehicle.base_fee, "1000.00")
        per_km_fee = money(vehicle.per_km_fee, "250.00")
        minimum_fee = Decimal("1500.00")
        maximum_fee = None
        surge = Decimal("1.00")
        commission_percent = money(vehicle.rider_commission_percent, "70.00")
    else:
        base_fee = Decimal("1000.00")
        per_km_fee = Decimal("250.00")
        minimum_fee = Decimal("1500.00")
        maximum_fee = None
        surge = Decimal("1.00")
        commission_percent = Decimal("70.00")

    if not is_distance_based:
        fallback = money(fallback_fee, "2500.00")
        fee = max(minimum_fee, fallback)
        distance = Decimal("0.00")
        message = "Add pickup and drop-off map pins for exact distance pricing. This is the zone minimum for now."
    else:
        multiplier = SERVICE_LEVEL_MULTIPLIERS.get(service_level, Decimal("1.00"))
        fee = (base_fee + (distance * per_km_fee)) * surge * multiplier
        fee = max(minimum_fee, fee).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if maximum_fee:
            fee = min(maximum_fee, fee)
        message = "Delivery fee calculated from pickup to drop-off distance."

    speed = money(getattr(vehicle, "base_speed_kmph", None), "30.00") if vehicle else Decimal("30.00")
    duration = 0
    if distance > 0 and speed > 0:
        duration = int(((distance / speed) * Decimal("60")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    rider_earning = (fee * (commission_percent / Decimal("100"))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {
        "fee": fee,
        "distance_km": distance,
        "estimated_duration_minutes": duration,
        "rider_earning": rider_earning,
        "is_distance_based": is_distance_based,
        "message": message,
    }


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
