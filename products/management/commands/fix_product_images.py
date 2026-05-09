from django.core.management.base import BaseCommand
from products.models import Product, ProductImage
from django.core.files import File
from django.core.files.base import ContentFile
import os
import requests
from io import BytesIO
from PIL import Image
import json
from urllib.parse import urlparse

class Command(BaseCommand):
    help = 'Fix product images by downloading from URLs or local files'

    def add_arguments(self, parser):
        parser.add_argument('--sku', type=str, help='Process specific product by SKU')
        parser.add_argument('--product-id', type=int, help='Process specific product by ID')
        parser.add_argument('--all', action='store_true', help='Process all products without images')
        parser.add_argument('--force', action='store_true', help='Force download even if image exists')
        parser.add_argument('--resize', action='store_true', help='Resize images to standard dimensions')
        parser.add_argument('--width', type=int, default=800, help='Target width for resizing')
        parser.add_argument('--height', type=int, default=800, help='Target height for resizing')
        parser.add_argument('--quality', type=int, default=85, help='JPEG quality (1-100)')
        parser.add_argument('--from-file', type=str, help='Path to local image file')
        parser.add_argument('--from-dir', type=str, help='Directory containing images named by SKU')
        parser.add_argument('--json', type=str, help='JSON file with image URLs mapping')
        parser.add_argument('--clear-missing', action='store_true', help='Clear images for products without URLs')
        parser.add_argument('--dry-run', action='store_true', help='Show what would be done without changes')

    def get_default_image_urls(self):
        """Get default image URLs for common products"""
        return {
            'SNY-WH1000XM5': 'https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=800',
            'CAN-R5': 'https://images.unsplash.com/photo-1526170375885-4d8ecf77b99f?w=800',
            'APL-MBP16-M3': 'https://images.unsplash.com/photo-1517336714731-489689fd1ca8?w=800',
            'BOS-QC-ULTRA': 'https://images.unsplash.com/photo-1583394838336-acd977736f90?w=800',
            'SNY-A7IV': 'https://images.unsplash.com/photo-1502920917128-1aa500764cbd?w=800',
            'APL-AIRPODS-PRO2': 'https://images.unsplash.com/photo-1606841837239-c5a1a4a07af7?w=800',
        }

    def resize_image(self, img_content, width, height, quality):
        """Resize image to specified dimensions"""
        try:
            img = Image.open(BytesIO(img_content))
            
            # Convert to RGB if needed (for PNG with transparency)
            if img.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                img = background
            
            # Resize maintaining aspect ratio
            img.thumbnail((width, height), Image.Resampling.LANCZOS)
            
            # Save to buffer
            buffer = BytesIO()
            img.save(buffer, format='JPEG', quality=quality, optimize=True)
            buffer.seek(0)
            
            return buffer.getvalue()
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'  ⚠️ Resize failed: {e}'))
            return img_content

    def download_image(self, url, resize=False, width=800, height=800, quality=85):
        """Download image from URL and optionally resize"""
        try:
            response = requests.get(url, timeout=10, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
            
            if response.status_code == 200:
                img_content = response.content
                
                if resize:
                    img_content = self.resize_image(img_content, width, height, quality)
                
                return img_content
            else:
                return None
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'  ❌ Download error: {e}'))
            return None

    def process_product_images(self, product, img_content, filename, is_gallery=False, dry_run=False):
        """Save images to product"""
        if dry_run:
            return True
        
        try:
            if not is_gallery:
                # Save as main image
                product.main_image.save(filename, ContentFile(img_content), save=True)
                self.stdout.write(self.style.SUCCESS(f'  ✅ Saved main image for {product.name}'))
            else:
                # Save as gallery image
                gallery_img = ProductImage.objects.create(
                    product=product,
                    image=ContentFile(img_content, filename),
                    alt_text=product.name,
                    order=product.images.count()
                )
                self.stdout.write(self.style.SUCCESS(f'  ✅ Saved gallery image for {product.name}'))
            return True
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'  ❌ Save error: {e}'))
            return False

    def handle(self, *args, **options):
        sku = options['sku']
        product_id = options['product_id']
        process_all = options['all']
        force = options['force']
        resize = options['resize']
        width = options['width']
        height = options['height']
        quality = options['quality']
        from_file = options['from_file']
        from_dir = options['from_dir']
        json_file = options['json']
        clear_missing = options['clear_missing']
        dry_run = options['dry_run']

        # Load image URLs from JSON if provided
        image_urls = {}
        if json_file:
            try:
                with open(json_file, 'r') as f:
                    image_urls = json.load(f)
                self.stdout.write(self.style.SUCCESS(f'✅ Loaded {len(image_urls)} URLs from {json_file}'))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'❌ Error loading JSON: {e}'))
                return
        else:
            image_urls = self.get_default_image_urls()

        # Determine products to process
        if sku:
            products = Product.objects.filter(sku=sku, is_active=True)
        elif product_id:
            products = Product.objects.filter(id=product_id, is_active=True)
        elif process_all:
            products = Product.objects.filter(is_active=True)
        else:
            products = Product.objects.filter(main_image__isnull=True, is_active=True)
            if not products and not force:
                self.stdout.write(self.style.WARNING('No products without images found. Use --force to override.'))
                return

        if not products.exists():
            self.stdout.write(self.style.WARNING('No products found to process'))
            return

        # Display configuration
        self.stdout.write("\n" + "="*70)
        self.stdout.write("🖼️  PRODUCT IMAGE FIXER")
        self.stdout.write("="*70)
        self.stdout.write(f"\n📊 Products to process: {products.count()}")
        self.stdout.write(f"   Force overwrite: {'Yes' if force else 'No'}")
        self.stdout.write(f"   Resize images: {'Yes' if resize else 'No'}")
        if resize:
            self.stdout.write(f"   Target size: {width}x{height}px")
            self.stdout.write(f"   JPEG quality: {quality}%")
        if dry_run:
            self.stdout.write(f"\n⚠️  DRY RUN MODE - No changes will be made")
        
        self.stdout.write("\n" + "-"*70)

        # Process each product
        processed = 0
        succeeded = 0
        failed = 0
        skipped = 0

        for product in products:
            self.stdout.write(f"\n📦 Product: {product.name}")
            self.stdout.write(f"   SKU: {product.sku}")
            
            # Check if image already exists
            if product.main_image and not force:
                self.stdout.write(self.style.WARNING(f'  ⚠️ Image already exists, skipping (use --force to override)'))
                skipped += 1
                continue

            # Get image URL from mapping
            image_url = image_urls.get(product.sku)
            
            # Try to get from local file
            if from_file and os.path.exists(from_file):
                self.stdout.write(f'  📁 Using local file: {from_file}')
                with open(from_file, 'rb') as f:
                    img_content = f.read()
                    filename = os.path.basename(from_file)
                    if self.process_product_images(product, img_content, filename, False, dry_run):
                        succeeded += 1
                    else:
                        failed += 1
                    processed += 1
                    continue
            
            # Try to get from directory
            if from_dir and os.path.exists(from_dir):
                local_path = os.path.join(from_dir, f"{product.sku}.jpg")
                if os.path.exists(local_path):
                    self.stdout.write(f'  📁 Using local file: {local_path}')
                    with open(local_path, 'rb') as f:
                        img_content = f.read()
                        filename = f"{product.sku}.jpg"
                        if self.process_product_images(product, img_content, filename, False, dry_run):
                            succeeded += 1
                        else:
                            failed += 1
                        processed += 1
                        continue
            
            # Download from URL
            if image_url:
                self.stdout.write(f'  🌐 Downloading from: {image_url[:50]}...')
                
                if dry_run:
                    self.stdout.write(f'  ✅ Would download image for {product.name}')
                    succeeded += 1
                    processed += 1
                    continue
                
                img_content = self.download_image(image_url, resize, width, height, quality)
                
                if img_content:
                    filename = f"{product.sku}.jpg"
                    if self.process_product_images(product, img_content, filename, False, dry_run):
                        succeeded += 1
                    else:
                        failed += 1
                else:
                    self.stdout.write(self.style.ERROR(f'  ❌ Failed to download image for {product.name}'))
                    failed += 1
                
                processed += 1
            else:
                self.stdout.write(self.style.WARNING(f'  ⚠️ No image URL found for SKU: {product.sku}'))
                
                if clear_missing and not dry_run:
                    if product.main_image:
                        product.main_image.delete(save=False)
                        self.stdout.write(f'  🗑️ Cleared existing image')
                    skipped += 1
                else:
                    skipped += 1

        # Summary
        self.stdout.write("\n" + "="*70)
        self.stdout.write("📊 SUMMARY")
        self.stdout.write("="*70)
        
        if not dry_run:
            self.stdout.write(self.style.SUCCESS(f"\n✅ Completed!"))
            self.stdout.write(f"   Products processed: {processed}")
            self.stdout.write(f"   Successful: {succeeded}")
            self.stdout.write(f"   Failed: {failed}")
            self.stdout.write(f"   Skipped: {skipped}")
            
            # Count products with/without images
            with_images = Product.objects.filter(main_image__isnull=False, is_active=True).count()
            without_images = Product.objects.filter(main_image__isnull=True, is_active=True).count()
            
            self.stdout.write(f"\n📈 Overall status:")
            self.stdout.write(f"   Products with images: {with_images}")
            self.stdout.write(f"   Products without images: {without_images}")
        else:
            self.stdout.write("\n💡 This was a DRY RUN. Use without --dry-run to apply changes.")

        self.stdout.write("="*70 + "\n")


