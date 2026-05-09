from django.core.management.base import BaseCommand
from products.models import Product, ProductVariant
from django.db import transaction

class Command(BaseCommand):
    help = 'Add colors to products with various options'

    def add_arguments(self, parser):
        parser.add_argument('--product-id', type=int, help='Product ID to add colors to')
        parser.add_argument('--product-slug', type=str, help='Product slug to add colors to')
        parser.add_argument('--price-adjustment', type=float, default=0, help='Price adjustment for all colors')
        parser.add_argument('--stock', type=int, default=10, help='Stock quantity for each color')
        parser.add_argument('--colors', type=str, help='Comma-separated list of colors to add (e.g., "Red,Blue,Green")')
        parser.add_argument('--all', action='store_true', help='Add all colors to all products')
        parser.add_argument('--remove', action='store_true', help='Remove specified colors instead of adding')
        parser.add_argument('--clear-all', action='store_true', help='Clear all colors from product')
        parser.add_argument('--update-price', action='store_true', help='Update price adjustment for existing colors')
        parser.add_argument('--dry-run', action='store_true', help='Show what would be done without making changes')
        parser.add_argument('--bulk', action='store_true', help='Add colors to multiple products (requires product list)')
        parser.add_argument('--product-ids', type=str, help='Comma-separated product IDs for bulk operations')

    def add_colors_to_product(self, product, colors, price_adjustment, stock, remove=False, 
                               update_price=False, dry_run=False):
        """Add or remove colors from a product"""
        
        if dry_run:
            self.stdout.write(f"\n📋 DRY RUN - {product.name}:")
        
        colors_added = 0
        colors_removed = 0
        colors_updated = 0
        
        for color in colors:
            color = color.strip()
            variant, created = ProductVariant.objects.get_or_create(
                product=product,
                variant_type='color',
                name='Color',
                value=color,
                defaults={
                    'price_adjustment': price_adjustment,
                    'stock_quantity': stock,
                    'is_active': True
                }
            )
            
            if remove:
                if not created:
                    if not dry_run:
                        variant.delete()
                    colors_removed += 1
                    self.stdout.write(self.style.WARNING(f'  🗑️ Removed Color: {color}'))
                else:
                    self.stdout.write(f'  ⚠️ Color not found: {color}')
            else:
                if created:
                    colors_added += 1
                    if not dry_run:
                        self.stdout.write(self.style.SUCCESS(f'  ✅ Added Color: {color}'))
                    else:
                        self.stdout.write(f'  ✅ Would add Color: {color}')
                else:
                    if update_price:
                        if not dry_run:
                            variant.price_adjustment = price_adjustment
                            variant.stock_quantity = stock
                            variant.save()
                        colors_updated += 1
                        self.stdout.write(self.style.SUCCESS(f'  🔄 Updated Color: {color}'))
                    else:
                        self.stdout.write(f'  ⚠️ Color already exists: {color}')
        
        return {
            'added': colors_added,
            'removed': colors_removed,
            'updated': colors_updated
        }

    def handle(self, *args, **options):
        product_id = options['product_id']
        product_slug = options['product_slug']
        price_adjustment = options['price_adjustment']
        stock = options['stock']
        colors_input = options['colors']
        remove = options['remove']
        clear_all = options['clear_all']
        update_price = options['update_price']
        dry_run = options['dry_run']
        bulk = options['bulk']
        product_ids = options['product_ids']
        all_products = options['all']

        # Complete color list
        all_colors = [
            'Red', 'Blue', 'Green', 'Black', 'White', 'Yellow', 'Purple', 'Orange',
            'Pink', 'Brown', 'Gray', 'Navy', 'Cyan', 'Magenta', 'Lime', 'Olive',
            'Maroon', 'Teal', 'Gold', 'Silver', 'Indigo', 'Violet', 'Coral', 'Salmon',
            'Turquoise', 'Lavender', 'Khaki', 'Plum', 'Peach', 'Mint', 'Beige',
            'Crimson', 'Aqua', 'Fuchsia', 'Tan', 'Ivory', 'Champagne', 'Bronze', 'Copper',
            'Rose Gold', 'Space Gray', 'Midnight Blue', 'Forest Green', 'Burgundy',
            'Charcoal', 'Steel Blue', 'Slate', 'Denim', 'Emerald', 'Ruby', 'Sapphire'
        ]

        # Determine which colors to use
        if colors_input:
            colors_to_use = [c.strip() for c in colors_input.split(',')]
        else:
            colors_to_use = all_colors

        # Bulk operation
        if bulk and product_ids:
            product_ids_list = [int(pid.strip()) for pid in product_ids.split(',')]
            products = Product.objects.filter(id__in=product_ids_list, is_active=True)
            
            if not products.exists():
                self.stdout.write(self.style.ERROR('No products found with given IDs'))
                return
            
            for product in products:
                self.add_colors_to_product(product, colors_to_use, price_adjustment, 
                                           stock, remove, update_price, dry_run)
            
            return

        # Add colors to all products
        if all_products:
            products = Product.objects.filter(is_active=True)
            
            if not products.exists():
                self.stdout.write(self.style.ERROR('No active products found'))
                return
            
            self.stdout.write(f"\n🎨 Adding colors to {products.count()} products...")
            
            for product in products:
                self.add_colors_to_product(product, colors_to_use, price_adjustment, 
                                           stock, remove, update_price, dry_run)
            
            return

        # Single product by ID
        if product_id:
            try:
                product = Product.objects.get(id=product_id, is_active=True)
            except Product.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'Product with ID {product_id} not found'))
                return
        
        # Single product by slug
        elif product_slug:
            try:
                product = Product.objects.get(slug=product_slug, is_active=True)
            except Product.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'Product with slug {product_slug} not found'))
                return
        else:
            self.stdout.write(self.style.ERROR('Please provide --product-id, --product-slug, --all, or --bulk'))
            return

        # Clear all colors from product
        if clear_all:
            if dry_run:
                self.stdout.write(f"\n📋 DRY RUN - Would clear all colors from {product.name}")
            else:
                deleted_count = product.variants.filter(variant_type='color').delete()[0]
                self.stdout.write(self.style.SUCCESS(f'\n✅ Cleared {deleted_count} colors from {product.name}'))
            return

        # Add/remove colors
        self.stdout.write(f"\n🎨 Product: {product.name}")
        self.stdout.write(f"   Category: {product.category.name}")
        self.stdout.write(f"   Current price: ${product.price}")
        self.stdout.write(f"   Price adjustment: ${price_adjustment}")
        self.stdout.write(f"   Stock per color: {stock}\n")
        
        if remove:
            self.stdout.write(f"🗑️ Removing colors from {product.name}...\n")
        else:
            self.stdout.write(f"🎨 Adding colors to {product.name}...\n")
        
        stats = self.add_colors_to_product(product, colors_to_use, price_adjustment, 
                                           stock, remove, update_price, dry_run)
        
        if not dry_run:
            self.stdout.write(self.style.SUCCESS(f'\n✅ Completed!'))
            self.stdout.write(f'   Added: {stats["added"]} colors')
            self.stdout.write(f'   Removed: {stats["removed"]} colors')
            self.stdout.write(f'   Updated: {stats["updated"]} colors')
            
            total_colors = product.variants.filter(variant_type='color').count()
            self.stdout.write(f'   Total colors now: {total_colors}')
            
            # Show existing colors
            if total_colors > 0:
                self.stdout.write('\n📋 Current colors:')
                for variant in product.variants.filter(variant_type='color').order_by('value'):
                    self.stdout.write(f'   - {variant.value} (Stock: {variant.stock_quantity}, Price adj: ${variant.price_adjustment})')
        
        if dry_run:
            self.stdout.write('\n💡 This was a DRY RUN. Use without --dry-run to apply changes.')


