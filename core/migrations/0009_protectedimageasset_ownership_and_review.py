from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0008_contenttranslation"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="protectedimageasset",
            name="original_filename",
            field=models.CharField(blank=True, max_length=500),
        ),
        migrations.AddField(
            model_name="protectedimageasset",
            name="duplicate_type",
            field=models.CharField(
                blank=True,
                choices=[
                    ("", "Not a Duplicate"),
                    ("exact", "Exact Duplicate"),
                    ("near", "Likely / Near Duplicate"),
                ],
                db_index=True,
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="protectedimageasset",
            name="duplicate_status",
            field=models.CharField(
                choices=[
                    ("original", "Original"),
                    ("same_vendor_reuse", "Same Vendor Reuse"),
                    ("needs_review", "Needs Review"),
                    ("approved", "Admin Allowed"),
                    ("rejected", "Rejected"),
                ],
                db_index=True,
                default="original",
                max_length=30,
            ),
        ),
        migrations.AddField(
            model_name="protectedimageasset",
            name="perceptual_distance",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="protectedimageasset",
            name="source_product_id",
            field=models.PositiveBigIntegerField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="protectedimageasset",
            name="uploader",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="uploaded_protected_images",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="protectedimageasset",
            name="vendor",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="vendor_protected_images",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
