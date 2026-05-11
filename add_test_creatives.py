import os
import django
import json
from datetime import timedelta

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'arolana_config.settings')
django.setup()

from ads.models import AdCampaign, AdCreative, AdBanner
from django.utils import timezone
from django.core.files.base import ContentFile
from PIL import Image, ImageDraw
from io import BytesIO
import random

# Ensure we have campaigns first
campaigns = AdCampaign.objects.filter(status='active')
if not campaigns.exists():
    print("⚠️ No active campaigns found. Creating a test campaign first...")
    
    campaign = AdCampaign.objects.create(
        name='Test Campaign for Creatives',
        campaign_type='display',
        budget_type='total',
        total_budget=1000.00,
        max_bid=0.75,
        targeting='all',
        status='active',
        approved=True,
        start_date=timezone.now(),
        end_date=timezone.now() + timedelta(days=30)
    )
    print(f"✅ Created test campaign: {campaign.name}")
    campaigns = [campaign]

def create_test_image(width, height, text, bg_color):
    """Create a test image for creatives"""
    img = Image.new('RGB', (width, height), color=bg_color)
    draw = ImageDraw.Draw(img)
    
    # Add text
    bbox = draw.textbbox((0, 0), text)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    x = (width - text_width) // 2
    y = (height - text_height) // 2
    
    draw.text((x, y), text, fill=(255, 255, 255))
    
    # Save to buffer
    buffer = BytesIO()
    img.save(buffer, format='JPEG', quality=85)
    buffer.seek(0)
    return ContentFile(buffer.read(), name=f'creative_{text[:10]}.jpg')

# Create different types of creatives
creatives_data = [
    {
        'name': 'Summer Sale Banner - Large',
        'creative_type': 'image',
        'headline': '☀️ Summer Sale! Up to 50% Off',
        'description': 'Shop the hottest summer deals. Limited time offer!',
        'cta_text': 'Shop Summer Sale →',
        'clickthrough_url': '/products/summer-sale/',
        'ab_variant': 'A',
        'ab_weight': 70,
    },
    {
        'name': 'Summer Sale Banner - Variant B',
        'creative_type': 'image',
        'headline': '🔥 Flash Sale! Extra 20% Off',
        'description': 'Use code FLASH20 at checkout',
        'cta_text': 'Get Discount →',
        'clickthrough_url': '/products/summer-sale/?code=FLASH20',
        'ab_variant': 'B',
        'ab_weight': 30,
    },
    {
        'name': 'Free Shipping Promo',
        'creative_type': 'image',
        'headline': '🚚 Free Shipping Worldwide',
        'description': 'On orders over $50. No code needed!',
        'cta_text': 'Start Shopping →',
        'clickthrough_url': '/shipping/',
        'ab_variant': 'A',
        'ab_weight': 100,
    },
    {
        'name': 'Membership Offer',
        'creative_type': 'image',
        'headline': '💎 VIP Membership',
        'description': 'Get exclusive perks and early access to sales',
        'cta_text': 'Join VIP →',
        'clickthrough_url': '/subscriptions/',
        'ab_variant': '',
        'ab_weight': 100,
    },
    {
        'name': 'Video Ad - Product Showcase',
        'creative_type': 'video',
        'headline': 'Watch Our Latest Collection',
        'description': 'See our new arrivals in action',
        'cta_text': 'Watch Now →',
        'clickthrough_url': '/products/new/',
        'video_url': 'https://www.youtube.com/watch?v=example',
        'ab_variant': '',
        'ab_weight': 100,
    },
    {
        'name': 'Native Ad - Blog Post',
        'creative_type': 'native',
        'headline': '10 Tips for Better Shopping',
        'description': 'Learn from our experts',
        'cta_text': 'Read Article →',
        'clickthrough_url': '/blog/shopping-tips/',
        'ab_variant': '',
        'ab_weight': 100,
    },
    {
        'name': 'Carousel Ad - Product Gallery',
        'creative_type': 'carousel',
        'headline': 'Trending Products',
        'description': 'Browse our best sellers',
        'cta_text': 'View Collection →',
        'clickthrough_url': '/products/trending/',
        'carousel_items': json.dumps([
            {'image': '/media/products/product1.jpg', 'title': 'Product 1', 'price': '$99'},
            {'image': '/media/products/product2.jpg', 'title': 'Product 2', 'price': '$149'},
            {'image': '/media/products/product3.jpg', 'title': 'Product 3', 'price': '$199'},
        ]),
        'ab_variant': '',
        'ab_weight': 100,
    },
]

