# Generated for the Arolana social publishing foundation.

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [
        migrations.CreateModel(
            name="SocialAccount",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("is_active", models.BooleanField(default=True)),
                ("owner_role", models.CharField(choices=[("vendor", "Vendor"), ("provider", "Service Provider"), ("admin", "Arolana Admin")], max_length=20)),
                ("platform", models.CharField(choices=[("youtube", "YouTube"), ("instagram", "Instagram"), ("facebook", "Facebook"), ("tiktok", "TikTok"), ("linkedin", "LinkedIn")], max_length=20)),
                ("external_account_id", models.CharField(blank=True, max_length=255)),
                ("account_name", models.CharField(blank=True, max_length=255)),
                ("account_username", models.CharField(blank=True, max_length=255)),
                ("status", models.CharField(choices=[("connected", "Connected"), ("expired", "Expired"), ("revoked", "Revoked"), ("error", "Error")], db_index=True, default="connected", max_length=20)),
                ("access_token_encrypted", models.TextField(blank=True)),
                ("refresh_token_encrypted", models.TextField(blank=True)),
                ("token_expires_at", models.DateTimeField(blank=True, null=True)),
                ("scopes", models.JSONField(blank=True, default=list)),
                ("platform_metadata", models.JSONField(blank=True, default=dict)),
                ("connected_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("last_verified_at", models.DateTimeField(blank=True, null=True)),
                ("last_error", models.TextField(blank=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="social_publishing_accounts", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="TemporaryVideoLease",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("is_active", models.BooleanField(default=True)),
                ("owner_role", models.CharField(choices=[("vendor", "Vendor"), ("provider", "Service Provider"), ("admin", "Arolana Admin")], max_length=20)),
                ("storage_key", models.CharField(max_length=1000, unique=True)),
                ("original_filename", models.CharField(blank=True, max_length=500)),
                ("file_size", models.PositiveBigIntegerField(default=0)),
                ("mime_type", models.CharField(blank=True, max_length=120)),
                ("expires_at", models.DateTimeField(db_index=True)),
                ("cleanup_completed_at", models.DateTimeField(blank=True, null=True)),
                ("cleanup_error", models.TextField(blank=True)),
                ("owner_user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="temporary_social_video_leases", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="SocialPublication",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("is_active", models.BooleanField(default=True)),
                ("owner_role", models.CharField(choices=[("vendor", "Vendor"), ("provider", "Service Provider"), ("admin", "Arolana Admin")], max_length=20)),
                ("platform", models.CharField(choices=[("youtube", "YouTube"), ("instagram", "Instagram"), ("facebook", "Facebook"), ("tiktok", "TikTok"), ("linkedin", "LinkedIn")], db_index=True, max_length=20)),
                ("object_id", models.PositiveBigIntegerField()),
                ("status", models.CharField(choices=[("pending", "Pending"), ("queued", "Queued"), ("uploading", "Uploading"), ("processing", "Processing"), ("published", "Published"), ("retrying", "Retrying"), ("failed", "Failed"), ("cancelled", "Cancelled")], db_index=True, default="pending", max_length=20)),
                ("external_id", models.CharField(blank=True, max_length=255)),
                ("external_url", models.URLField(blank=True, max_length=1000)),
                ("attempt_count", models.PositiveIntegerField(default=0)),
                ("last_attempt_at", models.DateTimeField(blank=True, null=True)),
                ("next_retry_at", models.DateTimeField(blank=True, null=True)),
                ("published_at", models.DateTimeField(blank=True, null=True)),
                ("error_code", models.CharField(blank=True, max_length=120)),
                ("error_message", models.TextField(blank=True)),
                ("request_metadata", models.JSONField(blank=True, default=dict)),
                ("response_metadata", models.JSONField(blank=True, default=dict)),
                ("content_type", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="contenttypes.contenttype")),
                ("owner_user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="social_publications", to=settings.AUTH_USER_MODEL)),
                ("social_account", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="publications", to="social_publishing.socialaccount")),
            ],
        ),
        migrations.AddConstraint(
            model_name="socialaccount",
            constraint=models.UniqueConstraint(fields=("user", "owner_role", "platform"), name="uniq_social_account_user_role_platform"),
        ),
        migrations.AddIndex(model_name="socialaccount", index=models.Index(fields=["user", "owner_role", "status"], name="social_publ_user_id_952fbe_idx")),
        migrations.AddIndex(model_name="socialaccount", index=models.Index(fields=["platform", "status"], name="social_publ_platfor_171da2_idx")),
        migrations.AddIndex(model_name="temporaryvideolease", index=models.Index(fields=["expires_at", "cleanup_completed_at"], name="social_publ_expires_da3c8c_idx")),
        migrations.AddConstraint(
            model_name="socialpublication",
            constraint=models.UniqueConstraint(fields=("owner_user", "owner_role", "platform", "content_type", "object_id"), name="uniq_social_publication_content_platform"),
        ),
        migrations.AddIndex(model_name="socialpublication", index=models.Index(fields=["status", "next_retry_at"], name="social_publ_status_02f4ea_idx")),
        migrations.AddIndex(model_name="socialpublication", index=models.Index(fields=["content_type", "object_id"], name="social_publ_content_f57b05_idx")),
        migrations.AddIndex(model_name="socialpublication", index=models.Index(fields=["owner_user", "owner_role", "created_at"], name="social_publ_owner_u_b0172e_idx")),
    ]
