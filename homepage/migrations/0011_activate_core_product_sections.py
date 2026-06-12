from django.db import migrations


def activate_core_product_sections(apps, schema_editor):
    HomepageSection = apps.get_model('homepage', 'HomepageSection')
    HomepageSection.objects.filter(
        section_type__in=('featured', 'new', 'bestsellers', 'trending'),
    ).update(is_active=True)


class Migration(migrations.Migration):
    dependencies = [
        ('homepage', '0010_ensure_core_product_sections'),
    ]

    operations = [
        migrations.RunPython(
            activate_core_product_sections,
            migrations.RunPython.noop,
        ),
    ]
