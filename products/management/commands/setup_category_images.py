from django.core.management.base import BaseCommand
from django.core.files import File
from io import BytesIO
import requests
from products.models import Category


class Command(BaseCommand):
    help = 'Setup default category images from Unsplash'
    
    def handle(self, *args, **kwargs):
        # Category image URLs (high-quality Unsplash images)
        category_images = {
            'electronics': 'https://images.unsplash.com/photo-1498049794561-7780e7231661?w=800&h=800&fit=crop',
            'cameras': 'https://images.unsplash.com/photo-1502920917128-1aa500764cbd?w=800&h=800&fit=crop',
            'audio': 'https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=800&h=800&fit=crop',
            'laptops': 'https://images.unsplash.com/photo-1496181133206-80ce9b88a853?w=800&h=800&fit=crop',
            'accessories': 'https://images.unsplash.com/photo-1484704849700-f032a568e944?w=800&h=800&fit=crop',
            'phones': 'https://images.unsplash.com/photo-1511707171634-5f897ff02aa9?w=800&h=800&fit=crop',
            'gaming': 'https://images.unsplash.com/photo-1593305841991-05c297ba4575?w=800&h=800&fit=crop',
            'watches': 'https://images.unsplash.com/photo-1523275335684-37898b6baf30?w=800&h=800&fit=crop',
            'headphones': 'https://images.unsplash.com/photo-1583394838336-acd977736f90?w=800&h=800&fit=crop',
            'smart-home': 'https://images.unsplash.com/photo-1558089687-f282ffcbc126?w=800&h=800&fit=crop',
        }
        
        # Get or create categories
        categories_data = [
            {'name': 'Electronics', 'slug': 'electronics', 'icon': 'microchip'},
            {'name': 'Cameras', 'slug': 'cameras', 'icon': 'camera'},
            {'name': 'Audio', 'slug': 'audio', 'icon': 'headphones'},
            {'name': 'Laptops', 'slug': 'laptops', 'icon': 'laptop'},
            {'name': 'Accessories', 'slug': 'accessories', 'icon': 'keyboard'},
            {'name': 'Smartphones', 'slug': 'phones', 'icon': 'mobile-alt'},
            {'name': 'Gaming', 'slug': 'gaming', 'icon': 'gamepad'},
            {'name': 'Smart Home', 'slug': 'smart-home', 'icon': 'home'},
        ]
        
        for cat_data in categories_data:
            try:
                category, created = Category.objects.get_or_create(
                    slug=cat_data['slug'],
                    defaults={
                        'name': cat_data['name'],
                        'icon': cat_data['icon'],
                        'order': 0,
                        'is_active': True
                    }
                )
                
                if created:
                    self.stdout.write(self.style.SUCCESS(f'✅ Created category: {category.name}'))
                else:
                    self.stdout.write(self.style.WARNING(f'ℹ️ Category already exists: {category.name}'))
                
                # Set icon if not set
                if not category.icon:
                    category.icon = cat_data['icon']
                    category.save(update_fields=['icon'])
                
                # Try to download and set image
                if not category.image and category.slug in category_images:
                    try:
                        response = requests.get(category_images[category.slug], timeout=10)
                        if response.status_code == 200:
                            img_name = f"{category.slug}.jpg"
                            img_temp = BytesIO(response.content)
                            img_temp.seek(0)
                            category.image.save(img_name, File(img_temp), save=True)
                            self.stdout.write(self.style.SUCCESS(f'  📸 Added image for {category.name}'))
                    except Exception as e:
                        self.stdout.write(self.style.WARNING(f'  ⚠️ Could not download image for {category.name}: {e}'))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'❌ Error processing {cat_data["name"]}: {e}'))
        
        self.stdout.write(self.style.SUCCESS('\n🎉 Category setup complete!'))
