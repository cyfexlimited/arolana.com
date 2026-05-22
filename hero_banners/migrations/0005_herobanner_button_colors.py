from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('hero_banners', '0004_herobanner_article_button_text_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='herobanner',
            name='article_button_background_color',
            field=models.CharField(blank=True, default='', help_text='Optional custom article button background color.', max_length=20),
        ),
        migrations.AddField(
            model_name='herobanner',
            name='article_button_border_color',
            field=models.CharField(blank=True, default='', help_text='Optional custom article button border color.', max_length=20),
        ),
        migrations.AddField(
            model_name='herobanner',
            name='article_button_text_color',
            field=models.CharField(blank=True, default='', help_text='Optional custom article button text color.', max_length=20),
        ),
        migrations.AddField(
            model_name='herobanner',
            name='button1_background_color',
            field=models.CharField(blank=True, default='', help_text='Optional custom button background color, e.g. #2563eb.', max_length=20),
        ),
        migrations.AddField(
            model_name='herobanner',
            name='button1_border_color',
            field=models.CharField(blank=True, default='', help_text='Optional custom border color.', max_length=20),
        ),
        migrations.AddField(
            model_name='herobanner',
            name='button1_text_color',
            field=models.CharField(blank=True, default='', help_text='Optional custom button text color, e.g. #ffffff.', max_length=20),
        ),
        migrations.AddField(
            model_name='herobanner',
            name='button2_background_color',
            field=models.CharField(blank=True, default='', help_text='Optional custom button background color.', max_length=20),
        ),
        migrations.AddField(
            model_name='herobanner',
            name='button2_border_color',
            field=models.CharField(blank=True, default='', help_text='Optional custom border color.', max_length=20),
        ),
        migrations.AddField(
            model_name='herobanner',
            name='button2_text_color',
            field=models.CharField(blank=True, default='', help_text='Optional custom button text color.', max_length=20),
        ),
        migrations.AddField(
            model_name='herobanner',
            name='button3_background_color',
            field=models.CharField(blank=True, default='', help_text='Optional custom button background color.', max_length=20),
        ),
        migrations.AddField(
            model_name='herobanner',
            name='button3_border_color',
            field=models.CharField(blank=True, default='', help_text='Optional custom border color.', max_length=20),
        ),
        migrations.AddField(
            model_name='herobanner',
            name='button3_text_color',
            field=models.CharField(blank=True, default='', help_text='Optional custom button text color.', max_length=20),
        ),
    ]
