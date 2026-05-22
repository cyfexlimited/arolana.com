from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('hero_banners', '0005_herobanner_button_colors'),
    ]

    operations = [
        migrations.AddField(
            model_name='herobanner',
            name='enable_slide_link',
            field=models.BooleanField(default=False, help_text='Make the whole banner clickable when customers tap/click the image area.'),
        ),
        migrations.AddField(
            model_name='herobanner',
            name='show_buttons',
            field=models.BooleanField(default=True, help_text='Show CTA buttons. Turn off when the uploaded design already includes button text.'),
        ),
        migrations.AddField(
            model_name='herobanner',
            name='show_content',
            field=models.BooleanField(default=True, help_text='Show the text/content layer over the banner.'),
        ),
        migrations.AddField(
            model_name='herobanner',
            name='show_description',
            field=models.BooleanField(default=True, help_text='Show the description on the banner.'),
        ),
        migrations.AddField(
            model_name='herobanner',
            name='show_subtitle',
            field=models.BooleanField(default=True, help_text='Show the subtitle on the banner.'),
        ),
        migrations.AddField(
            model_name='herobanner',
            name='show_title',
            field=models.BooleanField(default=True, help_text='Show the title on the banner.'),
        ),
        migrations.AddField(
            model_name='herobanner',
            name='slide_link_url',
            field=models.CharField(blank=True, default='', help_text='Optional whole-banner URL. Useful when the uploaded design already contains button artwork.', max_length=500),
        ),
        migrations.AddField(
            model_name='herobanner',
            name='slide_open_behavior',
            field=models.CharField(choices=[('same_page', 'Open in same page'), ('new_page', 'Open in new tab'), ('popup', 'Open in popup modal')], default='same_page', max_length=20),
        ),
    ]
