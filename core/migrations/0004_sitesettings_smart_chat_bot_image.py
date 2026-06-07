from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_sitesettings_footer_logo_height_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='sitesettings',
            name='smart_chat_bot_image',
            field=models.ImageField(
                blank=True,
                help_text='Smart Chat bot avatar (recommended: square PNG or WebP, at least 256x256).',
                null=True,
                upload_to='settings/smart-chat/',
            ),
        ),
    ]
