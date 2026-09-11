from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("ads", "0016_metapublicationattempt_live_execution_fields")]

    operations = [
        migrations.CreateModel(
            name="MetaPermissionReceipt",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("is_active", models.BooleanField(default=True)),
                ("credential_version", models.PositiveIntegerField()),
                ("context_fingerprint", models.CharField(db_index=True, max_length=64)),
                ("status", models.CharField(choices=[("ready", "Ready"), ("reconnect_required", "Reconnect required"), ("not_verified", "Not verified"), ("unavailable", "Unavailable")], db_index=True, default="not_verified", max_length=30)),
                ("granted_permissions", models.JSONField(blank=True, default=list)),
                ("missing_permissions", models.JSONField(blank=True, default=list)),
                ("checked_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("invalidated_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("advertiser_identity", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="meta_permission_receipts", to="ads.advertiseridentity")),
                ("external_account", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="meta_permission_receipt", to="ads.externaladvertisingaccount")),
            ],
        ),
    ]
