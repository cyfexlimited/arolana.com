from decimal import Decimal, ROUND_HALF_UP

from django.utils import timezone


def money(value):
    """Return a Decimal money value without mixing floats into calculations."""
    return Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calculate_surge_multiplier(
    active_delivery_requests=0,
    available_riders=0,
    weather_bad=False,
    is_peak_hour=False,
    is_night=False,
    is_rainy=False,
):
    """Demand, rider supply, time, and weather based delivery surge."""
    multiplier = Decimal("1.00")

    if available_riders <= 0 and active_delivery_requests > 0:
        multiplier += Decimal("0.80")
    elif available_riders > 0:
        demand_ratio = Decimal(str(active_delivery_requests)) / Decimal(str(available_riders))
        if demand_ratio >= Decimal("5"):
            multiplier += Decimal("0.70")
        elif demand_ratio >= Decimal("3"):
            multiplier += Decimal("0.50")
        elif demand_ratio >= Decimal("2"):
            multiplier += Decimal("0.30")
        elif demand_ratio >= Decimal("1.3"):
            multiplier += Decimal("0.15")

    if is_peak_hour:
        multiplier += Decimal("0.20")
    if is_night:
        multiplier += Decimal("0.25")
    if weather_bad or is_rainy:
        multiplier += Decimal("0.25")

    return min(multiplier, Decimal("2.50")).quantize(Decimal("0.01"))


def calculate_delivery_price(
    distance_km,
    estimated_minutes,
    package_weight_kg=0,
    active_delivery_requests=0,
    available_riders=0,
    weather_bad=False,
    is_rainy=False,
    express=False,
    base_fare=1000,
    per_km_rate=250,
    per_minute_rate=35,
    service_fee=300,
    express_fee=1200,
    free_weight_kg=5,
    extra_weight_rate=150,
):
    """Main Arolana delivery pricing engine."""
    now = timezone.localtime()
    hour = now.hour
    is_peak_hour = hour in [7, 8, 9, 16, 17, 18, 19, 20]
    is_night = hour >= 21 or hour <= 5

    distance_km = money(distance_km)
    estimated_minutes = money(estimated_minutes)
    package_weight_kg = money(package_weight_kg)

    base_fare = money(base_fare)
    per_km_rate = money(per_km_rate)
    per_minute_rate = money(per_minute_rate)
    service_fee = money(service_fee)

    distance_fee = distance_km * per_km_rate
    time_fee = estimated_minutes * per_minute_rate

    weight_fee = money(0)
    free_weight_kg = money(free_weight_kg)
    if package_weight_kg > free_weight_kg:
        weight_fee = (package_weight_kg - free_weight_kg) * money(extra_weight_rate)

    express_fee_value = money(express_fee) if express else money(0)

    subtotal = base_fare + distance_fee + time_fee + weight_fee + service_fee + express_fee_value
    surge_multiplier = calculate_surge_multiplier(
        active_delivery_requests=active_delivery_requests,
        available_riders=available_riders,
        weather_bad=weather_bad,
        is_peak_hour=is_peak_hour,
        is_night=is_night,
        is_rainy=is_rainy,
    )
    final_price = subtotal * surge_multiplier

    return {
        "base_fare": base_fare,
        "distance_fee": distance_fee.quantize(Decimal("0.01")),
        "time_fee": time_fee.quantize(Decimal("0.01")),
        "weight_fee": weight_fee.quantize(Decimal("0.01")),
        "service_fee": service_fee,
        "express_fee": express_fee_value,
        "surge_multiplier": surge_multiplier,
        "subtotal": subtotal.quantize(Decimal("0.01")),
        "final_price": final_price.quantize(Decimal("0.01")),
        "is_peak_hour": is_peak_hour,
        "is_night": is_night,
        "is_rainy": is_rainy,
    }
