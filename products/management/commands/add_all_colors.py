from django.core.management.base import BaseCommand
from products.models import Product, ProductVariant

class Command(BaseCommand):
    help = 'Add all colors to a product'
    
    def add_arguments(self, parser):
        parser.add_argument('--product-id', type=int, required=True, help='Product ID to add colors to')
        parser.add_argument('--price-adjustment', type=float, default=0, help='Price adjustment for all colors')
        parser.add_argument('--stock', type=int, default=10, help='Stock quantity for each color')
    
    def handle(self, *args, **options):
        product_id = options['product_id']
        price_adjustment = options['price_adjustment']
        stock = options['stock']
        
        try:
            product = Product.objects.get(id=product_id, is_active=True)
        except Product.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'Product with ID {product_id} not found'))
            return
        
        # Complete color list
        all_colors = [
            'Red', 'Blue', 'Green', 'Black', 'White', 'Yellow', 'Purple', 'Orange',
            'Pink', 'Brown', 'Gray', 'Navy', 'Cyan', 'Magenta', 'Lime', 'Olive',
            'Maroon', 'Teal', 'Gold', 'Silver', 'Indigo', 'Violet', 'Coral', 'Salmon',
            'Turquoise', 'Lavender', 'Khaki', 'Plum', 'Peach', 'Mint', 'Lavender', 'Beige',
            'Crimson', 'Aqua', 'Fuchsia', 'Tan', 'Ivory', 'Champagne', 'Bronze', 'Copper'
        ]
        
        colors_added = 0
        colors_skipped = 0
        
        for color in all_colors:
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
            if created:
                colors_added += 1
                self.stdout.write(self.style.SUCCESS(f'  ✅ Added Color: {color}'))
            else:
                colors_skipped += 1
        
        self.stdout.write(self.style.SUCCESS(f'\n✅ Completed! Added {colors_added} colors to {product.name}'))
        self.stdout.write(f'   Skipped {colors_skipped} existing colors')
        self.stdout.write(f'   Total colors now: {product.variants.filter(variant_type="color").count()}')