class CommandAddSizes(BaseCommand):
    """Add sizes to products"""
    help = 'Add standard sizes to products'

    def add_arguments(self, parser):
        parser.add_argument('--product-id', type=int, required=True, help='Product ID to add sizes to')
        parser.add_argument('--price-adjustment', type=float, default=0, help='Price adjustment for sizes')
        parser.add_argument('--stock', type=int, default=10, help='Stock quantity for each size')

    def handle(self, *args, **options):
        product_id = options['product_id']
        price_adjustment = options['price_adjustment']
        stock = options['stock']
        
        try:
            product = Product.objects.get(id=product_id, is_active=True)
        except Product.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'Product with ID {product_id} not found'))
            return
        
        sizes = ['XS', 'S', 'M', 'L', 'XL', 'XXL', 'XXXL']
        
        sizes_added = 0
        
        for size in sizes:
            variant, created = ProductVariant.objects.get_or_create(
                product=product,
                variant_type='size',
                name='Size',
                value=size,
                defaults={
                    'price_adjustment': price_adjustment,
                    'stock_quantity': stock,
                    'is_active': True
                }
            )
            if created:
                sizes_added += 1
                self.stdout.write(self.style.SUCCESS(f'  ✅ Added Size: {size}'))
        
        self.stdout.write(self.style.SUCCESS(f'\n✅ Added {sizes_added} sizes to {product.name}'))
        self.stdout.write(f'   Total sizes: {product.variants.filter(variant_type="size").count()}')


class CommandAddAllVariants(BaseCommand):
    """Add both colors and sizes to products"""
    help = 'Add both colors and sizes to products'

    def add_arguments(self, parser):
        parser.add_argument('--product-id', type=int, required=True, help='Product ID')
        parser.add_argument('--price-adjustment', type=float, default=0, help='Price adjustment')
        parser.add_argument('--stock', type=int, default=10, help='Stock quantity')

    def handle(self, *args, **options):
        product_id = options['product_id']
        price_adjustment = options['price_adjustment']
        stock = options['stock']
        
        try:
            product = Product.objects.get(id=product_id, is_active=True)
        except Product.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'Product with ID {product_id} not found'))
            return
        
        colors = [
            'Red', 'Blue', 'Green', 'Black', 'White', 'Yellow', 'Purple', 'Orange'
        ]
        
        sizes = ['XS', 'S', 'M', 'L', 'XL', 'XXL']
        
        variants_added = 0
        
        self.stdout.write(f"\n🎨 Adding variants to {product.name}...\n")
        
        for color in colors:
            for size in sizes:
                variant_name = f"{color} - {size}"
                variant, created = ProductVariant.objects.get_or_create(
                    product=product,
                    variant_type='other',
                    name='Color-Size',
                    value=variant_name,
                    defaults={
                        'price_adjustment': price_adjustment,
                        'stock_quantity': stock,
                        'is_active': True
                    }
                )
                if created:
                    variants_added += 1
                    self.stdout.write(self.style.SUCCESS(f'  ✅ Added: {color} / {size}'))
        
        self.stdout.write(self.style.SUCCESS(f'\n✅ Added {variants_added} variants to {product.name}'))