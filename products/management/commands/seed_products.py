from django.core.management.base import BaseCommand
from django.utils.text import slugify
from django.utils import timezone
from accounts.models import User
from products.models import Category, Brand, Product, ProductImage, ProductVariant, ProductReview, ProductQnA
import random

class Command(BaseCommand):
    help = 'Generate 50+ sample tech products with complete data'

    def handle(self, *args, **kwargs):
        # Create or get vendor
        vendor, _ = User.objects.get_or_create(
            username='tech_vendor',
            defaults={
                'email': 'tech@arolana.com',
                'user_type': 'vendor',
                'is_active': True
            }
        )
        if not vendor.password:
            vendor.set_password('vendor123')
            vendor.save()
        
        # Create demo user for reviews
        demo_user, _ = User.objects.get_or_create(
            username='demo_user',
            defaults={
                'email': 'demo@arolana.com',
                'user_type': 'customer',
                'is_active': True
            }
        )
        if not demo_user.password:
            demo_user.set_password('demo123')
            demo_user.save()

        # Categories
        categories_data = [
            ('Smartphones', 'mobile-alt'),
            ('Laptops', 'laptop'),
            ('Headphones', 'headphones'),
            ('Cameras', 'camera'),
            ('Smartwatches', 'clock'),
            ('Gaming', 'gamepad'),
            ('Tablets', 'tablet-alt'),
            ('Audio', 'music'),
        ]

        categories = {}
        for cat_name, icon in categories_data:
            category, _ = Category.objects.get_or_create(
                name=cat_name,
                defaults={'slug': slugify(cat_name), 'icon': icon, 'is_active': True}
            )
            categories[cat_name] = category
            self.stdout.write(f"✅ Category: {cat_name}")

        # Brands
        brands_data = ['Apple', 'Samsung', 'Google', 'Sony', 'Bose', 'Canon', 'Nikon', 'Dell', 'HP', 'Lenovo', 'Microsoft', 'JBL']
        brands = {}
        for brand_name in brands_data:
            brand, _ = Brand.objects.get_or_create(
                name=brand_name,
                defaults={'slug': slugify(brand_name), 'is_active': True}
            )
            brands[brand_name] = brand

        # Product templates
        product_templates = [
            {'name': 'iPhone 15 Pro Max', 'category': 'Smartphones', 'brand': 'Apple', 'price': 1199, 'compare_price': 1299, 'stock': 50},
            {'name': 'Samsung Galaxy S24 Ultra', 'category': 'Smartphones', 'brand': 'Samsung', 'price': 1299, 'compare_price': 1399, 'stock': 45},
            {'name': 'Google Pixel 8 Pro', 'category': 'Smartphones', 'brand': 'Google', 'price': 999, 'compare_price': 1099, 'stock': 40},
            {'name': 'MacBook Pro 16"', 'category': 'Laptops', 'brand': 'Apple', 'price': 3499, 'compare_price': 3799, 'stock': 30},
            {'name': 'Dell XPS 15', 'category': 'Laptops', 'brand': 'Dell', 'price': 2499, 'compare_price': 2699, 'stock': 35},
            {'name': 'HP Spectre x360', 'category': 'Laptops', 'brand': 'HP', 'price': 1899, 'compare_price': 2099, 'stock': 40},
            {'name': 'Lenovo ThinkPad X1', 'category': 'Laptops', 'brand': 'Lenovo', 'price': 2199, 'compare_price': 2399, 'stock': 25},
            {'name': 'Sony WH-1000XM5', 'category': 'Headphones', 'brand': 'Sony', 'price': 399, 'compare_price': 449, 'stock': 120},
            {'name': 'Bose QC Ultra', 'category': 'Headphones', 'brand': 'Bose', 'price': 429, 'compare_price': 499, 'stock': 100},
            {'name': 'Apple AirPods Max', 'category': 'Headphones', 'brand': 'Apple', 'price': 549, 'stock': 80},
            {'name': 'Canon EOS R5', 'category': 'Cameras', 'brand': 'Canon', 'price': 3899, 'compare_price': 4299, 'stock': 25},
            {'name': 'Sony A7 IV', 'category': 'Cameras', 'brand': 'Sony', 'price': 2499, 'stock': 35},
            {'name': 'Nikon Z8', 'category': 'Cameras', 'brand': 'Nikon', 'price': 3999, 'compare_price': 4499, 'stock': 20},
            {'name': 'Apple Watch Ultra 2', 'category': 'Smartwatches', 'brand': 'Apple', 'price': 799, 'compare_price': 899, 'stock': 60},
            {'name': 'Samsung Watch 6 Classic', 'category': 'Smartwatches', 'brand': 'Samsung', 'price': 399, 'compare_price': 449, 'stock': 80},
            {'name': 'PlayStation 5', 'category': 'Gaming', 'brand': 'Sony', 'price': 499, 'stock': 100},
            {'name': 'Xbox Series X', 'category': 'Gaming', 'brand': 'Microsoft', 'price': 499, 'stock': 90},
            {'name': 'Nintendo Switch OLED', 'category': 'Gaming', 'brand': 'Nintendo', 'price': 349, 'stock': 120},
            {'name': 'iPad Pro 12.9"', 'category': 'Tablets', 'brand': 'Apple', 'price': 1099, 'compare_price': 1199, 'stock': 55},
            {'name': 'Samsung Tab S9 Ultra', 'category': 'Tablets', 'brand': 'Samsung', 'price': 1199, 'compare_price': 1299, 'stock': 40},
            {'name': 'Microsoft Surface Pro 9', 'category': 'Tablets', 'brand': 'Microsoft', 'price': 1299, 'stock': 35},
            {'name': 'Sonos Era 300', 'category': 'Audio', 'brand': 'Sonos', 'price': 449, 'stock': 70},
            {'name': 'JBL Boombox 3', 'category': 'Audio', 'brand': 'JBL', 'price': 499, 'compare_price': 549, 'stock': 65},
            {'name': 'Bose SoundLink Max', 'category': 'Audio', 'brand': 'Bose', 'price': 399, 'stock': 85},
        ]

        products_created = 0
        for template in product_templates:
            category = categories.get(template['category'])
            brand = brands.get(template['brand'])
            
            if not category or not brand:
                continue
            
            # Create unique slug
            base_slug = slugify(template['name'])
            slug = base_slug
            counter = 1
            while Product.objects.filter(slug=slug).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            
            # Create product
            product = Product.objects.create(
                sku=f"ARO-{template['brand'][:3].upper()}{random.randint(1000, 9999)}",
                name=template['name'],
                slug=slug,
                description=f"""
                <h2>Premium {template['name']}</h2>
                <p>Experience the best in class technology with outstanding performance and premium build quality.</p>
                <h3>Key Features</h3>
                <ul>
                    <li>Latest generation processor</li>
                    <li>High-resolution display</li>
                    <li>Long battery life</li>
                    <li>Premium build quality</li>
                    <li>Advanced connectivity options</li>
                </ul>
                """,
                specifications='{"Processor": "Latest Gen", "Display": "High Resolution", "Memory": "16GB RAM", "Storage": "512GB SSD"}',
                category=category,
                brand=brand,
                vendor=vendor,
                price=template['price'],
                compare_price=template.get('compare_price'),
                stock_quantity=template['stock'],
                is_featured=products_created < 10,
                is_new=products_created < 20,
                is_active=True
            )
            
            products_created += 1
            self.stdout.write(f"✅ Created: {product.name} (slug: {product.slug})")
            
            # Add a single review
            ProductReview.objects.get_or_create(
                product=product,
                user=demo_user,
                defaults={
                    'rating': random.randint(4, 5),
                    'title': "Excellent product!",
                    'review': f"I've been using the {template['name']} for a while now and it's absolutely fantastic. Highly recommended!",
                    'is_active': True
                }
            )
            
            # Add a Q&A
            ProductQnA.objects.get_or_create(
                product=product,
                user=demo_user,
                defaults={'question': "Does this come with warranty?", 'is_active': True}
            )
            
            # Add variants
            ProductVariant.objects.get_or_create(
                product=product,
                variant_type='color',
                name='Color',
                value='Standard',
                defaults={'price_adjustment': 0, 'stock_quantity': template['stock'], 'is_active': True}
            )

        self.stdout.write(self.style.SUCCESS(f"\n🎉 Successfully created {products_created} products!"))
        self.stdout.write(self.style.SUCCESS(f"📊 Statistics:"))
        self.stdout.write(f"   - Categories: {Category.objects.count()}")
        self.stdout.write(f"   - Brands: {Brand.objects.count()}")
        self.stdout.write(f"   - Products: {Product.objects.count()}")
        self.stdout.write(f"   - Reviews: {ProductReview.objects.count()}")
        self.stdout.write(f"   - Q&A: {ProductQnA.objects.count()}")
