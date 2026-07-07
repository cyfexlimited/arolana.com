from decimal import Decimal

from django.db import migrations


BACKFILL_NOTE = "Auto-created default offer from legacy product inventory."


def backfill_default_vendor_offers(apps, schema_editor):
    Product = apps.get_model("products", "Product")
    VendorProfile = apps.get_model("vendors", "VendorProfile")
    VendorProductOffer = apps.get_model("products", "VendorProductOffer")

    vendor_profiles = {
        profile.user_id: profile
        for profile in VendorProfile.objects.filter(user_id__isnull=False).only("id", "user_id")
    }

    products = (
        Product.objects.filter(
            vendor_id__isnull=False,
            is_active=True,
            approval_status="approved",
            price__gt=Decimal("0"),
        )
        .only(
            "id",
            "vendor_id",
            "sku",
            "price",
            "stock_quantity",
            "reserved_quantity",
            "condition",
            "warranty_description",
        )
        .iterator(chunk_size=500)
    )

    offers_to_create = []
    for product in products:
        vendor_profile = vendor_profiles.get(product.vendor_id)
        if not vendor_profile:
            continue

        if VendorProductOffer.objects.filter(
            vendor=vendor_profile,
            product_id=product.id,
            variant__isnull=True,
        ).exists():
            continue

        stock_quantity = max(
            int(product.stock_quantity or 0) - int(product.reserved_quantity or 0),
            0,
        )
        seller_sku = f"{product.sku or 'PRODUCT'}-{vendor_profile.id}".strip("-")

        offers_to_create.append(
            VendorProductOffer(
                vendor=vendor_profile,
                product_id=product.id,
                variant_id=None,
                seller_sku=seller_sku[:120],
                price=product.price,
                stock_quantity=stock_quantity,
                reserved_quantity=0,
                condition=product.condition or "brand_new",
                seller_warranty=product.warranty_description or "",
                approval_status="approved",
                approval_notes=BACKFILL_NOTE,
                is_featured=False,
                is_preferred=True,
                is_active=True,
            )
        )

        if len(offers_to_create) >= 500:
            VendorProductOffer.objects.bulk_create(offers_to_create, ignore_conflicts=True)
            offers_to_create = []

    if offers_to_create:
        VendorProductOffer.objects.bulk_create(offers_to_create, ignore_conflicts=True)


def remove_backfilled_vendor_offers(apps, schema_editor):
    VendorProductOffer = apps.get_model("products", "VendorProductOffer")
    VendorProductOffer.objects.filter(approval_notes=BACKFILL_NOTE).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0028_productcatalogrequest"),
        ("vendors", "0015_vendorprofile_business_hours_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_default_vendor_offers, remove_backfilled_vendor_offers),
    ]
