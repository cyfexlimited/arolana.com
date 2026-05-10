import os
import django
import random
from decimal import Decimal

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'arolana_config.settings')
django.setup()

from products.models import Product, Category, Brand, ProductImage, ProductVariant
from accounts.models import User
from django.core.files.base import ContentFile
from django.core.files import File
import requests
from io import BytesIO
import json

# Function to format specifications dict as HTML
def format_specs_as_html(specs_dict):
    if not specs_dict:
        return ""
    
    html = "<ul>"
    for key, value in specs_dict.items():
        html += f"<li><strong>{key}:</strong> {value}</li>"
    html += "</ul>"
    return html

# Product data - 100 products across categories
products_data = []

# Electronics subcategories
electronics_products = [
    {"name": "4K Ultra HD Smart TV", "price": 699.99, "compare_price": 899.99, "description": "55-inch 4K Ultra HD Smart TV with HDR and Voice Control", "specs": {"Screen": "55\"", "Resolution": "3840x2160", "HDR": "Yes"}},
    {"name": "Wireless Earbuds Pro", "price": 129.99, "compare_price": 199.99, "description": "Active noise cancelling wireless earbuds with charging case", "specs": {"Battery": "8 hours", "Charging": "USB-C", "Waterproof": "IPX7"}},
    {"name": "Smart Home Hub", "price": 89.99, "description": "Central control for all smart home devices", "specs": {"Compatibility": "Alexa, Google, HomeKit", "Screen": "7\""}},
    {"name": "Portable SSD 1TB", "price": 149.99, "compare_price": 199.99, "description": "Ultra-fast portable SSD with USB 3.2", "specs": {"Speed": "1050MB/s", "Capacity": "1TB", "Interface": "USB-C"}},
    {"name": "Mechanical Gaming Keyboard", "price": 89.99, "description": "RGB mechanical keyboard with blue switches", "specs": {"Switches": "Blue", "RGB": "16.8M colors", "Wrist rest": "Yes"}},
    {"name": "Wireless Gaming Mouse", "price": 59.99, "compare_price": 89.99, "description": "High-precision wireless gaming mouse", "specs": {"DPI": "16000", "Buttons": "8", "Battery": "70 hours"}},
    {"name": "27\" Monitor 4K", "price": 349.99, "compare_price": 499.99, "description": "27-inch 4K UHD professional monitor", "specs": {"Resolution": "3840x2160", "Refresh": "60Hz", "Ports": "HDMI, DP, USB-C"}},
    {"name": "Smartwatch Fitness Tracker", "price": 199.99, "description": "Advanced fitness tracker with GPS and heart rate monitor", "specs": {"GPS": "Yes", "Heart Rate": "Continuous", "Battery": "7 days"}},
    {"name": "Robot Vacuum Cleaner", "price": 299.99, "compare_price": 449.99, "description": "Smart robot vacuum with mapping technology", "specs": {"Suction": "2500Pa", "Runtime": "120min", "Mapping": "Laser"}},
    {"name": "Air Purifier", "price": 159.99, "description": "HEPA air purifier for allergies and dust", "specs": {"Coverage": "350 sq ft", "HEPA": "True", "Timer": "Yes"}},
]

# Audio products
audio_products = [
    {"name": "Studio Monitor Headphones", "price": 149.99, "description": "Professional studio monitoring headphones", "specs": {"Impedance": "32Ω", "Frequency": "20-20kHz", "Cable": "Detachable"}},
    {"name": "Bluetooth Speaker", "price": 79.99, "compare_price": 129.99, "description": "Waterproof portable Bluetooth speaker", "specs": {"Battery": "12 hours", "Waterproof": "IPX7", "Power": "20W"}},
    {"name": "Soundbar with Subwoofer", "price": 199.99, "compare_price": 299.99, "description": "2.1 channel soundbar with wireless subwoofer", "specs": {"Channels": "2.1", "Power": "300W", "Connectivity": "HDMI ARC, Bluetooth"}},
    {"name": "USB Microphone", "price": 89.99, "description": "Professional USB microphone for streaming and recording", "specs": {"Pattern": "Cardioid", "Sample Rate": "48kHz", "Plug": "USB-C"}},
    {"name": "Turntable Record Player", "price": 249.99, "description": "Belt-driven turntable with built-in speakers", "specs": {"Speeds": "33 1/3, 45, 78 RPM", "Drive": "Belt", "Bluetooth": "Yes"}},
]

