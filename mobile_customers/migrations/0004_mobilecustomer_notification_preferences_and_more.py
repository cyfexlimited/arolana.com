from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("mobile_customers", "0003_mobilecustomer_profile_image"),
    ]

    operations = [
        migrations.AddField(
            model_name="mobilecustomer",
            name="notification_preferences",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="mobilecustomer",
            name="preferred_language",
            field=models.CharField(default="english", max_length=24),
        ),
    ]
