from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("deliveries", "0004_deliveryrequest_is_ready_for_rider"),
    ]

    operations = [
        migrations.AddField(
            model_name="riderprofile",
            name="dashboard_image",
            field=models.ImageField(blank=True, null=True, upload_to="delivery/riders/banners/"),
        ),
        migrations.AddField(
            model_name="riderprofile",
            name="notification_preferences",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="riderprofile",
            name="preferred_language",
            field=models.CharField(blank=True, default="english", max_length=40),
        ),
    ]
