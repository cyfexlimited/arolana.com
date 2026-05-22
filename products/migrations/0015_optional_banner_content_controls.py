from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0014_category_hero_colors_productlistingbanner_cta_colors'),
    ]

    operations = [
        migrations.AddField(
            model_name='category',
            name='show_hero_cta',
            field=models.BooleanField(default=True, help_text='Show the category hero CTA button.'),
        ),
        migrations.AddField(
            model_name='category',
            name='show_hero_eyebrow',
            field=models.BooleanField(default=True, help_text='Show the small category hero eyebrow label.'),
        ),
        migrations.AddField(
            model_name='category',
            name='show_hero_side_image',
            field=models.BooleanField(default=True, help_text='Show the optional category side image.'),
        ),
        migrations.AddField(
            model_name='category',
            name='show_hero_stats',
            field=models.BooleanField(default=True, help_text='Show product/vendor/subcategory metrics on the category hero.'),
        ),
        migrations.AddField(
            model_name='category',
            name='show_hero_subtitle',
            field=models.BooleanField(default=True, help_text='Show the category hero subtitle/description.'),
        ),
        migrations.AddField(
            model_name='category',
            name='show_hero_title',
            field=models.BooleanField(default=True, help_text='Show the category hero title.'),
        ),
        migrations.AddField(
            model_name='productlistingbanner',
            name='show_cta',
            field=models.BooleanField(default=True, help_text='Show the CTA button.'),
        ),
        migrations.AddField(
            model_name='productlistingbanner',
            name='show_eyebrow',
            field=models.BooleanField(default=True, help_text='Show the banner eyebrow label.'),
        ),
        migrations.AddField(
            model_name='productlistingbanner',
            name='show_metrics',
            field=models.BooleanField(default=True, help_text='Show the metric chips on the banner.'),
        ),
        migrations.AddField(
            model_name='productlistingbanner',
            name='show_side_image',
            field=models.BooleanField(default=True, help_text='Show the optional floating side image.'),
        ),
        migrations.AddField(
            model_name='productlistingbanner',
            name='show_subtitle',
            field=models.BooleanField(default=True, help_text='Show the banner subtitle.'),
        ),
        migrations.AddField(
            model_name='productlistingbanner',
            name='show_title',
            field=models.BooleanField(default=True, help_text='Show the banner title.'),
        ),
    ]
