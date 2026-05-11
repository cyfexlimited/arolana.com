import os
import django
from datetime import timedelta

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'arolana_config.settings')
django.setup()

from ads.models import AdCampaign, AdBanner, AdPlacement, Advertisement
from django.utils import timezone

print("=" * 60)
print("ADDING TEST AD CAMPAIGNS")
print("=" * 60)

# Create placements
placements_data = [
    {'name': 'Sidebar', 'slug': 'sidebar', 'placement_type': 'sidebar', 'width': 300, 'height': 250},
    {'name': 'Homepage Banner', 'slug': 'banner', 'placement_type': 'banner', 'width': 728, 'height': 90},
    {'name': 'Footer', 'slug': 'footer', 'placement_type': 'footer', 'width': 728, 'height': 90},
]

for p in placements_data:
    obj, created = AdPlacement.objects.get_or_create(slug=p['slug'], defaults=p)
    print(f"{'Created' if created else 'Exists'} placement: {obj.name}")

print("\n" + "-" * 60)

# Create campaigns
campaigns = [
    {
        'name': 'Summer Sale Campaign',
        'campaign_type': 'display',
        'budget_type': 'total',
        'total_budget': 1000.00,
        'max_bid': 0.75,
        'targeting': 'all',
        'status': 'active',
        'approved': True,
        'end_date': timezone.now() + timedelta(days=30)
    },
    {
        'name': 'Black Friday Campaign',
        'campaign_type': 'cpc',
        'budget_type': 'daily',
        'daily_budget': 50.00,
        'total_budget': 1500.00,
        'max_bid': 1.25,
        'targeting': 'all',
        'status': 'active',
        'approved': True,
        'end_date': timezone.now() + timedelta(days=45)
    },
    {
        'name': 'New User Campaign',
        'campaign_type': 'cpa',
        'budget_type': 'total',
        'total_budget': 500.00,
        'max_bid': 2.00,
        'targeting': 'new',
        'status': 'active',
        'approved': True,
        'end_date': timezone.now() + timedelta(days=60)
    },
]

for data in campaigns:
    obj, created = AdCampaign.objects.get_or_create(name=data['name'], defaults=data)
    print(f"{'Created' if created else 'Exists'} campaign: {obj.name} (ID: {obj.campaign_id})")

print("\n" + "-" * 60)

# Create simple advertisements
ads_data = [
    {
        'title': 'Summer Sale Special',
        'description': 'Get up to 50% off on all summer items! Limited time offer.',
        'button_text': 'Shop Sale',
        'url': '/products/summer-sale/',
        'placement': 'sidebar',
        'is_featured': True
    },
    {
        'title': 'Free Shipping',
        'description': 'Free shipping on orders over $50. Shop now!',
        'button_text': 'Learn More',
        'url': '/shipping/',
        'placement': 'sidebar',
        'is_featured': False
    },
    {
        'title': 'Welcome Offer',
        'description': 'New customers get 20% off first order',
        'button_text': 'Sign Up',
        'url': '/accounts/register/',
        'placement': 'sidebar',
        'is_featured': False
    },
]

for data in ads_data:
    obj, created = Advertisement.objects.get_or_create(
        title=data['title'],
        placement=data['placement'],
        defaults={
            'description': data['description'],
            'button_text': data['button_text'],
            'url': data['url'],
            'is_featured': data['is_featured'],
            'is_active': True,
            'end_date': timezone.now() + timedelta(days=30)
        }
    )
    print(f"{'Created' if created else 'Exists'} ad: {obj.title}")

print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)
print(f"Total Campaigns: {AdCampaign.objects.count()}")
print(f"Total Placements: {AdPlacement.objects.count()}")
print(f"Total Advertisements: {Advertisement.objects.filter(is_active=True).count()}")
print("\nTest data added successfully!")
print("Go to: http://127.0.0.1:8000/admin/ads/ to view")
