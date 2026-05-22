from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0013_product_manufacturer_sku'),
    ]

    operations = [
        migrations.AddField(
            model_name='category',
            name='hero_accent_color',
            field=models.CharField(blank=True, default='', help_text='Optional category hero accent color for badges and stats.', max_length=20),
        ),
        migrations.AddField(
            model_name='category',
            name='hero_background_color',
            field=models.CharField(blank=True, default='', help_text='Optional category hero background color, used behind or instead of an image. Example: #0f172a', max_length=20),
        ),
        migrations.AddField(
            model_name='category',
            name='hero_button_background_color',
            field=models.CharField(blank=True, default='', help_text='Optional category hero button background color.', max_length=20),
        ),
        migrations.AddField(
            model_name='category',
            name='hero_button_text_color',
            field=models.CharField(blank=True, default='', help_text='Optional category hero button text color.', max_length=20),
        ),
        migrations.AddField(
            model_name='category',
            name='hero_text_color',
            field=models.CharField(blank=True, default='', help_text='Optional category hero text color. Example: #ffffff', max_length=20),
        ),
        migrations.AddField(
            model_name='productlistingbanner',
            name='cta_background_color',
            field=models.CharField(blank=True, default='', help_text='Optional CTA button background color.', max_length=20),
        ),
        migrations.AddField(
            model_name='productlistingbanner',
            name='cta_text_color',
            field=models.CharField(blank=True, default='', help_text='Optional CTA button text color.', max_length=20),
        ),
    ]
