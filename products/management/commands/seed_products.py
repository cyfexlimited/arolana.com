from django.core.management.base import BaseCommand
from django.utils.text import slugify
from products.models import Product, Category, Brand, ProductImage
from accounts.models import User
from decimal import Decimal
import random
import string


class Command(BaseCommand):
    help = 'Seed database with realistic products (safe to run multiple times)'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Starting product seeding...'))
        
        # Get or create a vendor
        vendor, created = User.objects.get_or_create(
            email='vendor@arolana.com',
            defaults={
                'username': 'vendor_arolana',
                'user_type': 'vendor',
                'is_active': True
            }
        )
        if created:
            vendor.set_password('vendor123')
            vendor.save()
            self.stdout.write(self.style.SUCCESS(f'Created vendor: {vendor.email}'))
        else:
            self.stdout.write(self.style.SUCCESS(f'Vendor already exists: {vendor.email}'))
        
        # Get or create categories
        categories_data = {
            'Electronics': 'electronics',
            'Audio': 'audio',
            'Cameras': 'cameras',
            'Gaming': 'gaming',
            'Laptops': 'laptops',
            'Smart Home': 'smart-home',
            'Smartphones': 'smartphones',
            'Tablets': 'tablets',
            'Wearables': 'wearables',
            'Accessories': 'accessories'
        }
        
        categories = {}
        for name, slug in categories_data.items():
            category, created = Category.objects.get_or_create(
                slug=slug,
                defaults={
                    'name': name,
                    'is_active': True
                }
            )
            categories[name] = category
            if created:
                self.stdout.write(self.style.SUCCESS(f'Created category: {name}'))
        
        # Get or create brands
        brands_data = ['Apple', 'Samsung', 'Sony', 'Bose', 'JBL', 'Google', 'Microsoft', 'Dell', 'HP', 'LG']
        brands = {}
        for brand_name in brands_data:
            brand, created = Brand.objects.get_or_create(
                slug=slugify(brand_name),
                defaults={
                    'name': brand_name,
                    'is_active': True
                }
            )
            brands[brand_name] = brand
            if created:
                self.stdout.write(self.style.SUCCESS(f'Created brand: {brand_name}'))
        
        # Product templates
        products_data = [
            {
                'name': 'Apple iPhone 15 Pro Max',
                'sku_prefix': 'IP15PM',
                'brand': 'Apple',
                'category': 'Smartphones',
                'price': 1199.99,
                'compare_price': 1299.99,
                'description': 'The ultimate iPhone with A17 Pro chip, titanium design, and pro camera system.',
                'stock': 50,
                'is_featured': True,
                'is_bestseller': True,
                'approval_status': 'approved'
            },
            {
                'name': 'Samsung Galaxy S24 Ultra',
                'sku_prefix': 'SGS24U',
                'brand': 'Samsung',
                'category': 'Smartphones',
                'price': 1199.99,
                'compare_price': 1399.99,
                'description': 'Experience the power of Galaxy AI with the all-new S24 Ultra.',
                'stock': 45,
                'is_featured': True,
                'is_new': True,
                'approval_status': 'approved'
            },
            {
                'name': 'Sony WH-1000XM5',
                'sku_prefix': 'SONYXM5',
                'brand': 'Sony',
                'category': 'Audio',
                'price': 399.99,
                'compare_price': 449.99,
                'description': 'Industry-leading noise cancellation with exceptional sound quality.',
                'stock': 30,
                'is_featured': True,
                'is_bestseller': True,
                'approval_status': 'approved'
            },
            {
                'name': 'Apple AirPods Pro 2',
                'sku_prefix': 'APP2',
                'brand': 'Apple',
                'category': 'Audio',
                'price': 249.99,
                'compare_price': 279.99,
                'description': 'Next-level noise cancellation and spatial audio.',
                'stock': 60,
                'is_bestseller': True,
                'approval_status': 'approved'
            },
            {
                'name': 'Samsung Galaxy Tab S9 Ultra',
                'sku_prefix': 'TABS9U',
                'brand': 'Samsung',
                'category': 'Tablets',
                'price': 1199.99,
                'compare_price': 1299.99,
                'description': 'Premium Android tablet with stunning display and S Pen included.',
                'stock': 25,
                'is_featured': True,
                'approval_status': 'approved'
            },
            {
                'name': 'Google Pixel 8 Pro',
                'sku_prefix': 'PIX8P',
                'brand': 'Google',
                'category': 'Smartphones',
                'price': 999.99,
                'compare_price': 1099.99,
                'description': 'The most advanced Pixel yet with AI-powered features.',
                'stock': 35,
                'is_new': True,
                'approval_status': 'approved'
            },
            {
                'name': 'Bose QuietComfort Ultra',
                'sku_prefix': 'BQCU',
                'brand': 'Bose',
                'category': 'Audio',
                'price': 429.99,
                'compare_price': 479.99,
                'description': 'Immersive audio with breakthrough spatial technology.',
                'stock': 28,
                'is_bestseller': True,
                'approval_status': 'approved'
            },
            {
                'name': 'Apple Watch Series 9',
                'sku_prefix': 'AW9',
                'brand': 'Apple',
                'category': 'Wearables',
                'price': 399.99,
                'compare_price': 429.99,
                'description': 'Brighter display, faster performance, and advanced health features.',
                'stock': 55,
                'is_featured': True,
                'approval_status': 'approved'
            },
            {
                'name': 'Samsung Galaxy Watch 6 Classic',
                'sku_prefix': 'SGW6C',
                'brand': 'Samsung',
                'category': 'Wearables',
                'price': 389.99,
                'compare_price': 429.99,
                'description': 'Classic design with rotating bezel and advanced fitness tracking.',
                'stock': 40,
                'approval_status': 'approved'
            },
            {
                'name': 'Dell XPS 15',
                'sku_prefix': 'DXP15',
                'brand': 'Dell',
                'category': 'Laptops',
                'price': 1899.99,
                'compare_price': 2099.99,
                'description': 'Premium laptop with stunning OLED display and powerful performance.',
                'stock': 15,
                'is_featured': True,
                'approval_status': 'approved'
            },
            {
                'name': 'JBL Tour Pro 2',
                'sku_prefix': 'JBLTP2',
                'brand': 'JBL',
                'category': 'Audio',
                'price': 249.99,
                'compare_price': 279.99,
                'description': 'True wireless earbuds with smart charging case display.',
                'stock': 45,
                'approval_status': 'pending'
            },
            {
                'name': 'Sony Xperia 1 V',
                'sku_prefix': 'SX1V',
                'brand': 'Sony',
                'category': 'Smartphones',
                'price': 1399.99,
                'compare_price': 1499.99,
                'description': 'Pro-level camera and 4K OLED display.',
                'stock': 20,
                'approval_status': 'pending'
            },
            {
                'name': 'LG UltraGear 27" Gaming Monitor',
                'sku_prefix': 'LGUG27',
                'brand': 'LG',
                'category': 'Electronics',
                'price': 349.99,
                'compare_price': 399.99,
                'description': '27" 144Hz gaming monitor with G-Sync compatibility.',
                'stock': 20,
                'approval_status': 'approved'
            },
            {
                'name': 'Logitech MX Master 3S',
                'sku_prefix': 'LOGIMX3',
                'brand': 'Logitech',
                'category': 'Accessories',
                'price': 99.99,
                'compare_price': 119.99,
                'description': 'High-performance wireless mouse with MagSpeed scrolling.',
                'stock': 100,
                'approval_status': 'approved'
            },
            {
                'name': 'Razer BlackWidow V4',
                'sku_prefix': 'RAZBW4',
                'brand': 'Razer',
                'category': 'Gaming',
                'price': 179.99,
                'compare_price': 199.99,
                'description': 'Mechanical gaming keyboard with Razer Chroma RGB.',
                'stock': 35,
                'approval_status': 'pending'
            },
            {
                'name': 'Microsoft Surface Laptop Studio',
                'sku_prefix': 'MSLS',
                'brand': 'Microsoft',
                'category': 'Laptops',
                'price': 1599.99,
                'compare_price': 1799.99,
                'description': 'Versatile laptop with dynamic woven hinge.',
                'stock': 12,
                'is_featured': True,
                'approval_status': 'approved'
            },
            {
                'name': 'HP Spectre x360',
                'sku_prefix': 'HPX360',
                'brand': 'HP',
                'category': 'Laptops',
                'price': 1399.99,
                'compare_price': 1599.99,
                'description': 'Premium 2-in-1 laptop with OLED display.',
                'stock': 18,
                'approval_status': 'pending'
            }
        ]
        
        created_count = 0
        updated_count = 0
        
        for product_data in products_data:
            # Generate a consistent SKU based on product name and prefix
            base_sku = product_data['sku_prefix']
            unique_sku = f"{base_sku}-{product_data['brand'][:3]}{product_data['category'][:3]}".upper()
            
            # Clean the SKU to ensure it's valid
            unique_sku = ''.join(c for c in unique_sku if c.isalnum() or c == '-')
            
            # Ensure SKU is unique by adding a suffix if needed
            original_sku = unique_sku
            counter = 1
            while Product.objects.filter(sku=unique_sku).exists():
                unique_sku = f"{original_sku}-{counter}"
                counter += 1
            
            # Get slug
            slug = slugify(product_data['name'])
            original_slug = slug
            counter = 1
            while Product.objects.filter(slug=slug).exists():
                slug = f"{original_slug}-{counter}"
                counter += 1
            
            # Get or create product
            product, created = Product.objects.get_or_create(
                sku=unique_sku,
                defaults={
                    'name': product_data['name'],
                    'slug': slug,
                    'brand': brands.get(product_data['brand']),
                    'category': categories.get(product_data['category']),
                    'vendor': vendor,
                    'price': Decimal(str(product_data['price'])),
                    'compare_price': Decimal(str(product_data['compare_price'])) if product_data.get('compare_price') else None,
                    'description': product_data['description'],
                    'stock_quantity': product_data['stock'],
                    'is_featured': product_data.get('is_featured', False),
                    'is_new': product_data.get('is_new', False),
                    'is_bestseller': product_data.get('is_bestseller', False),
                    'is_active': True,
                    'approval_status': product_data.get('approval_status', 'pending'),
                }
            )
            
            if created:
                created_count += 1
                self.stdout.write(self.style.SUCCESS(f'Created product: {product.name} (SKU: {product.sku})'))
            else:
                updated_count += 1
                self.stdout.write(self.style.WARNING(f'Product already exists: {product.name} (SKU: {product.sku})'))
        
        # Summary
        self.stdout.write(self.style.SUCCESS(f'\n{"="*60}'))
        self.stdout.write(self.style.SUCCESS(f'✅ SEEDING COMPLETE!'))
        self.stdout.write(self.style.SUCCESS(f'{"="*60}'))
        self.stdout.write(self.style.SUCCESS(f'   📦 New products created: {created_count}'))
        self.stdout.write(self.style.SUCCESS(f'   🔄 Existing products verified: {updated_count}'))
        self.stdout.write(self.style.SUCCESS(f'   📊 Total products in database: {Product.objects.count()}'))
        
        # Count by approval status
        approved_count = Product.objects.filter(approval_status='approved').count()
        pending_count = Product.objects.filter(approval_status='pending').count()
        self.stdout.write(self.style.SUCCESS(f'   ✅ Approved products: {approved_count}'))
        self.stdout.write(self.style.WARNING(f'   ⏳ Pending products: {pending_count}'))
        self.stdout.write(self.style.SUCCESS(f'{"="*60}'))