print("\n📢 Creating Ad Creatives...")
print("="*50)

created_count = 0
existing_count = 0

for campaign in campaigns:
    for data in creatives_data:
        # Check if creative already exists
        creative, created = AdCreative.objects.get_or_create(
            campaign=campaign,
            name=data['name'],
            defaults={
                'creative_type': data['creative_type'],
                'headline': data['headline'],
                'description': data.get('description', ''),
                'cta_text': data.get('cta_text', 'Learn More'),
                'clickthrough_url': data['clickthrough_url'],
                'ab_variant': data.get('ab_variant', ''),
                'ab_weight': data.get('ab_weight', 100),
                'is_active': True,
            }
        )
        
        if created:
            created_count += 1
            print(f"\n✅ Created Creative: {creative.name}")
            print(f"   - Type: {creative.creative_type}")
            print(f"   - Campaign: {campaign.name}")
            print(f"   - Headline: {creative.headline}")
            
            # Add image for image creatives
            if creative.creative_type == 'image' and not creative.image:
                try:
                    # Create a test image
                    if 'Summer' in creative.name:
                        img_file = create_test_image(728, 90, "SUMMER SALE!", (255, 100, 100))
                    elif 'Free Shipping' in creative.name:
                        img_file = create_test_image(300, 250, "FREE SHIPPING!", (100, 150, 255))
                    elif 'Membership' in creative.name:
                        img_file = create_test_image(300, 250, "VIP MEMBERSHIP", (156, 0, 156))
                    else:
                        img_file = create_test_image(728, 90, creative.headline[:20], (59, 130, 246))
                    
                    creative.image.save(creative.name.replace(' ', '_').lower() + '.jpg', img_file, save=True)
                    print(f"   📸 Added image to creative")
                    
                except Exception as e:
                    print(f"   ⚠️ Could not add image: {e}")
            
            # Add mobile image
            if creative.creative_type == 'image' and not creative.image_mobile:
                try:
                    img_file = create_test_image(300, 250, creative.headline[:15], (59, 130, 246))
                    creative.image_mobile.save(creative.name.replace(' ', '_').lower() + '_mobile.jpg', img_file, save=True)
                    print(f"   📱 Added mobile image")
                except:
                    pass
                    
        else:
            existing_count += 1

print("\n" + "="*50)
print("📊 CREATIVES SUMMARY")
print("="*50)
print(f"✅ New Creatives Created: {created_count}")
print(f"⚠️ Existing Creatives: {existing_count}")
print(f"📈 Total Creatives: {AdCreative.objects.count()}")

# Display detailed stats
print("\n📊 Detailed Creative Statistics:")
print("-"*50)
for creative_type in ['image', 'video', 'native', 'carousel']:
    count = AdCreative.objects.filter(creative_type=creative_type, is_active=True).count()
    print(f"   {creative_type.title()}: {count} active creatives")

# Create banner - creative relationships
print("\n🔗 Linking Creatives to Banners...")
print("-"*50)

for banner in AdBanner.objects.filter(is_active=True)[:5]:
    # Get a random creative
    creative = AdCreative.objects.filter(is_active=True).first()
    if creative:
        banner.creative = creative
        banner.save()
        print(f"   ✅ Linked creative '{creative.name}' to banner '{banner.title}'")

# Update creative performance metrics
print("\n📈 Updating Performance Metrics...")
print("-"*50)

for creative in AdCreative.objects.all():
    # Generate random performance data for testing
    creative.impressions = random.randint(100, 10000)
    creative.clicks = random.randint(10, int(creative.impressions * 0.1))
    creative.ctr = (creative.clicks / creative.impressions * 100) if creative.impressions > 0 else 0
    creative.save()
    
    if creative.impressions > 0:
        print(f"   📊 {creative.name}: {creative.impressions:,} impressions, {creative.clicks:,} clicks ({creative.ctr:.2f}% CTR)")

print("\n" + "="*50)
print("✅ TEST CREATIVES COMPLETE!")
print("="*50)
print("\n🔗 Admin Links:")
print("   - View all creatives: http://127.0.0.1:8000/admin/ads/adcreative/")
print("   - Add new creative: http://127.0.0.1:8000/admin/ads/adcreative/add/")
print("   - View campaigns: http://127.0.0.1:8000/admin/ads/adcampaign/")
print("   - View banners: http://127.0.0.1:8000/admin/ads/adbanner/")
