from django.core.management.base import BaseCommand
from products.models import Product, ProductVariant

class Command(BaseCommand):
    help = 'Add size and color variants to products'
    
    def add_arguments(self, parser):
        parser.add_argument('--product-id', type=int, help='Product ID to add variants to')
        parser.add_argument('--all', action='store_true', help='Add variants to all products')
    
    def handle(self, *args, **options):
        sizes = ['XS', 'Small', 'Medium', 'Large', 'XL', 'XXL']
        colors = ['Red', 'Blue', 'Green', 'Black', 'White', 'Yellow', 'Purple', 'Orange']
        
        if options['product_id']:
            products = Product.objects.filter(id=options['product_id'], is_active=True)
        elif options['all']:
            products = Product.objects.filter(is_active=True)
        else:
            self.stdout.write(self.style.ERROR('Please specify --product-id or --all'))
            return
        
        for product in products:
            # Add size variants
            for i, size in enumerate(sizes[:4]):  # First 4 sizes
                obj, created = ProductVariant.objects.get_or_create(
                    product=product,
                    name='Size',
                    value=size,
                    defaults={
                        'price_adjustment': i * 5.00,
                        'stock_quantity': 10,
                        'is_active': True
                    }
                )
                if created:
                    self.stdout.write(self.style.SUCCESS(f'  Added Size: {size} to {product.name}'))
            
            # Add color variants
            for color in colors[:4]:  # First 4 colors
                obj, created = ProductVariant.objects.get_or_create(
                    product=product,
                    name='Color',
                    value=color,
                    defaults={
                        'price_adjustment': 0,
                        'stock_quantity': 15,
                        'is_active': True
                    }
                )
                if created:
                    self.stdout.write(self.style.SUCCESS(f'  Added Color: {color} to {product.name}'))
        
        self.stdout.write(self.style.SUCCESS(f'\n✅ Completed! Added variants to {products.count()} products'))
