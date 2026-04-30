from django.core.management.base import BaseCommand
from vendors.models import VendorProfile
from django.utils import timezone

class Command(BaseCommand):
    help = 'Update vendor priority scores based on subscription tiers'
    
    def handle(self, *args, **kwargs):
        tier_scores = {
            'free': 10,
            'basic': 50,
            'premium': 100,
            'enterprise': 200,
            'featured': 500,
        }
        
        for vendor in VendorProfile.objects.all():
            # Check if subscription is expired
            if vendor.subscription_expiry and vendor.subscription_expiry < timezone.now():
                vendor.subscription_tier = 'free'
                vendor.priority_score = tier_scores['free']
            else:
                vendor.priority_score = tier_scores.get(vendor.subscription_tier, 10)
            
            vendor.save()
            self.stdout.write(f"Updated {vendor.store_name}: {vendor.subscription_tier} (Score: {vendor.priority_score})")
        
        self.stdout.write(self.style.SUCCESS('Successfully updated vendor priorities'))
