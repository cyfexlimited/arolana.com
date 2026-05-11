import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'arolana_config.settings')
django.setup()

from ads.models import AdPlacement, AdCampaign, AdBanner

# Create placements
placements = [
    {'slug': 'sidebar', 'name': 'Sidebar Banner', 'width': 300, 'height': 250},
    {'slug': 'footer', 'name': 'Footer Banner', 'width': 728, 'height': 90},
    {'slug': 'homepage', 'name': 'Homepage Banner', 'width': 1200, 'height': 400},
]

for p in placements:
    obj, created = AdPlacement.objects.get_or_create(slug=p['slug'], defaults=p)
    print(f"{'Created' if created else 'Found'}: {obj.name}")

# Create campaign
campaign, created = AdCampaign.objects.get_or_create(
    name='Welcome Campaign',
    defaults={
        'campaign_type': 'display',
        'budget': 1000.00,
        'cost_per_click': 0.50,
        'cost_per_impression': 0.01,
        'status': 'active',
        'approved': True,
        'sponsor_name': 'Arolana'
    }
)
print(f"{'Created' if createdprint(f"{'Created' if createdpriaiprint(f}")print(f"{' bannprint(f"{'Created' if createdprint(f"{'Created' if createdpriaiprint(f}")Baprint(f"{'Creget_or_create(
    title='Special Offer!',
    campaign=campa    campaign=campa=s    campaign=ef    campaign=campa    campaign=campa=s    campaign=ef    campaign=campa    camcta_text': 'Shop Now',
        'cta_url': '/products/',
        'priority': 1,
        'priority': 1,
oducts/',
mpa=s    campaign=ef    campaign=campa    campainner mpa=s    campae}")

print("\n✅ Ads data created successfully!")
