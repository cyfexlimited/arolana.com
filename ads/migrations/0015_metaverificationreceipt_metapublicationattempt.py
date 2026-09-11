from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [("ads", "0014_advertisingadresource")]

    operations = [
        migrations.CreateModel(
            name="MetaVerificationReceipt",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("is_active", models.BooleanField(default=True)),
                ("context_fingerprint", models.CharField(db_index=True, max_length=64)),
                ("verified_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ("expires_at", models.DateTimeField(db_index=True)),
                ("creative", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="meta_verification_receipts", to="ads.adcreative")),
                ("external_account", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="meta_verification_receipts", to="ads.externaladvertisingaccount")),
            ],
            options={"indexes": [models.Index(fields=["creative", "external_account", "expires_at"], name="ads_metaver_creativ_09c3a4_idx")]},
        ),
        migrations.CreateModel(
            name="MetaPublicationAttempt",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("is_active", models.BooleanField(default=True)),
                ("mode", models.CharField(choices=[("dry_run", "Dry run")], default="dry_run", max_length=20)),
                ("status", models.CharField(choices=[("ready", "Ready"), ("stale", "Stale")], db_index=True, default="ready", max_length=20)),
                ("plan_fingerprint", models.CharField(db_index=True, max_length=64)),
                ("attempt_count", models.PositiveIntegerField(default=0)),
                ("last_attempted_at", models.DateTimeField(blank=True, null=True)),
                ("ad_resource", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="meta_publication_attempts", to="ads.advertisingadresource")),
                ("advertiser_identity", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="meta_publication_attempts", to="ads.advertiseridentity")),
                ("campaign", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="meta_publication_attempts", to="ads.adcampaign")),
                ("creative", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="meta_publication_attempts", to="ads.adcreative")),
                ("creative_preparation", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="meta_publication_attempts", to="ads.advertisingcreativepreparation")),
                ("execution", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="meta_publication_attempts", to="ads.adchannelexecution")),
                ("external_account", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="meta_publication_attempts", to="ads.externaladvertisingaccount")),
                ("verification_receipt", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="publication_attempts", to="ads.metaverificationreceipt")),
            ],
            options={"indexes": [models.Index(fields=["external_account", "status"], name="ads_metapub_externa_aeb2ff_idx")]},
        ),
        migrations.AddConstraint(model_name="metapublicationattempt", constraint=models.UniqueConstraint(fields=("creative", "external_account", "plan_fingerprint"), name="unique_meta_publication_dry_run_plan")),
    ]
