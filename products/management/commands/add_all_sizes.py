from django.core.management.base import BaseCommand
from products.models import Product, ProductVariant

class Command(BaseCommand):
    help = 'Add all sizes to a product'
    
    def add_arguments(self, parser):
        parser.add_argument('--product-id', type=int, required=True, help='Product ID to add sizes to')
        parser.add_argument('--price-adjustments', type=str, default='0,5,10,15,20', help='Comma-separated price adjustments for sizes')
        parser.add_argument('--stock', type=int, default=10, help='Stock quantity for each size')
    
    def handle(self, *args, **options):
        product_id = options['product_id']
        stock = options['stock']
        price_adjustments = [float(x) for x in options['price_adjustments'].split(',')]
        
        try:
            product = Product.objects.get(id=product_id, is_active=True)
        except Product.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'Product with ID {product_id} not found'))
            return
        
        all_sizes = ['XS', 'Small', 'Medium', 'Large', 'XL', 'XXL', 'XXXL']
        
        sizes_added = 0
        
        for i, size in enumerate(all_sizes):
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
            if created:
                sizes_added += 1
                self.stdout.write(self.style.SUCCESS(f'  ✅ Added Size: {size} (${price_adj})'))
        
        self.stdout.write(self.style.SUCCESS(f'\n✅ Completed! Added {sizes_added} sizes to {product.name}'))
