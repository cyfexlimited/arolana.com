from django.core.management.base import BaseCommand
from products.models import Product, ProductVariant
from django.db import transaction

class Command(BaseCommand):
    help = 'Add size and color variants to products with flexible options'

    def add_arguments(self, parser):
        parser.add_argument('--product-id', type=int, help='Product ID to add variants to')
        parser.add_argument('--product-slug', type=str, help='Product slug to add variants to')
        parser.add_argument('--all', action='store_true', help='Add variants to all products')
        parser.add_argument('--category-id', type=int, help='Add variants to all products in category')
        
        # Size options
        parser.add_argument('--add-sizes', action='store_true', default=True, help='Add size variants')
        parser.add_argument('--no-sizes', action='store_true', help='Skip size variants')
        parser.add_argument('--sizes', type=str, help='Custom sizes (comma-separated)')
        parser.add_argument('--size-price-adjustments', type=str, 
                           help='Price adjustments for sizes (comma-separated)')
        parser.add_argument('--size-stock', type=int, default=10, help='Stock for each size')
        
        # Color options
        parser.add_argument('--add-colors', action='store_true', default=True, help='Add color variants')
        parser.add_argument('--no-colors', action='store_true', help='Skip color variants')
        parser.add_argument('--colors', type=str, help='Custom colors (comma-separated)')
        parser.add_argument('--color-price-adjustment', type=float, default=0, help='Price adjustment for colors')
        parser.add_argument('--color-stock', type=int, default=15, help='Stock for each color')
        
        # General options
        parser.add_argument('--clear-existing', action='store_true', help='Clear existing variants before adding')
        parser.add_argument('--remove', action='store_true', help='Remove variants instead of adding')
        parser.add_argument('--remove-sizes-only', action='store_true', help='Remove only size variants')
        parser.add_argument('--remove-colors-only', action='store_true', help='Remove only color variants')
        parser.add_argument('--dry-run', action='store_true', help='Show what would be done without changes')
        parser.add_argument('--update-existing', action='store_true', help='Update existing variants with new values')
        
        # Bulk options
        parser.add_argument('--product-ids', type=str, help='Comma-separated product IDs for bulk operations')
        parser.add_argument('--bulk', action='store_true', help='Add variants to multiple products')

    def get_default_sizes(self):
        """Get default size list"""
        return ['XS', 'S', 'M', 'L', 'XL', 'XXL', 'XXXL']
    
    def get_default_colors(self):
        """Get default color list"""
        return [
            'Red', 'Blue', 'Green', 'Black', 'White', 'Yellow', 'Purple', 'Orange',
            'Pink', 'Brown', 'Gray', 'Navy', 'Cyan', 'Magenta', 'Lime', 'Olive',
            'Maroon', 'Teal', 'Gold', 'Silver', 'Indigo', 'Violet', 'Coral', 'Salmon'
        ]
    
    def add_variants_to_product(self, product, add_sizes=True, add_colors=True, 
                                 sizes=None, colors=None, size_price_adjustments=None,
                                 color_price_adjustment=0, size_stock=10, color_stock=15,
                                 clear_existing=False, remove=False, remove_sizes_only=False,
                                 remove_colors_only=False, update_existing=False, dry_run=False):
        """Add or remove variants from a product"""
        
        if dry_run:
            self.stdout.write(f"\n📋 DRY RUN - {product.name}:")
        
        stats = {'sizes_added': 0, 'colors_added': 0, 'sizes_removed': 0, 'colors_removed': 0}
        
        # Prepare sizes
        if add_sizes and not remove and not remove_sizes_only:
            if not sizes:
                sizes = self.get_default_sizes()
            size_price_list = self.parse_price_adjustments(size_price_adjustments, len(sizes))
            
            if clear_existing and not dry_run:
                product.variants.filter(variant_type='size').delete()
                self.stdout.write(self.style.WARNING('  🗑️ Cleared existing size variants'))
            
            for i, size in enumerate(sizes):
                price_adj = size_price_list[i] if i < len(size_price_list) else 0
                
                variant, created = ProductVariant.objects.get_or_create(
                    product=product,
                    variant_type='size',
                    name='Size',
                    value=size,
                    defaults={
                        'price_adjustment': price_adj,
                        'stock_quantity': size_stock,
                        'is_active': True
                    }
                )
                
                if created:
                    stats['sizes_added'] += 1
                    if not dry_run:
                        self.stdout.write(self.style.SUCCESS(f'  ✅ Added Size: {size} (+${price_adj})'))
                    else:
                        self.stdout.write(f'  ✅ Would add Size: {size} (+${price_adj})')
                elif update_existing and not dry_run:
                    variant.price_adjustment = price_adj
                    variant.stock_quantity = size_stock
                    variant.save()
                    self.stdout.write(self.style.SUCCESS(f'  🔄 Updated Size: {size} (Stock: {size_stock})'))
        
        # Remove sizes
        if remove_sizes_only or (remove and add_sizes):
            removed = product.variants.filter(variant_type='size').delete()[0]
            stats['sizes_removed'] = removed
            if not dry_run:
                self.stdout.write(self.style.WARNING(f'  🗑️ Removed {removed} size variants'))
        
        # Prepare colors
        if add_colors and not remove and not remove_colors_only:
            if not colors:
                colors = self.get_default_colors()
            
            if clear_existing and not dry_run:
                product.variants.filter(variant_type='color').delete()
                self.stdout.write(self.style.WARNING('  🗑️ Cleared existing color variants'))
            
            for color in colors[:12]:  # Limit to first 12 colors
                variant, created = ProductVariant.objects.get_or_create(
                    product=product,
                    variant_type='color',
                    name='Color',
                    value=color,
                    defaults={
                        'price_adjustment': color_price_adjustment,
                        'stock_quantity': color_stock,
                        'is_active': True
                    }
                )
                
                if created:
                    stats['colors_added'] += 1
                    if not dry_run:
                        self.stdout.write(self.style.SUCCESS(f'  ✅ Added Color: {color} (+${color_price_adjustment})'))
                    else:
                        self.stdout.write(f'  ✅ Would add Color: {color} (+${color_price_adjustment})')
                elif update_existing and not dry_run:
                    variant.price_adjustment = color_price_adjustment
                    variant.stock_quantity = color_stock
                    variant.save()
                    self.stdout.write(self.style.SUCCESS(f'  🔄 Updated Color: {color}'))
        
        # Remove colors
        if remove_colors_only or (remove and add_colors):
            removed = product.variants.filter(variant_type='color').delete()[0]
            stats['colors_removed'] = removed
            if not dry_run:
                self.stdout.write(self.style.WARNING(f'  🗑️ Removed {removed} color variants'))
        
        return stats
    
    def parse_price_adjustments(self, price_str, num_items):
        """Parse price adjustments string into list"""
        if not price_str:
            # Generate progressive adjustments
            return [i * 5 for i in range(num_items)]
        
        adjustments = [float(x.strip()) for x in price_str.split(',')]
        
        # Extend or truncate to match number of items
        while len(adjustments) < num_items:
            adjustments.append(adjustments[-1] if adjustments else 0)
        
        return adjustments[:num_items]

    def handle(self, *args, **options):
        product_id = options['product_id']
        product_slug = options['product_slug']
        add_sizes = not options['no_sizes']
        add_colors = not options['no_colors']
        sizes_input = options['sizes']
        colors_input = options['colors']
        size_price_adjustments = options['size_price_adjustments']
        color_price_adjustment = options['color_price_adjustment']
        size_stock = options['size_stock']
        color_stock = options['color_stock']
        clear_existing = options['clear_existing']
        remove = options['remove']
        remove_sizes_only = options['remove_sizes_only']
        remove_colors_only = options['remove_colors_only']
        dry_run = options['dry_run']
        update_existing = options['update_existing']
        all_products = options['all']
        category_id = options['category_id']
        bulk = options['bulk']
        product_ids_str = options['product_ids']
        
        # Parse sizes and colors
        sizes = [s.strip() for s in sizes_input.split(',')] if sizes_input else None
        colors = [c.strip() for c in colors_input.split(',')] if colors_input else None
        
        # Determine which products to process
        if product_id:
            products = Product.objects.filter(id=product_id, is_active=True)
        elif product_slug:
            products = Product.objects.filter(slug=product_slug, is_active=True)
        elif all_products:
            products = Product.objects.filter(is_active=True)
        elif category_id:
            from products.models import Category
            try:
                category = Category.objects.get(id=category_id, is_active=True)
                products = Product.objects.filter(category=category, is_active=True)
            except Category.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'Category with ID {category_id} not found'))
                return
        elif bulk and product_ids_str:
            product_ids = [int(pid.strip()) for pid in product_ids_str.split(',')]
            products = Product.objects.filter(id__in=product_ids, is_active=True)
        else:
            self.stdout.write(self.style.ERROR('Please specify --product-id, --product-slug, --all, --category-id, or --bulk'))
            return
        
        if not products.exists():
            self.stdout.write(self.style.ERROR('No products found'))
            return
        
        # Display configuration
        self.stdout.write("\n" + "="*60)
        self.stdout.write("📦 PRODUCT VARIANT MANAGER")
        self.stdout.write("="*60)
        self.stdout.write(f"\n📊 Processing {products.count()} product(s)")
        
        if add_sizes:
            self.stdout.write(f"\n📏 Size Configuration:")
            self.stdout.write(f"   Sizes: {', '.join(sizes) if sizes else 'Default sizes'}")
            self.stdout.write(f"   Stock per size: {size_stock}")
            if size_price_adjustments:
                self.stdout.write(f"   Price adjustments: {size_price_adjustments}")
            else:
                self.stdout.write(f"   Price adjustments: Progressive ($0, $5, $10, ...)")
        
        if add_colors:
            self.stdout.write(f"\n🎨 Color Configuration:")
            self.stdout.write(f"   Colors: {', '.join(colors[:12]) if colors else 'Default colors (first 12)'}")
            self.stdout.write(f"   Stock per color: {color_stock}")
            self.stdout.write(f"   Price adjustment: +${color_price_adjustment}")
        
        if clear_existing:
            self.stdout.write(f"\n⚠️  Will clear existing variants before adding")
        if remove:
            self.stdout.write(f"\n⚠️  Will REMOVE variants")
        if dry_run:
            self.stdout.write(f"\n⚠️  DRY RUN MODE - No changes will be made")
        
        # Process each product
        total_stats = {'sizes_added': 0, 'colors_added': 0, 
                       'sizes_removed': 0, 'colors_removed': 0}
        
        for product in products:
            stats = self.add_variants_to_product(
                product, add_sizes, add_colors, sizes, colors,
                size_price_adjustments, color_price_adjustment,
                size_stock, color_stock, clear_existing, remove,
                remove_sizes_only, remove_colors_only, update_existing, dry_run
            )
            
            total_stats['sizes_added'] += stats['sizes_added']
            total_stats['colors_added'] += stats['colors_added']
            total_stats['sizes_removed'] += stats['sizes_removed']
            total_stats['colors_removed'] += stats['colors_removed']
            
            if not dry_run and (stats['sizes_added'] > 0 or stats['colors_added'] > 0):
                self.stdout.write(f"\n📊 {product.name}:")
                self.stdout.write(f"   Sizes added: {stats['sizes_added']}")
                self.stdout.write(f"   Colors added: {stats['colors_added']}")
        
        # Summary
        self.stdout.write("\n" + "="*60)
        self.stdout.write("📊 SUMMARY")
        self.stdout.write("="*60)
        
        if not dry_run:
            self.stdout.write(self.style.SUCCESS(f"\n✅ Completed!"))
            self.stdout.write(f"   Products processed: {products.count()}")
            self.stdout.write(f"   Sizes added: {total_stats['sizes_added']}")
            self.stdout.write(f"   Colors added: {total_stats['colors_added']}")
            if total_stats['sizes_removed'] > 0:
                self.stdout.write(f"   Sizes removed: {total_stats['sizes_removed']}")
            if total_stats['colors_removed'] > 0:
                self.stdout.write(f"   Colors removed: {total_stats['colors_removed']}")
            
            # Show final variant counts
            total_size_variants = ProductVariant.objects.filter(variant_type='size').count()
            total_color_variants = ProductVariant.objects.filter(variant_type='color').count()
            self.stdout.write(f"\n📈 Total variants in system:")
            self.stdout.write(f"   Size variants: {total_size_variants}")
            self.stdout.write(f"   Color variants: {total_color_variants}")
        else:
            self.stdout.write("\n💡 This was a DRY RUN. Use without --dry-run to apply changes.")
        
        self.stdout.write("="*60 + "\n")