class CommandFixGalleryImages(BaseCommand):
    """Fix product gallery images"""
    help = 'Add gallery images to products'

    def add_arguments(self, parser):
        parser.add_argument('--product-id', type=int, required=True, help='Product ID')
        parser.add_argument('--images', type=str, required=True, help='Comma-separated image URLs')
        parser.add_argument('--clear-existing', action='store_true', help='Clear existing gallery images')

    def handle(self, *args, **options):
        product_id = options['product_id']
        image_urls = [url.strip() for url in options['images'].split(',')]
        clear_existing = options['clear_existing']
        
        try:
            product = Product.objects.get(id=product_id, is_active=True)
        except Product.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'Product with ID {product_id} not found'))
            return
        
        if clear_existing:
            product.images.all().delete()
            self.stdout.write(self.style.SUCCESS(f'  🗑️ Cleared existing gallery images'))
        
        added = 0
        for url in image_urls:
            try:
                response = requests.get(url)
                if response.status_code == 200:
                    img_content = response.content
                    filename = url.split('/')[-1].split('?')[0] or f"gallery_{added}.jpg"
                    
                    ProductImage.objects.create(
                        product=product,
                        image=ContentFile(img_content, filename),
                        alt_text=product.name,
                        order=added
                    )
                    added += 1
                    self.stdout.write(self.style.SUCCESS(f'  ✅ Added gallery image {added}'))
                else:
                    self.stdout.write(self.style.ERROR(f'  ❌ Failed to download: {url}'))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'  ❌ Error: {e}'))
        
        self.stdout.write(self.style.SUCCESS(f'\n✅ Added {added} gallery images to {product.name}'))