from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('homepage', '0005_homepagebanner_background_fit_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='HomepageVendorSection',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('title', models.CharField(max_length=200)),
                ('section_type', models.CharField(choices=[('verified_vendors', 'Verified Vendors'), ('factory_direct_manufacturers', 'Factory Direct Manufacturers'), ('top_retailers', 'Top Retailers'), ('distributors_wholesalers', 'Distributors & Wholesalers'), ('service_providers', 'Service Providers'), ('custom', 'Custom')], db_index=True, default='verified_vendors', max_length=40)),
                ('vendor_type_filter', models.CharField(blank=True, choices=[('', 'Any vendor type'), ('manufacturer', 'Manufacturer'), ('distributor', 'Distributor'), ('wholesaler', 'Wholesaler'), ('retailer', 'Retailer'), ('service_provider', 'Service Provider'), ('distributor_wholesaler', 'Distributor + Wholesaler')], default='', max_length=40)),
                ('verified_only', models.BooleanField(default=True)),
                ('manufacturer_only', models.BooleanField(default=False, help_text='Hard lock this section to vendor_type=manufacturer.')),
                ('max_items', models.PositiveIntegerField(default=12)),
                ('sort_order', models.IntegerField(default=0)),
                ('empty_state_text', models.CharField(blank=True, default='No vendors yet.', max_length=255)),
                ('is_active', models.BooleanField(default=True)),
            ],
            options={
                'verbose_name': 'Homepage Vendor Section',
                'verbose_name_plural': 'Homepage Vendor Sections',
                'ordering': ['sort_order', 'title'],
            },
        ),
        migrations.AddIndex(
            model_name='homepagevendorsection',
            index=models.Index(fields=['section_type', 'is_active'], name='homepage_ho_section_8a8a7d_idx'),
        ),
        migrations.AddIndex(
            model_name='homepagevendorsection',
            index=models.Index(fields=['sort_order', 'is_active'], name='homepage_ho_sort_or_0e4bd5_idx'),
        ),
    ]
