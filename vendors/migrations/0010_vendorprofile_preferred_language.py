from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vendors', '0009_vendorprofile_subscription_tier_labels'),
    ]

    operations = [
        migrations.AddField(
            model_name='vendorprofile',
            name='preferred_language',
            field=models.CharField(blank=True, default='english', max_length=20),
        ),
        migrations.AddField(
            model_name='vendorprofile',
            name='preferred_currency',
            field=models.CharField(blank=True, default='NGN', max_length=10),
        ),
    ]
