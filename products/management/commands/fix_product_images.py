from django.core.management.base import BaseCommand
from products.models import Product
from django.core.files import File
import os
import requests
from io import BytesIO

class Command(BaseCommand):
    help = 'Fix product images by downloading from URLs'
    
    def handle(self, *args, **kwargs):
        image_urls = {
            'SNY-WH1000XM5': 'https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=600',
            'CAN-R5': 'https://images.unsplash.com/photo-1526170375885-4d8ecf77b99f?w=600',
            'APL-MBP16-M3': 'https://images.unsplash.com/photo-1517336714731-489689fd1ca8?w=600',
            'BOS-QC-ULTRA': 'https://images.unsplash.com/photo-1583394838336-acd977736f90?w=600',
            'SNY-A7IV': 'https://images.unsplash.com/photo-1502920917128-1aa500764cbd?w=600',
            'APL-AIRPODS-PRO2': 'https://images.unsplash.com/photo-1606841837239-c5a1a4a07af7?w=600',
        }
        
        for sku, url in image_urls.items():
            try:
                product = Product.objects.get(sku=sku)
                response = requests.get(url)
                if response.status_code == 200:
                    img_temp = BytesIO(response.content)
                    img_temp.seek(0)
                    filename = f"{sku}.jpg"
                    product.main_image.save(filename, File(img_temp), save=True)
                    self.stdout.write(self.style.SUCCESS(f'✅ Fixed image for {product.name}'))
                else:
                    self.stdout.write(self.style.ERROR(f'❌ Failed to download image for {sku}'))
            except Product.DoesNotExist:
                self.stdout.write(self.style.WARNING(f'⚠️ Product {sku} not found'))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'❌ Error: {str(e)}'))
        
        self.stdout.write(self.style.SUCCESS('\n🎉 All product images fixed!'))