class CommandAddSizeColorCombos(BaseCommand):
    """Add all size-color combinations as variants"""
    help = 'Add size-color combinations as individual variants'

    def add_arguments(self, parser):
        parser.add_argument('--product-id', type=int, required=True, help='Product ID')
        parser.add_argument('--sizes', type=str, default='XS,S,M,L,XL', help='Sizes (comma-separated)')
        parser.add_argument('--colors', type=str, default='Red,Blue,Black,White', help='Colors (comma-separated)')
        parser.add_argument('--price-adjustment', type=float, default=0, help='Base price adjustment')
        parser.add_argument('--stock', type=int, default=5, help='Stock per combination')
        
    def handle(self, *args, **options):
        product_id = options['product_id']
        sizes = [s.strip() for s in options['sizes'].split(',')]
        colors = [c.strip() for c in options['colors'].split(',')]
        base_adjustment = options['price_adjustment']
        stock = options['stock']
        
        try:
            product = Product.objects.get(id=product_id, is_active=True)
        except Product.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'Product with ID {product_id} not found'))
            return
        
        variants_added = 0
        
        self.stdout.write(f"\n🎨 Creating size-color combinations for {product.name}")
        self.stdout.write(f"   Sizes: {', '.join(sizes)}")
        self.stdout.write(f"   Colors: {', '.join(colors)}")
        self.stdout.write(f"   Total combinations: {len(sizes) * len(colors)}\n")
        
        for size in sizes:
            for color in colors:
                variant_name = f"{size} - {color}"
                variant, created = ProductVariant.objects.get_or_create(
                    product=product,
                    variant_type='other',
                    name='Size-Color',
                    value=variant_name,
                    defaults={
                        'price_adjustment': base_adjustment,
                        'stock_quantity': stock,
                        'is_active': True
                    }
                )
                if created:
                    variants_added += 1
                    self.stdout.write(self.style.SUCCESS(f'  ✅ Added: {variant_name}'))
        
        self.stdout.write(self.style.SUCCESS(f'\n✅ Added {variants_added} size-color combinations to {product.name}'))