# Camera products
camera_products = [
    {"name": "DSLR Camera Bundle", "price": 899.99, "compare_price": 1299.99, "description": "24MP DSLR with 18-55mm lens kit", "specs": {"Megapixels": "24.2MP", "Video": "4K", "Lens": "18-55mm"}},
    {"name": "Action Camera 4K", "price": 199.99, "compare_price": 299.99, "description": "Waterproof action camera for adventure", "specs": {"Video": "4K60", "Waterproof": "33ft", "Stabilization": "Electronic"}},
    {"name": "Camera Tripod", "price": 49.99, "description": "Professional aluminum tripod", "specs": {"Material": "Aluminum", "Height": "63\"", "Load": "15lbs"}},
    {"name": "Camera Bag Backpack", "price": 79.99, "description": "Waterproof camera backpack with laptop compartment", "specs": {"Capacity": "DSLR + 3 lenses", "Laptop": "15\"", "Waterproof": "Yes"}},
    {"name": "Lens Cleaning Kit", "price": 14.99, "description": "Complete lens cleaning kit", "specs": {"Includes": "Blower, Brush, Wipes, Solution"}},
]

# Gaming products
gaming_products = [
    {"name": "Gaming Chair", "price": 249.99, "compare_price": 399.99, "description": "Ergonomic gaming chair with lumbar support", "specs": {"Adjustable": "Height, Armrest", "Recline": "180°", "Material": "PU Leather"}},
    {"name": "Gaming Headset", "price": 79.99, "compare_price": 119.99, "description": "7.1 surround sound gaming headset", "specs": {"Sound": "7.1 Surround", "Mic": "Noise-cancelling", "RGB": "Yes"}},
    {"name": "Graphics Card RTX 4070", "price": 599.99, "description": "High-performance graphics card for gaming", "specs": {"VRAM": "12GB", "Ray Tracing": "Yes", "Ports": "3x DP, 1x HDMI"}},
    {"name": "Gaming Desk", "price": 199.99, "description": "RGB gaming desk with cable management", "specs": {"Size": "55\"", "RGB": "Yes", "Mouse Pad": "Full surface"}},
]

# Laptop products
laptop_products = [
    {"name": "Ultrabook Laptop", "price": 899.99, "compare_price": 1199.99, "description": "Lightweight ultrabook for productivity", "specs": {"CPU": "Intel i7", "RAM": "16GB", "Storage": "512GB SSD"}},
    {"name": "2-in-1 Convertible Laptop", "price": 749.99, "description": "Convertible laptop with touchscreen", "specs": {"Screen": "14\" Touch", "CPU": "Intel i5", "Storage": "256GB SSD"}},
    {"name": "Business Laptop", "price": 1099.99, "description": "Professional business laptop", "specs": {"CPU": "Intel i7", "RAM": "32GB", "Storage": "1TB SSD"}},
    {"name": "Student Laptop", "price": 499.99, "compare_price": 699.99, "description": "Affordable laptop for students", "specs": {"CPU": "Intel i3", "RAM": "8GB", "Storage": "256GB SSD"}},
    {"name": "Gaming Laptop RTX", "price": 1599.99, "compare_price": 1999.99, "description": "High-performance gaming laptop", "specs": {"GPU": "RTX 4070", "CPU": "Intel i9", "RAM": "32GB", "Storage": "1TB SSD"}},
]

# Book products
book_products = [
    {"name": "Python Programming Guide", "price": 39.99, "description": "Complete guide to Python programming", "specs": {"Pages": "450", "Edition": "3rd"}},
    {"name": "Data Science Handbook", "price": 49.99, "description": "Comprehensive data science guide", "specs": {"Pages": "600", "Includes": "Code examples"}},
    {"name": "Web Development Bootcamp", "price": 44.99, "description": "Full-stack web development", "specs": {"Projects": "10", "Technologies": "HTML, CSS, JS, React, Node"}},
    {"name": "Machine Learning Basics", "price": 59.99, "description": "Introduction to machine learning", "specs": {"Algorithms": "20+", "Examples": "Practical"}},
    {"name": "Cloud Computing AWS", "price": 54.99, "description": "AWS certification guide", "specs": {"Certification": "SAA-C03", "Practice tests": "Included"}},
]

# Combine all products
all_categories = [
    ("Electronics", electronics_products),
    ("Audio", audio_products),
    ("Cameras", camera_products),
    ("Gaming", gaming_products),
    ("Laptops", laptop_products),
    ("Books", book_products),
]

# Colors for variants
colors = ["Black", "White", "Silver", "Gold", "Blue", "Red", "Green", "Purple", "Pink", "Gray"]

