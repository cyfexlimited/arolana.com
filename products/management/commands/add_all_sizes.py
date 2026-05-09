from django.core.management.base import BaseCommand
from products.models import Product, ProductVariant
from django.db import transaction

class Command(BaseCommand):
    help = 'Add sizes to a product with flexible options'

    def add_arguments(self, parser):
        parser.add_argument('--product-id', type=int, help='Product ID to add sizes to')
        parser.add_argument('--product-slug', type=str, help='Product slug to add sizes to')
        parser.add_argument('--price-adjustments', type=str, default='0,5,10,15,20',
                           help='Comma-separated price adjustments for sizes')
        parser.add_argument('--stock', type=int, default=10, help='Stock quantity for each size')
        parser.add_argument('--sizes', type=str, 
                           help='Comma-separated custom sizes (e.g., "XS,S,M,L,XL,XXL")')
        parser.add_argument('--size-type', type=str, default='standard',
                           choices=['standard', 'us', 'eu', 'uk', 'kids', 'custom'],
                           help='Size system to use')
        parser.add_argument('--clear-existing', action='store_true',
                           help='Clear existing sizes before adding new ones')
        parser.add_argument('--remove', action='store_true',
                           help='Remove sizes instead of adding')
        parser.add_argument('--remove-sizes', type=str,
                           help='Comma-separated sizes to remove')
        parser.add_argument('--update-stock', action='store_true',
                           help='Update stock for existing sizes')
        parser.add_argument('--dry-run', action='store_true',
                           help='Show what would be done without making changes')
        parser.add_argument('--all-products', action='store_true',
                           help='Add sizes to all active products')

    def get_size_list(self, size_type, custom_sizes=None):
        """Get size list based on size system"""
        
        size_systems = {
            'standard': ['XS', 'S', 'M', 'L', 'XL', 'XXL', 'XXXL'],
            'us': ['XS', 'S', 'M', 'L', 'XL', 'XXL', 'XXXL'],
            'eu': ['32', '34', '36', '38', '40', '42', '44', '46', '48', '50'],
            'uk': ['6', '8', '10', '12', '14', '16', '18', '20', '22'],
            'kids': ['2T', '3T', '4T', '5T', '6', '7', '8', '10', '12', '14'],
        }
        
        if custom_sizes:
            return [s.strip() for s in custom_sizes.split(',')]
        
        return size_systems.get(size_type, size_systems['standard'])

    def get_price_adjustments_list(self, price_adjustments_str, num_sizes):
        """Parse and extend price adjustments to match number of sizes"""
        adjustments = [float(x) for x in price_adjustments_str.split(',')]
        
        # If fewer adjustments than sizes, repeat last value
        while len(adjustments) < num_sizes:
            adjustments.append(adjustments[-1] if adjustments else 0)
        
        # If more adjustments than sizes, truncate
        return adjustments[:num_sizes]

    def add_sizes_to_product(self, product, sizes, price_adjustments, stock, 
                             remove=False, clear_existing=False, 
                             update_stock=False, dry_run=False):
        """Add or remove sizes from a product"""
        
        if dry_run:
            self.stdout.write(f"\n📋 DRY RUN - {product.name}:")
        
        sizes_added = 0
        sizes_removed = 0
        sizes_updated = 0
        
        if clear_existing and not dry_run and not remove:
            existing_count = product.variants.filter(variant_type='size').delete()[0]
            self.stdout.write(self.style.WARNING(f'  🗑️ Cleared {existing_count} existing sizes'))
        
        for i, size in enumerate(sizes):
            price_adj = price_adjustments[i] if i < len(price_adjustments) else 0
            
            variant, created = ProductVariant.objects.get_or_create(
                product=product,
                variant_type='size',
                name='Size',
                value=size,
                defaults={
                    'price_adjustment': price_adj,
                    'stock_quantity': stock,
                    'is_active': True
                }
            )
            
            if remove:
                if not created:
                    if not dry_run:
                        variant.delete()
                    sizes_removed += 1
                    if not dry_run:
                        self.stdout.write(self.style.WARNING(f'  🗑️ Removed Size: {size}'))
                    else:
                        self.stdout.write(f'  🗑️ Would remove Size: {size}')
                else:
                    self.stdout.write(f'  ⚠️ Size not found: {size}')
            else:
                if created:
                    sizes_added += 1
                    if not dry_run:
                        self.stdout.write(self.style.SUCCESS(f'  ✅ Added Size: {size} (${price_adj})'))
                    else:
                        self.stdout.write(f'  ✅ Would add Size: {size} (${price_adj})')
                else:
                    if update_stock:
                        if not dry_run:
                            variant.price_adjustment = price_adj
                            variant.stock_quantity = stock
                            variant.save()
                        sizes_updated += 1
                        self.stdout.write(self.style.SUCCESS(f'  🔄 Updated Size: {size} (Stock: {stock})'))
                    else:
                        self.stdout.write(f'  ⚠️ Size already exists: {size}')
        
        return {
            'added': sizes_added,
            'removed': sizes_removed,
            'updated': sizes_updated
        }

    def handle(self, *args, **options):
        product_id = options['product_id']
        product_slug = options['product_slug']
        stock = options['stock']
        price_adjustments_str = options['price_adjustments']
        sizes_input = options['sizes']
        size_type = options['size_type']
        clear_existing = options['clear_existing']
        remove = options['remove']
        remove_sizes = options['remove_sizes']
        update_stock = options['update_stock']
        dry_run = options['dry_run']
        all_products = options['all_products']

        # Get size list
        if remove_sizes:
            sizes_to_use = [s.strip() for s in remove_sizes.split(',')]
            remove = True
        else:
            sizes_to_use = self.get_size_list(size_type, sizes_input)
        
        # Get price adjustments
        price_adjustments = self.get_price_adjustments_list(price_adjustments_str, len(sizes_to_use))
        
        # Add sizes to all active products
        if all_products:
            products = Product.objects.filter(is_active=True)
            
            if not products.exists():
                self.stdout.write(self.style.ERROR('No active products found'))
                return
            
            self.stdout.write(f"\n🎨 Adding sizes to {products.count()} products...")
            self.stdout.write(f"   Size system: {size_type}")
            self.stdout.write(f"   Sizes: {', '.join(sizes_to_use)}")
            self.stdout.write(f"   Stock per size: {stock}\n")
            
            total_stats = {'added': 0, 'removed': 0, 'updated': 0}
            
            for product in products:
                self.stdout.write(f"\n📦 Product: {product.name}")
                stats = self.add_sizes_to_product(
                    product, sizes_to_use, price_adjustments, stock,
                    remove, clear_existing, update_stock, dry_run
                )
                total_stats['added'] += stats['added']
                total_stats['removed'] += stats['removed']
                total_stats['updated'] += stats['updated']
            
            if not dry_run:
                self.stdout.write(self.style.SUCCESS(f'\n✅ Completed for all products!'))
                self.stdout.write(f'   Total sizes added: {total_stats["added"]}')
                self.stdout.write(f'   Total sizes removed: {total_stats["removed"]}')
                self.stdout.write(f'   Total sizes updated: {total_stats["updated"]}')
            else:
                self.stdout.write('\n💡 This was a DRY RUN. Use without --dry-run to apply changes.')
            
            return

        # Get single product
        if product_id:
            try:
                product = Product.objects.get(id=product_id, is_active=True)
            except Product.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'Product with ID {product_id} not found'))
                return
        
        elif product_slug:
            try:
                product = Product.objects.get(slug=product_slug, is_active=True)
            except Product.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'Product with slug {product_slug} not found'))
                return
        else:
            self.stdout.write(self.style.ERROR('Please provide --product-id, --product-slug, or --all-products'))
            return

        # Display product info
        self.stdout.write(f"\n📦 Product: {product.name}")
        self.stdout.write(f"   ID: {product.id}")
        self.stdout.write(f"   Category: {product.category.name}")
        self.stdout.write(f"   Price: ${product.price}")
        self.stdout.write(f"   Current stock: {product.stock_quantity}")
        self.stdout.write(f"\n📏 Size Information:")
        self.stdout.write(f"   Size system: {size_type}")
        self.stdout.write(f"   Sizes: {', '.join(sizes_to_use)}")
        self.stdout.write(f"   Price adjustments: {', '.join(f'${adj}' for adj in price_adjustments)}")
        self.stdout.write(f"   Stock per size: {stock}\n")

        # Show existing sizes
        existing_sizes = product.variants.filter(variant_type='size')
        if existing_sizes.exists():
            self.stdout.write("📋 Existing sizes:")
            for variant in existing_sizes:
                self.stdout.write(f"   - {variant.value} (Stock: {variant.stock_quantity}, Price adj: ${variant.price_adjustment})")
            self.stdout.write("")
        
        if remove:
            if remove_sizes:
                self.stdout.write(f"🗑️ Removing specific sizes from {product.name}...\n")
            else:
                self.stdout.write(f"🗑️ Removing all sizes from {product.name}...\n")
        else:
            self.stdout.write(f"🎨 Adding sizes to {product.name}...\n")
        
        # Add/remove sizes
        stats = self.add_sizes_to_product(
            product, sizes_to_use, price_adjustments, stock,
            remove, clear_existing, update_stock, dry_run
        )
        
        if not dry_run:
            self.stdout.write(self.style.SUCCESS(f'\n✅ Completed!'))
            self.stdout.write(f'   Added: {stats["added"]} sizes')
            self.stdout.write(f'   Removed: {stats["removed"]} sizes')
            self.stdout.write(f'   Updated: {stats["updated"]} sizes')
            
            total_sizes = product.variants.filter(variant_type='size').count()
            self.stdout.write(f'   Total sizes now: {total_sizes}')
            
            # Show updated sizes
            if total_sizes > 0:
                self.stdout.write('\n📋 Updated sizes:')
                for variant in product.variants.filter(variant_type='size').order_by('value'):
                    self.stdout.write(f'   - {variant.value} (Stock: {variant.stock_quantity}, Price adj: ${variant.price_adjustment})')
        
        if dry_run:
            self.stdout.write('\n💡 This was a DRY RUN. Use without --dry-run to apply changes.')


