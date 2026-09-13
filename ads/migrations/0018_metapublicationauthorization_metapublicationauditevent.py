from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [("ads", "0017_metapermissionreceipt")]
    operations = [
        migrations.CreateModel(name="MetaPublicationAuthorization", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)), ("is_active", models.BooleanField(default=True)),
            ("plan_fingerprint", models.CharField(db_index=True, max_length=64)),
            ("page_id", models.CharField(max_length=100)),
            ("status", models.CharField(choices=[("authorized", "Authorized"), ("revoked", "Revoked")], db_index=True, default="authorized", max_length=20)),
            ("authorized_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)), ("expires_at", models.DateTimeField(db_index=True)), ("revoked_at", models.DateTimeField(blank=True, null=True)),
            ("advertiser_identity", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="meta_publication_authorizations", to="ads.advertiseridentity")),
            ("external_account", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="meta_publication_authorizations", to="ads.externaladvertisingaccount")),
            ("campaign", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="meta_publication_authorizations", to="ads.adcampaign")),
            ("creative", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="meta_publication_authorizations", to="ads.adcreative")),
            ("publication_attempt", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="authorizations", to="ads.metapublicationattempt")),
            ("authorized_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="meta_publication_authorizations", to="accounts.user")),
        ], options={"indexes": [models.Index(fields=["publication_attempt", "status", "expires_at"], name="ads_metapu_publica_7ea142_idx")] }),
        migrations.CreateModel(name="MetaPublicationAuditEvent", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)), ("is_active", models.BooleanField(default=True)),
            ("event_type", models.CharField(choices=[("authorization_created", "Authorization Created"), ("authorization_revoked", "Authorization Revoked"), ("execute_blocked", "Execute Blocked"), ("execution_started", "Execution Started"), ("execution_stage_changed", "Execution Stage Changed"), ("execution_completed", "Execution Completed"), ("execution_failed", "Execution Failed")], db_index=True, max_length=40)),
            ("stage", models.CharField(blank=True, max_length=40)), ("reason_code", models.CharField(blank=True, max_length=80)),
            ("advertiser_identity", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="meta_publication_audit_events", to="ads.advertiseridentity")),
            ("creative", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="meta_publication_audit_events", to="ads.adcreative")),
            ("publication_attempt", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="audit_events", to="ads.metapublicationattempt")),
            ("actor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="meta_publication_audit_events", to="accounts.user")),
        ]),
    ]
