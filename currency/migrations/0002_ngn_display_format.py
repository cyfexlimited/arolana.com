from django.db import migrations


def set_ngn_display_format(apps, schema_editor):
    Currency = apps.get_model('currency', 'Currency')
    Currency.objects.filter(code='NGN').update(
        decimal_places=2,
        thousands_separator='.',
        decimal_separator='.',
        symbol_position='left',
    )


def restore_ngn_display_format(apps, schema_editor):
    Currency = apps.get_model('currency', 'Currency')
    Currency.objects.filter(code='NGN').update(
        decimal_places=2,
        thousands_separator=',',
        decimal_separator='.',
        symbol_position='left',
    )


class Migration(migrations.Migration):

    dependencies = [
        ('currency', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(set_ngn_display_format, restore_ngn_display_format),
    ]
