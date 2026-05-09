from django.db import migrations
from django.utils.text import slugify

def fix_slugs(apps, schema_editor):
    Product = apps.get_model('products', 'Product')
    for product in Product.objects.all():
        clean_slug = slugify(product.name)
        
        # Handle potential duplicates
        counter = 1
        original_slug = clean_slug
        while Product.objects.filter(slug=clean_slug).exclude(pk=product.pk).exists():
            clean_slug = f"{original_slug}-{counter}"
            counter += 1
        
        if product.slug != clean_slug:
            product.slug = clean_slug
            product.save(update_fields=['slug'])

class Migration(migrations.Migration):
    dependencies = [
        ('products', '0001_initial'),  # ← Replace with your actual last migration name
    ]

    operations = [
        migrations.RunPython(fix_slugs, migrations.RunPython.noop),
    ]