class CommandAddAllSizesToCategory(BaseCommand):
    """Add sizes to all products in a category"""
    help = 'Add standard sizes to all products in a category'

    def add_arguments(self, parser):
        parser.add_argument('--category-id', type=int, required=True, help='Category ID')
        parser.add_argument('--stock', type=int, default=10, help='Stock quantity for each size')
        parser.add_argument('--price-adjustments', type=str, default='0,5,10,15,20',
                           help='Comma-separated price adjustments')

    def handle(self, *args, **options):
        from products.models import Category
        
        category_id = options['category_id']
        stock = options['stock']
        price_adjustments_str = options['price_adjustments']
        
        try:
            category = Category.objects.get(id=category_id, is_active=True)
        except Category.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'Category with ID {category_id} not found'))
            return
        
        products = Product.objects.filter(category=category, is_active=True)
        
        if not products.exists():
            self.stdout.write(self.style.WARNING(f'No active products found in category {category.name}'))
            return
        
        sizes = ['XS', 'S', 'M', 'L', 'XL', 'XXL', 'XXXL']
        price_adjustments = [float(x) for x in price_adjustments_str.split(',')]
        
        # Extend price adjustments
        while len(price_adjustments) < len(sizes):
            price_adjustments.append(price_adjustments[-1] if price_adjustments else 0)
        
        total_added = 0
        
        self.stdout.write(f"\n🎨 Adding sizes to products in category: {category.name}")
        self.stdout.write(f"   Products found: {products.count()}")
        self.stdout.write(f"   Sizes: {', '.join(sizes)}\n")
        
        for product in products:
            sizes_added = 0
            for i, size in enumerate(sizes):
                variant, created = ProductVariant.objects.get_or_create(
                    product=product,
                    variant_type='size',
                    name='Size',
                    value=size,
                    defaults={
                        'price_adjustment': price_adjustments[i],
                        'stock_quantity': stock,
                        'is_active': True
                    }
                )
                if created:
                    sizes_added += 1
            
            if sizes_added > 0:
                total_added += sizes_added
                self.stdout.write(self.style.SUCCESS(f'  ✅ Added {sizes_added} sizes to {product.name}'))
            else:
                self.stdout.write(f'  ⚠️ Sizes already exist for {product.name}')
        
        self.stdout.write(self.style.SUCCESS(f'\n✅ Completed! Added {total_added} sizes total'))