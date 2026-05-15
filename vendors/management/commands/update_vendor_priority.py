from django.core.management.base import BaseCommand
from vendors.models import VendorProfile
from django.utils import timezone
from subscriptions.models import get_tier_limits, normalize_subscription_tier

class Command(BaseCommand):
    help = 'Update vendor priority scores based on subscription tiers'

    def handle(self, *args, **kwargs):
        for vendor in VendorProfile.objects.all():
            # Check if subscription is expired
            if vendor.subscription_expiry and vendor.subscription_expiry < timezone.now():
                vendor.subscription_tier = 'free'
            else:
                vendor.subscription_tier = normalize_subscription_tier(vendor.subscription_tier)

            vendor.priority_score = get_tier_limits(vendor.subscription_tier)['priority_score']

            vendor.save()
            self.stdout.write(f"Updated {vendor.store_name}: {vendor.subscription_tier} (Score: {vendor.priority_score})")

        self.stdout.write(self.style.SUCCESS('Successfully updated vendor priorities'))