# Product images (Unsplash URLs)
image_urls = [
    "https://images.unsplash.com/photo-1484704849700-f032a568e944?w=500",
    "https://images.unsplash.com/photo-1518791841217-8f162f1e1131?w=500",
    "https://images.unsplash.com/photo-1556905055-8f358a7a47b2?w=500",
    "https://images.unsplash.com/photo-1561154464-82e9adf32764?w=500",
    "https://images.unsplash.com/photo-1523275335684-37898b6baf30?w=500",
    "https://images.unsplash.com/photo-1526170375885-4d8ecf77b99f?w=500",
    "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=500",
    "https://images.unsplash.com/photo-1517336714731-489689fd1ca8?w=500",
    "https://images.unsplash.com/photo-1546868871-7041f2a55e12?w=500",
    "https://images.unsplash.com/photo-1583394838336-acd977736f90?w=500",
]

print("=" * 60)
print("ADDING 100+ PRODUCTS TO AROLANA")
print("=" * 60)

# Get vendor user
vendor_user = User.objects.filter(user_type='vendor').first()
if not vendor_user:
    vendor_user = User.objects.create_user(
        username='bulk_vendor',
        email='vendor@arolana.com',
        password='vendor123',
        user_type='vendor'
    )
print(f"Using vendor: {vendor_user.username}")

product_count = 0

for category_name, products in all_categories:
    # Get or create category
    category, _ = Category.objects.get_or_create(
        name=category_name,
        defaults={'slug': category_name.lower(), 'is_active': True}
    )
    print(f"\n📁 Processing category: {category_name}")
    
    for idx, prod_data in enumerate(products):
        # Generate unique SKU
        sku = f"{category_name[:3].upper()}-{idx+1:03d}"
        
        # Create product
        product, created = Product.objects.get_or_create(
            sku=sku,
            defaults={
                'name': prod_data['name'],
                'slug': f"{prod_data['name'].lower().replace(' ', '-')}-{idx}",
                'description': prod_data['description'],
                'specifications': format_specs_as_html(prod_data.get('specs', {})),
                'price': Decimal(prod_data['price']),
                'compare_price': Decimal(prod_data['compare_price']) if prod_data.get('compare_price') else None,
                'stock_quantity': random.randint(10, 100),
                'category': category,
                'vendor': vendor_user,
                'is_featured': random.choice([True, False]),
                'is_active': True,
                'rating_avg': Decimal(random.uniform(3.5, 5.0)).quantize(Decimal('0.01')),
                'rating_count': random.randint(10, 500),
            }
        )
        
        if created:
            product_count += 1
            print(f"  ✅ Created: {product.name}")
            
            # Add product images (try to download real images)
            for img_idx, img_url in enumerate(random.sample(image_urls, min(3, len(image_urls)))):
                try:
                    response = requests.get(img_url, timeout=5)
                    if response.status_code == 200:
                        img_name = f"{product.slug}_img{img_idx}.jpg"
                        product.main_image.save(img_name, ContentFile(response.content), save=False)
                        if img_idx == 0:
                            product.save()
                except:
                    pass
            
            # Add product variants (colors)
            for color in random.sample(colors, random.randint(2, 5)):
                variant_sku = f"{sku}-{color[:3].upper()}"
                ProductVariant.objects.get_or_create(
                    product=product,
                    name='Color',
                    value=color,
                    defaults={
                        'sku': variant_sku,
                        'stock_quantity': random.randint(5, 50),
                        'price_adjustment': Decimal(random.choice([0, 10, 20, 50]))
                    }
                )
            
            # Add size variants for certain products
            if category_name in ['Laptops', 'Gaming']:
                sizes = ['Small', 'Medium', 'Large']
                for size in sizes:
                    ProductVariant.objects.get_or_create(
                        product=product,
                        name='Size',
                        value=size,
                        defaults={
                            'sku': f"{sku}-{size[:2].upper()}",
                            'stock_quantity': random.randint(5, 30),
                        }
                    )
        else:
            print(f"  ⚠️ Product exists: {product.name}")

print("\n" + "=" * 60)
print(f"✅ COMPLETED! Added {product_count} new products")
print(f"📊 Total products now: {Product.objects.count()}")
print("=" * 60)

# Add additional images for existing products
print("\n🖼️ Adding extra images to products...")
products = Product.objects.filter(main_image__isnull=True)[:50]
for product in products:
    try:
        img_url = random.choice(image_urls)
        response = requests.get(img_url, timeout=5)
        if response.status_code == 200:
            product.main_image.save(f"{product.slug}_main.jpg", ContentFile(response.content), save=True)
            print(f"  ✅ Added image to: {product.name}")
    except:
        pass

print("\n🎉 All products added successfully!")
