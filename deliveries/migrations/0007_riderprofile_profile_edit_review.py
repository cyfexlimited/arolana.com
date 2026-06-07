from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("deliveries", "0006_riderprofile_payout_bank"),
    ]

    operations = [
        migrations.AddField(
            model_name="riderprofile",
            name="about",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="riderprofile",
            name="profile_edit_available_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="riderprofile",
            name="profile_edit_pending_data",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="riderprofile",
            name="profile_edit_requested_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="riderprofile",
            name="profile_edit_status",
            field=models.CharField(
                choices=[
                    ("clear", "No Pending Edit"),
                    ("pending_admin_review", "Pending Admin Review"),
                    ("approved", "Approved"),
                    ("rejected", "Rejected"),
                ],
                db_index=True,
                default="clear",
                max_length=30,
            ),
        ),
    ]
