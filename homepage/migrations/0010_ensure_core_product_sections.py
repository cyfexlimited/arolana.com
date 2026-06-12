from django.db import migrations


def ensure_core_product_sections(apps, schema_editor):
    HomepageSection = apps.get_model('homepage', 'HomepageSection')
    section_defaults = (
        ('trending', 'Trending Deals', 'editorial', 10),
        ('featured', 'Featured Products', 'compact', 20),
        ('new', 'New Arrivals', 'market_grid', 30),
        ('bestsellers', 'Best Sellers', 'carousel', 40),
    )

    for section_type, title, layout_style, display_order in section_defaults:
        if HomepageSection.objects.filter(section_type=section_type).exists():
            continue
        HomepageSection.objects.create(
            title=title,
            section_type=section_type,
            layout_style=layout_style,
            sort_mode='automatic',
            display_order=display_order,
            products_limit=8,
            view_all_url='/products/',
            view_all_text='View All',
            show_view_all=True,
            fill_automatically=True,
            use_subscription_priority=True,
            is_active=True,
        )


class Migration(migrations.Migration):
    dependencies = [
        ('homepage', '0009_homepagesection_accent_color_and_more'),
    ]

    operations = [
        migrations.RunPython(
            ensure_core_product_sections,
            migrations.RunPython.noop,
        ),
    ]
