from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("ads", "0013_advertisingcreativepreparation")]

    operations = [
        migrations.CreateModel(
            name="AdvertisingAdResource",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("is_active", models.BooleanField(default=True)),
                ("provider", models.CharField(choices=[("meta", "Meta"), ("google", "Google"), ("tiktok", "TikTok"), ("linkedin", "LinkedIn"), ("other", "Other")], db_index=True, max_length=30)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("prepared", "Prepared"), ("failed", "Failed")], db_index=True, default="pending", max_length=20)),
                ("payload_fingerprint", models.CharField(db_index=True, max_length=64)),
                ("mock_resource_id", models.CharField(blank=True, max_length=200)),
                ("failure_code", models.CharField(blank=True, max_length=80)),
                ("failure_message", models.CharField(blank=True, max_length=240)),
                ("attempt_count", models.PositiveIntegerField(default=0)),
                ("last_attempted_at", models.DateTimeField(blank=True, null=True)),
                ("campaign", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="provider_ad_resources", to="ads.adcampaign")),
                ("creative", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="provider_ad_resources", to="ads.adcreative")),
                ("creative_preparation", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="ad_resources", to="ads.advertisingcreativepreparation")),
                ("execution", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="ad_resources", to="ads.adchannelexecution")),
                ("external_account", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="ad_resources", to="ads.externaladvertisingaccount")),
            ],
            options={"indexes": [models.Index(fields=["external_account", "provider", "status"], name="ads_adverti_externa_c6cbee_idx")]},
        ),
        migrations.AddConstraint(model_name="advertisingadresource", constraint=models.UniqueConstraint(fields=("execution", "creative_preparation", "payload_fingerprint"), name="unique_ads_ad_resource_payload")),
    ]
