from django.db import migrations, models


def seed_product_detail_config(apps, schema_editor):
    ProductDetailSection = apps.get_model('products', 'ProductDetailSection')
    ProductDetailFieldConfig = apps.get_model('products', 'ProductDetailFieldConfig')
    ProductVariantTypeConfig = apps.get_model('products', 'ProductVariantTypeConfig')

    sections = [
        ('overview', 'Overview'),
        ('specifications', 'Specifications'),
        ('variants', 'Variants'),
        ('wholesale_pricing', 'Wholesale Pricing'),
        ('moq', 'MOQ'),
        ('product_images', 'Product Images'),
        ('videos', 'Videos'),
        ('brochure', 'PDF Brochure / Manual'),
        ('certifications', 'Certifications'),
        ('accessories', 'Accessories'),
        ('frequently_bought_together', 'Frequently Bought Together'),
        ('related_products', 'Related Products'),
        ('reviews', 'Reviews'),
        ('qa', 'Q&A'),
        ('shipping', 'Shipping'),
        ('warranty', 'Warranty'),
        ('vendor_profile', 'Vendor / Manufacturer Profile'),
        ('factory_details', 'Factory Details'),
        ('rfq', 'RFQ'),
        ('recently_viewed', 'Recently Viewed'),
        ('recommended_products', 'Recommended Products'),
    ]
    for order, (key, title) in enumerate(sections):
        ProductDetailSection.objects.get_or_create(
            key=key,
            defaults={'title': title, 'display_order': order * 10},
        )

    fields = [
        ('brand', 'Brand'),
        ('model_number', 'Model Number'),
        ('sku', 'SKU'),
        ('manufacturer_sku', 'Manufacturer SKU'),
        ('condition', 'Product Condition'),
        ('category', 'Category'),
        ('subcategory', 'Subcategory'),
        ('minimum_order_quantity', 'MOQ'),
        ('price', 'Retail Price'),
        ('wholesale_price', 'Wholesale Price'),
        ('bulk_price', 'Bulk Price'),
        ('stock_quantity', 'Stock Quantity'),
        ('country_of_origin', 'Country of Origin'),
        ('lead_time_days', 'Lead Time'),
        ('warranty', 'Warranty'),
        ('shipping_weight', 'Shipping Weight'),
        ('package_dimensions', 'Package Dimensions'),
        ('video_type', 'Video Type'),
        ('youtube_url', 'YouTube URL'),
        ('local_video', 'Local Video'),
        ('manufacturer_address', 'Manufacturer Address'),
        ('description', 'Description'),
        ('specifications', 'Specifications'),
        ('certifications', 'Certifications'),
        ('accessories', 'Accessories'),
        ('manual_pdf', 'PDF Brochure'),
        ('images', 'Images'),
        ('variants', 'Variants'),
    ]
    for order, (key, label) in enumerate(fields):
        ProductDetailFieldConfig.objects.get_or_create(
            key=key,
            defaults={'label': label, 'display_order': order * 10},
        )

    variant_types = [
        ('color', 'Color'),
        ('size', 'Size'),
        ('material', 'Material'),
        ('style', 'Style'),
        ('pattern', 'Pattern'),
        ('finish', 'Finish'),
        ('capacity', 'Capacity'),
        ('other', 'Other'),
    ]
    for order, (key, label) in enumerate(variant_types):
        ProductVariantTypeConfig.objects.get_or_create(
            key=key,
            defaults={'label': label, 'display_order': order * 10},
        )


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0018_productwholesaletier_product_bulk_price_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='ProductDetailFieldConfig',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('is_active', models.BooleanField(default=True)),
                ('key', models.CharField(choices=[('brand', 'Brand'), ('model_number', 'Model Number'), ('sku', 'SKU'), ('manufacturer_sku', 'Manufacturer SKU'), ('condition', 'Product Condition'), ('category', 'Category'), ('subcategory', 'Subcategory'), ('minimum_order_quantity', 'MOQ'), ('price', 'Retail Price'), ('wholesale_price', 'Wholesale Price'), ('bulk_price', 'Bulk Price'), ('stock_quantity', 'Stock Quantity'), ('country_of_origin', 'Country of Origin'), ('lead_time_days', 'Lead Time'), ('warranty', 'Warranty'), ('shipping_weight', 'Shipping Weight'), ('package_dimensions', 'Package Dimensions'), ('video_type', 'Video Type'), ('youtube_url', 'YouTube URL'), ('local_video', 'Local Video'), ('manufacturer_address', 'Manufacturer Address'), ('description', 'Description'), ('specifications', 'Specifications'), ('certifications', 'Certifications'), ('accessories', 'Accessories'), ('manual_pdf', 'PDF Brochure'), ('images', 'Images'), ('variants', 'Variants')], max_length=80, unique=True)),
                ('label', models.CharField(max_length=120)),
                ('is_enabled', models.BooleanField(db_index=True, default=True)),
                ('is_required', models.BooleanField(default=False)),
                ('display_order', models.IntegerField(default=0)),
                ('help_text', models.CharField(blank=True, max_length=255)),
            ],
            options={'verbose_name': 'Product Detail Field Config', 'verbose_name_plural': 'Product Detail Field Configs', 'ordering': ['display_order', 'label']},
        ),
        migrations.CreateModel(
            name='ProductDetailSection',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('is_active', models.BooleanField(default=True)),
                ('key', models.CharField(choices=[('overview', 'Overview'), ('specifications', 'Specifications'), ('variants', 'Variants'), ('wholesale_pricing', 'Wholesale Pricing'), ('moq', 'MOQ'), ('product_images', 'Product Images'), ('videos', 'Videos'), ('brochure', 'PDF Brochure / Manual'), ('certifications', 'Certifications'), ('accessories', 'Accessories'), ('frequently_bought_together', 'Frequently Bought Together'), ('related_products', 'Related Products'), ('reviews', 'Reviews'), ('qa', 'Q&A'), ('shipping', 'Shipping'), ('warranty', 'Warranty'), ('vendor_profile', 'Vendor / Manufacturer Profile'), ('factory_details', 'Factory Details'), ('rfq', 'RFQ'), ('recently_viewed', 'Recently Viewed'), ('recommended_products', 'Recommended Products')], max_length=60, unique=True)),
                ('title', models.CharField(max_length=120)),
                ('is_enabled', models.BooleanField(db_index=True, default=True)),
                ('display_order', models.IntegerField(default=0)),
                ('mobile_enabled', models.BooleanField(default=True)),
                ('web_enabled', models.BooleanField(default=True)),
            ],
            options={'verbose_name': 'Product Detail Section', 'verbose_name_plural': 'Product Detail Sections', 'ordering': ['display_order', 'title']},
        ),
        migrations.CreateModel(
            name='ProductVariantTypeConfig',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('key', models.CharField(max_length=40, unique=True)),
                ('label', models.CharField(max_length=80)),
                ('display_order', models.IntegerField(default=0)),
                ('is_active', models.BooleanField(default=True)),
            ],
            options={'verbose_name': 'Product Variant Type', 'verbose_name_plural': 'Product Variant Types', 'ordering': ['display_order', 'label']},
        ),
        migrations.RunPython(seed_product_detail_config, migrations.RunPython.noop),
    ]
