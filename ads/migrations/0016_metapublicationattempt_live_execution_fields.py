from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("ads", "0015_metaverificationreceipt_metapublicationattempt")]

    operations = [
        migrations.AlterField(
            model_name="metapublicationattempt",
            name="status",
            field=models.CharField(
                choices=[("ready", "Ready"), ("stale", "Stale"), ("failed", "Failed"), ("completed", "Completed")],
                db_index=True,
                default="ready",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="metapublicationattempt",
            name="stage",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"), ("creating_campaign", "Creating campaign"),
                    ("campaign_created", "Campaign created"), ("creating_adset", "Creating ad set"),
                    ("adset_created", "Ad set created"), ("creating_creative", "Creating creative"),
                    ("creative_created", "Creative created"), ("creating_ad", "Creating ad"),
                    ("completed", "Completed"), ("failed", "Failed"),
                ],
                db_index=True,
                default="pending",
                max_length=30,
            ),
        ),
        migrations.AddField(model_name="metapublicationattempt", name="external_campaign_id", field=models.CharField(blank=True, max_length=200)),
        migrations.AddField(model_name="metapublicationattempt", name="external_adset_id", field=models.CharField(blank=True, max_length=200)),
        migrations.AddField(model_name="metapublicationattempt", name="external_creative_id", field=models.CharField(blank=True, max_length=200)),
        migrations.AddField(model_name="metapublicationattempt", name="external_ad_id", field=models.CharField(blank=True, max_length=200)),
        migrations.AddField(model_name="metapublicationattempt", name="failure_code", field=models.CharField(blank=True, max_length=80)),
        migrations.AddField(model_name="metapublicationattempt", name="failure_message", field=models.CharField(blank=True, max_length=240)),
    ]
