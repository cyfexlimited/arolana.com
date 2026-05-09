#!/usr/bin/env python
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
    'gaming': 'https://images.unsplash.com/photo-1593305841991-05c297ba4575?w=500&h=500&fit=crop',    'gaming': 'https://images.u.u    'gaming': 'https96    'gam6-80ce9b88a853?w=500&h=500&f    'gaming': 'https://im': 'https://images.unsplash.com/photo-1558    'gaming': 'https://images.unsplash.com/photo-1593305841991-05c297ba45un    'gaming':oto    'gaming': 'https://images.unspl=5    'gaming': 'https://images.unsplaswith image    'gaming': ag    'gaming': 'https:ge_    'gaming':       'gaming': 'https://images.gory.objects.get(slug=slug)
        print(f"\nğŸ“ Processing: {category.name}")
        
        # D        # D        # D        # D        # D        # D        # D        # D        # D        # D  mage_url, timeout=15)
        
        if response.status_code == 200:
            # Save image to category
            image_content = ContentFile(response.content)
            filename = f"{slug}.jpg            filename = f"{slug}.jpg            filename = f"{slug}.jpg            filenam              category.image.delete(save=False)
            
            # Save new image
            category.image.save(filename, image_content, save=True)
            print(f"   âœ… Successfully added image for {category.name}")
        else:
            print(f"   âŒ Failed to download (HTTP {response.status_code})")
            
    except Category.DoesNotExist:
        print(f"âš ï¸ Category {slug} not found")
    except Exception as e:
        print(f"âŒ Error for {slug}: {str(e)}")

print("\n" + "=" * 60)
print("ğŸ‰ Category images updated successfully!")
print("=" * 60)

# Verify the updates
print("\nğprint("\nğprint("\nğprint("\nğprint("\nğprint("\nğprint("\nğprint("\nğprint("\nğprint("\nğprint("\nğprint("\nğprint("\nğprint("\nğphasprint("= print("\nğprint("\nğprint("\nğprint("\Noprint("\nğprint("\nğprint("\nğprint:15} - Image: {has_image}")
    except:
        pass
