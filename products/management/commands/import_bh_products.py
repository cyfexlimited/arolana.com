import requests
from django.core.management.base import BaseCommand
from django.core.files.base import ContentFile
from products.models import Product, Category, Brand
from accounts.models import User
from decimal import Decimal
import json
import random
from io import BytesIO

class Command(BaseCommand):
    help = 'Import 50 test products from B&H Photo categories'

    def handle(self, *args, **options):
        self.stdout.write('🚀 Starting B&H Product Import...')
        
        # Get or create vendor
        vendor, created = User.objects.get_or_create(
            username='bh_vendor',
            defaults={
                'email': 'bh@arolana.com',
                'user_type': 'vendor',
                'is_active': True
            }
        )
        if created:
            vendor.set_password('vendor123')
            vendor.save()
            self.stdout.write('✅ Created B&H vendor')
        
        # Create categories
        categories_data = {
            'phones': {'name': 'Smartphones', 'slug': 'smartphones'},
            'tablets': {'name': 'Tablets', 'slug': 'tablets'},
            'accessories': {'name': 'Accessories', 'slug': 'accessories'},
            'wearables': {'name': 'Wearables', 'slug': 'wearables'},
            'audio': {'name': 'Audio', 'slug': 'audio'},
        }
        
        categories = {}
        for key, data in categories_data.items():
            cat, created = Category.objects.get_or_create(
                slug=data['slug'],
                defaults={
                    'name': data['name'],
                    'is_active': True
                }
            )
            categories[key] = cat
            self.stdout.write(f'  {"✅ Created" if created else "📌 Found"} category: {cat.name}')
        
        # Create brands
        brand_names = ['Apple', 'Samsung', 'Google', 'OnePlus', 'Xiaomi', 'Sony', 'Bose', 'JBL']
        brands = {}
        for name in brand_names:
            brand, created = Brand.objects.get_or_create(
                name=name,
                slug=name.lower(),
                defaults={'is_active': True}
            )
            brands[name] = brand
        
        # Generate 50 sample phone products
        phone_models = [
            # Apple iPhones
            {'name': 'Apple iPhone 15 Pro Max', 'brand': 'Apple', 'price': 1199, 'compare': 1299, 'stock': 50},
            {'name': 'Apple iPhone 15 Pro', 'brand': 'Apple', 'price': 999, 'compare': 1099, 'stock': 45},
            {'name': 'Apple iPhone 15 Plus', 'brand': 'Apple', 'price': 899, 'compare': 999, 'stock': 60},
            {'name': 'Apple iPhone 15', 'brand': 'Apple', 'price': 799, 'compare': 899, 'stock': 70},
            {'name': 'Apple iPhone 14 Pro Max', 'brand': 'Apple', 'price': 1099, 'compare': 1199, 'stock': 40},
            {'name': 'Apple iPhone 14 Pro', 'brand': 'Apple', 'price': 999, 'compare': 1099, 'stock': 55},
            {'name': 'Apple iPhone 14', 'brand': 'Apple', 'price': 699, 'compare': 799, 'stock': 80},
            {'name': 'Apple iPhone SE (3rd Gen)', 'brand': 'Apple', 'price': 429, 'compare': 479, 'stock': 100},
            
            # Samsung Galaxy
            {'name': 'Samsung Galaxy S24 Ultra', 'brand': 'Samsung', 'price': 1299, 'compare': 1399, 'stock': 35},
            {'name': 'Samsung Galaxy S24 Plus', 'brand': 'Samsung', 'price': 1099, 'compare': 1199, 'stock': 40},
            {'name': 'Samsung Galaxy S24', 'brand': 'Samsung', 'price': 799, 'compare': 899, 'stock': 50},
            {'name': 'Samsung Galaxy Z Fold 5', 'brand': 'Samsung', 'price': 1799, 'compare': 1899, 'stock': 25},
            {'name': 'Samsung Galaxy Z Flip 5', 'brand': 'Samsung', 'price': 999, 'compare': 1099, 'stock': 30},
            {'name': 'Samsung Galaxy S23 Ultra', 'brand': 'Samsung', 'price': 1199, 'compare': 1299, 'stock': 45},
            {'name': 'Samsung Galaxy A54 5G', 'brand': 'Samsung', 'price': 449, 'compare': 499, 'stock': 120},
            
            # Google Pixel
            {'name': 'Google Pixel 8 Pro', 'brand': 'Google', 'price': 999, 'compare': 1099, 'stock': 40},
            {'name': 'Google Pixel 8', 'brand': 'Google', 'price': 699, 'compare': 799, 'stock': 55},
            {'name': 'Google Pixel 7a', 'brand': 'Google', 'price': 499, 'compare': 549, 'stock': 70},
            {'name': 'Google Pixel Fold', 'brand': 'Google', 'price': 1799, 'compare': 1899, 'stock': 20},
            
            # OnePlus
            {'name': 'OnePlus 12', 'brand': 'OnePlus', 'price': 799, 'compare': 899, 'stock': 45},
            {'name': 'OnePlus 12R', 'brand': 'OnePlus', 'price': 599, 'compare': 699, 'stock': 55},
            {'name': 'OnePlus Open', 'brand': 'OnePlus', 'price': 1699, 'compare': 1799, 'stock': 25},
            
            # Xiaomi
            {'name': 'Xiaomi 13 Pro', 'brand': 'Xiaomi', 'price': 999, 'compare': 1099, 'stock': 40},
            {'name': 'Xiaomi 13T Pro', 'brand': 'Xiaomi', 'price': 699, 'compare': 799, 'stock': 50},
            {'name': 'Xiaomi Redmi Note 13 Pro', 'brand': 'Xiaomi', 'price': 399, 'compare': 449, 'stock': 100},
            
            # Sony
            {'name': 'Sony Xperia 1 V', 'brand': 'Sony', 'price': 1399, 'compare': 1499, 'stock': 30},
            {'name': 'Sony Xperia 5 V', 'brand': 'Sony', 'price': 999, 'compare': 1099, 'stock': 35},
            
            # More Samsung
            {'name': 'Samsung Galaxy A15 5G', 'brand': 'Samsung', 'price': 199, 'compare': 249, 'stock': 150},
            {'name': 'Samsung Galaxy A25 5G', 'brand': 'Samsung', 'price': 299, 'compare': 349, 'stock': 130},
            {'name': 'Samsung Galaxy Tab S9 Ultra', 'brand': 'Samsung', 'price': 1199, 'compare': 1299, 'stock': 30, 'category': 'tablets'},
            
            # More Apple
            {'name': 'Apple iPad Pro 12.9"', 'brand': 'Apple', 'price': 1099, 'compare': 1199, 'stock': 40, 'category': 'tablets'},
            {'name': 'Apple iPad Air', 'brand': 'Apple', 'price': 599, 'compare': 649, 'stock': 60, 'category': 'tablets'},
            {'name': 'Apple iPad 10th Gen', 'brand': 'Apple', 'price': 449, 'compare': 499, 'stock': 80, 'category': 'tablets'},
            {'name': 'Apple Watch Ultra 2', 'brand': 'Apple', 'price': 799, 'compare': 849, 'stock': 35, 'category': 'wearables'},
            {'name': 'Apple Watch Series 9', 'brand': 'Apple', 'price': 399, 'compare': 429, 'stock': 60, 'category': 'wearables'},
            {'name': 'Samsung Galaxy Watch 6 Classic', 'brand': 'Samsung', 'price': 399, 'compare': 449, 'stock': 45, 'category': 'wearables'},
            {'name': 'Google Pixel Watch 2', 'brand': 'Google', 'price': 349, 'compare': 399, 'stock': 50, 'category': 'wearables'},
            
            # Audio products
            {'name': 'Apple AirPods Pro 2', 'brand': 'Apple', 'price': 249, 'compare': 279, 'stock': 120, 'category': 'audio'},
            {'name': 'Samsung Galaxy Buds2 Pro', 'brand': 'Samsung', 'price': 229, 'compare': 249, 'stock': 100, 'category': 'audio'},
            {'name': 'Google Pixel Buds Pro', 'brand': 'Google', 'price': 199, 'compare': 219, 'stock': 90, 'category': 'audio'},
            {'name': 'Sony WF-1000XM5', 'brand': 'Sony', 'price': 299, 'compare': 329, 'stock': 80, 'category': 'audio'},
            {'name': 'Bose QuietComfort Ultra', 'brand': 'Bose', 'price': 429, 'compare': 479, 'stock': 60, 'category': 'audio'},
            {'name': 'JBL Tour Pro 2', 'brand': 'JBL', 'price': 249, 'compare': 279, 'stock': 70, 'category': 'audio'},
            
            # Accessories
            {'name': 'Apple MagSafe Charger', 'brand': 'Apple', 'price': 39, 'compare': 49, 'stock': 200, 'category': 'accessories'},
            {'name': 'Samsung Wireless Charger Duo', 'brand': 'Samsung', 'price': 79, 'compare': 89, 'stock': 150, 'category': 'accessories'},
            {'name': 'OtterBox Defender Case', 'brand': 'Apple', 'price': 59, 'compare': 69, 'stock': 180, 'category': 'accessories'},
            {'name': 'Spigen Tough Armor Case', 'brand': 'Samsung', 'price': 39, 'compare': 49, 'stock': 200, 'category': 'accessories'},
        ]
        
        # Product images (Unsplash URLs for tech products)
        tech_images = [
            'https://images.unsplash.com/photo-1592899677977-9c10ca588bbd?w=400',  # iPhone
            'https://images.unsplash.com/photo-1610945264803-c22b62d2a7b3?w=400',  # Samsung
            'https://images.unsplash.com/photo-1567581935884-3349723552ca?w=400',  # Pixel
            'https://images.unsplash.com/photo-1585060544812-6b45742d762f?w=400',  # OnePlus
            'https://images.unsplash.com/photo-1616348436168-de43ad0db179?w=400',  # Phone
            'https://images.unsplash.com/photo-1511707171634-5f897ff02aa9?w=400',  # Phone front
            'https://images.unsplash.com/photo-1580910051074-3eb694886505?w=400',  # Phone side
            'https://images.unsplash.com/photo-1589492477829-5e65395b66cc?w=400',  # Tablet
            'https://images.unsplash.com/photo-1546868871-7041f2a55e12?w=400',  # Watch
            'https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=400',  # Headphones
        ]
        
        products_created = 0
        products_skipped = 0
        
        for i, phone_data in enumerate(phone_models[:50]):
            category_key = phone_data.get('category', 'phones')
            category = categories[category_key]
            brand = brands.get(phone_data['brand'], brands['Apple'])
            sku = f"BH-{phone_data['brand'][:3]}{phone_data['name'][:10]}{i}".upper().replace(' ', '')
            
            # Check if product already exists
            if Product.objects.filter(sku=sku).exists():
                products_skipped += 1
                continue
            
            # Create product
            product = Product.objects.create(
                sku=sku,
                name=phone_data['name'],
                slug=f"{phone_data['name'].lower().replace(' ', '-')}-{i}",
                description=f"""
                <h3>Product Overview</h3>
                <p>The {phone_data['name']} is a premium device offering cutting-edge technology and exceptional performance.</p>
                
                <h3>Key Features</h3>
                <ul>
                    <li>Latest processor for lightning-fast performance</li>
                    <li>Stunning high-resolution display</li>
                    <li>Advanced camera system for professional photos</li>
                    <li>All-day battery life with fast charging</li>
                    <li>5G connectivity for blazing-fast speeds</li>
                    <li>Premium build quality with durable materials</li>
                </ul>
                
                <h3>Technical Specifications</h3>
                <table border="0" cellpadding="5">
                    <tr><td><strong>Display:</strong></td><td>6.7-inch Super Retina XDR</td></tr>
                    <tr><td><strong>Processor:</strong></td><td>Latest-gen A-series chip</td></tr>
                    <tr><td><strong>RAM:</strong></td><td>8GB</td></tr>
                    <tr><td><strong>Storage:</strong></td><td>128GB / 256GB / 512GB</td></tr>
                    <tr><td><strong>Camera:</strong></td><td>48MP Main + 12MP Ultra Wide + 12MP Telephoto</td></tr>
                    <tr><td><strong>Battery:</strong></td><td>All-day battery life</td></tr>
                    <tr><td><strong>OS:</strong></td><td>Latest version</td></tr>
                    <tr><td><strong>Dimensions:</strong></td><td>160.7 x 77.6 x 7.85 mm</td></tr>
                    <tr><td><strong>Weight:</strong></td><td>240g</td></tr>
                </table>
                
                <h3>What's in the Box</h3>
                <ul>
                    <li>{phone_data['name']} device</li>
                    <li>USB-C charging cable</li>
                    <li>Documentation</li>
                    <li>SIM eject tool</li>
                </ul>
                """,
                specifications=f"""
                <h3>Technical Specifications</h3>
                <ul>
                    <li><strong>Brand:</strong> {phone_data['brand']}</li>
                    <li><strong>Model:</strong> {phone_data['name']}</li>
                    <li><strong>Network:</strong> 5G, 4G LTE</li>
                    <li><strong>SIM:</strong> Dual SIM (Nano-SIM and eSIM)</li>
                    <li><strong>Water Resistance:</strong> IP68 rating</li>
                    <li><strong>Sensors:</strong> Face ID, Accelerometer, Gyro, Proximity, Compass, Barometer</li>
                    <li><strong>Connectivity:</strong> Wi-Fi 6E, Bluetooth 5.3, NFC</li>
                </ul>
                """,
                category=category,
                brand=brand,
                vendor=vendor,
                price=Decimal(phone_data['price']),
                compare_price=Decimal(phone_data['compare']) if phone_data.get('compare') else None,
                stock_quantity=phone_data['stock'],
                is_in_stock=True,
                is_featured=i < 20,  # First 20 are featured
                is_new=i < 15,       # First 15 are new
                is_bestseller=i < 10, # First 10 are bestsellers
                is_active=True
            )
            
            # Try to download and save an image
            try:
                img_url = tech_images[i % len(tech_images)]
                response = requests.get(img_url, timeout=10)
                if response.status_code == 200:
                    img_content = ContentFile(response.content)
                    filename = f"{product.sku}.jpg"
                    product.main_image.save(filename, img_content, save=True)
                    self.stdout.write(f'  ✅ Downloaded image for {product.name}')
                else:
                    self.stdout.write(f'  ⚠️ Failed to download image for {product.name}')
            except Exception as e:
                self.stdout.write(f'  ⚠️ Image download error for {product.name}: {e}')
            
            products_created += 1
            self.stdout.write(f'  ✅ Created product {products_created}: {product.name} (${product.price})')
        
        self.stdout.write(self.style.SUCCESS(f'\n🎉 Import complete!'))
        self.stdout.write(self.style.SUCCESS(f'   ✅ Created: {products_created} products'))
        self.stdout.write(self.style.SUCCESS(f'   ⏭️ Skipped: {products_skipped} products (already exist)'))
        self.stdout.write(f'   📂 Category: Phones, Tablets, Wearables, Audio, Accessories')
        self.stdout.write(f'   🏷️ Brands: Apple, Samsung, Google, OnePlus, Xiaomi, Sony, Bose, JBL')
        
        # Update featured products count
        featured_count = Product.objects.filter(is_featured=True).count()
        new_count = Product.objects.filter(is_new=True).count()
        bestseller_count = Product.objects.filter(is_bestseller=True).count()
        
        self.stdout.write(f'\n📊 Current stats:')
        self.stdout.write(f'   Featured products: {featured_count}')
        self.stdout.write(f'   New products: {new_count}')
        self.stdout.write(f'   Best sellers: {bestseller_count}')