import os
import django
import sys

# Setup Django environment
sys.path.append('/Users/noble/arolana')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'arolana_config.settings')
django.setup()

from products.models import Category
from django.core.files.base import ContentFile
import requests
from io import BytesIO

print("=" * 60)
print("FIXING CATEGORY IMAGES")
print("=" * 60)

# High-quality professional category images from Unsplash
category_image_urls = {
    'accessories': 'https://images.unsplash.com/photo-1484704849700-f032a568e944?w=500&h=500&fit=crop',
    'audio': 'https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=500&h=500&fit=crop',
    'cameras': 'https://images.unsplash.com/photo-1502920917128-1aa500764cbd?w=500&h=500&fit=crop',
    'electronics': 'https://images.unsplash.com/photo-1498049794561-7780e7231661?w=500&h=500&fit=crop',
    'gaming': 'https://images.unsplash.com/photo-1593305841991-05c297ba4575?w=500&h=500&fit=crop',
    'laptops': 'https://images.unsplash.com/photo-1531297484001-80022131f5a1?w=500&h=500&fit=crop',
    'smart-home': 'https://images.unsplash.com/photo-1558002038-1055907df827?w=500&h=500&fit=crop',
    'smartphones': 'https://images.unsplash.com/photo-1511707171634-5f897ff02aa9?w=500&h=500&fit=crop',
    'tablets': 'https://images.unsplash.com/photo-1561154464-82e9adf32764?w=500&h=500&fit=crop',
    'wearables': 'https://images.unsplash.com/photo-1579586337278-3befd40fd17a?w=500&h=500&fit=crop',
}

for slug, image_url in category_image_urls.items():
    try:
        category = Category.objects.get(slug=slug)
        print(f"\n📁 Processing: {category.name}")
        
        # Download image
        response = requests.get(image_url, timeout=15)
        
        if response.status_code == 200:
            # Save image to category
            image_content = ContentFile(response.content)
            filename = f"{slug}.jpg"
            
            # Delete old image if exists
            if category.image:
                category.image.delete(save=False)
            
            # Save new image
            category.image.save(filename, image_content, save=True)
            print(f"   ✅ Successfully added image for {category.name}")
        else:
            print(f"   ❌ Failed to download (HTTP {response.status_code})")
            
    except Category.DoesNotExist:
        print(f"⚠️ Category {slug} not found")
    except Exception as e:
        print(f"❌ Error for {slug}: {str(e)}")

print("\n" + "=" * 60)
print("🎉 Category images updated successfully!")
print("=" * 60)

# Verify the updates
print("\n📊 Updated Categories:")
categories = Category.objects.filter(slug__in=category_image_urls.keys())
for category in categories:
    has_image = "✅" if category.image else "❌"
    print(f"   {has_image} {category.name}: {category.image.url if category.image else 'No image'}")
