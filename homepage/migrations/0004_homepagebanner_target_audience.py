from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('homepage', '0003_homepagevideosection_info_position_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='homepagebanner',
            name='target_audience',
            field=models.CharField(
                choices=[
                    ('all', 'Everyone'),
                    ('guests', 'Guests only'),
                    ('authenticated', 'Signed-in users'),
                    ('customers', 'Customers'),
                    ('vendors', 'Vendors'),
                    ('manufacturers', 'Manufacturers'),
                    ('staff', 'Staff/Admin'),
                ],
                default='all',
                help_text='Choose who should see this banner.',
                max_length=20,
            ),
        ),
    ]
