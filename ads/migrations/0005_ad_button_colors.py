from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ads', '0004_adbanner_article_open_behavior_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='adbanner',
            name='cta_background_color',
            field=models.CharField(blank=True, default='', help_text='Optional CTA button background color.', max_length=20),
        ),
        migrations.AddField(
            model_name='adbanner',
            name='cta_text_color',
            field=models.CharField(blank=True, default='', help_text='Optional CTA button text color.', max_length=20),
        ),
        migrations.AddField(
            model_name='adcreative',
            name='cta_background_color',
            field=models.CharField(blank=True, default='', help_text='Optional CTA button background color.', max_length=20),
        ),
        migrations.AddField(
            model_name='adcreative',
            name='cta_text_color',
            field=models.CharField(blank=True, default='', help_text='Optional CTA button text color.', max_length=20),
        ),
        migrations.AddField(
            model_name='advertisement',
            name='button_background_color',
            field=models.CharField(blank=True, default='', help_text='Optional button background color.', max_length=20),
        ),
        migrations.AddField(
            model_name='advertisement',
            name='button_text_color',
            field=models.CharField(blank=True, default='', help_text='Optional button text color.', max_length=20),
        ),
    ]
