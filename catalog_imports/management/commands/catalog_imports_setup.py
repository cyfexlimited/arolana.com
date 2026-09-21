from decimal import Decimal

from django.core.management.base import BaseCommand

from catalog_imports.models import BrandVerificationProfile, ImportPricingRule, ImportSource


class Command(BaseCommand):
    help = "Create safe starter configuration for the universal product importer."

    def handle(self, *args, **options):
        paykobo, _ = ImportSource.objects.update_or_create(
            domain="paykobo.com",
            defaults={
                "name": "Paykobo",
                "is_active": True,
                "extraction_mode": ImportSource.MODE_ADAPTER,
                "default_currency": "NGN",
                "adapter_key": "paykobo",
                "configuration": {"timeout_seconds": 12},
                "notes": "Retailer source. The importer does not bypass source access controls.",
            },
        )
        rule, created = ImportPricingRule.objects.get_or_create(
            name="Default import markup +₦50,000",
            defaults={
                "is_active": True,
                "priority": 10,
                "fixed_markup": Decimal("50000.00"),
                "percentage_markup": Decimal("0.000"),
                "rounding_mode": ImportPricingRule.ROUND_NONE,
            },
        )
        logitech, logitech_created = BrandVerificationProfile.objects.get_or_create(
            brand_name="Logitech",
            defaults={
                "manufacturer_name": "Logitech",
                "official_domain": "logitech.com",
                "aliases": ["logitech"],
                "is_active": True,
                "notes": "Starter manufacturer verification profile. Editable in Django Admin.",
            },
        )
        self.stdout.write(self.style.SUCCESS(f"Paykobo source ready: {paykobo.pk}"))
        self.stdout.write(self.style.SUCCESS(f"Default pricing rule ready: {rule.pk} ({'created' if created else 'existing'})"))
        self.stdout.write(self.style.SUCCESS(f"Logitech verification profile ready: {logitech.pk} ({'created' if logitech_created else 'existing'})"))
