from decimal import Decimal

from django.db import migrations


def seed_delivery_defaults(apps, schema_editor):
    DeliveryVehicle = apps.get_model("deliveries", "DeliveryVehicle")
    DeliveryZone = apps.get_model("deliveries", "DeliveryZone")
    DeliveryPricingRule = apps.get_model("deliveries", "DeliveryPricingRule")

    vehicles = [
        ("motorcycle", "Motorcycle Dispatch", Decimal("20.00"), Decimal("35.00"), Decimal("1000.00"), Decimal("250.00")),
        ("bicycle", "Bicycle Courier", Decimal("8.00"), Decimal("15.00"), Decimal("700.00"), Decimal("150.00")),
        ("car", "Car Delivery", Decimal("80.00"), Decimal("30.00"), Decimal("2500.00"), Decimal("350.00")),
        ("van", "Van Delivery", Decimal("300.00"), Decimal("25.00"), Decimal("5000.00"), Decimal("550.00")),
        ("truck", "Truck Delivery", Decimal("1000.00"), Decimal("20.00"), Decimal("12000.00"), Decimal("900.00")),
    ]
    vehicle_map = {}
    for vehicle_type, name, capacity, speed, base_fee, per_km in vehicles:
        vehicle, _created = DeliveryVehicle.objects.update_or_create(
            vehicle_type=vehicle_type,
            defaults={
                "name": name,
                "base_capacity_kg": capacity,
                "base_speed_kmph": speed,
                "base_fee": base_fee,
                "per_km_fee": per_km,
                "rider_commission_percent": Decimal("70.00"),
                "is_active": True,
            },
        )
        vehicle_map[vehicle_type] = vehicle

    lagos, _created = DeliveryZone.objects.update_or_create(
        code="lagos-metro",
        defaults={
            "name": "Lagos Metro",
            "city": "Lagos",
            "state": "Lagos",
            "country": "Nigeria",
            "center_latitude": Decimal("6.5244000"),
            "center_longitude": Decimal("3.3792000"),
            "radius_km": Decimal("60.00"),
            "is_active": True,
        },
    )

    DeliveryPricingRule.objects.update_or_create(
        name="Default Motorcycle Distance Pricing",
        defaults={
            "zone": lagos,
            "vehicle": vehicle_map.get("motorcycle"),
            "base_fee": Decimal("1000.00"),
            "per_km_fee": Decimal("250.00"),
            "minimum_fee": Decimal("1500.00"),
            "maximum_fee": None,
            "surge_multiplier": Decimal("1.00"),
            "rider_commission_percent": Decimal("70.00"),
            "is_default": True,
            "is_active": True,
        },
    )


def reverse_seed_delivery_defaults(apps, schema_editor):
    DeliveryPricingRule = apps.get_model("deliveries", "DeliveryPricingRule")
    DeliveryPricingRule.objects.filter(name="Default Motorcycle Distance Pricing").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("deliveries", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_delivery_defaults, reverse_seed_delivery_defaults),
    ]
