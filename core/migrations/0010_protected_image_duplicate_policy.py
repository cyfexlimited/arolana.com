from django.db import migrations, models


def rename_legacy_status(apps, schema_editor):
    ProtectedImageAsset = apps.get_model("core", "ProtectedImageAsset")
    ProtectedImageAsset.objects.filter(duplicate_status="approved").update(
        duplicate_status="admin_override"
    )
    ProtectedImageAsset.objects.filter(
        duplicate_status="needs_review",
        duplicate_type="exact",
    ).update(duplicate_status="exact_duplicate_cross_vendor")
    ProtectedImageAsset.objects.filter(
        duplicate_status="needs_review",
        duplicate_type="near",
    ).update(duplicate_status="near_duplicate_cross_vendor")


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0009_protectedimageasset_ownership_and_review"),
    ]

    operations = [
        migrations.AlterField(
            model_name="protectedimageasset",
            name="duplicate_status",
            field=models.CharField(
                choices=[
                    ("original", "Original"),
                    ("same_vendor_reuse", "Same Vendor Reuse"),
                    ("exact_duplicate_cross_vendor", "Exact Cross-Vendor Duplicate"),
                    ("near_duplicate_cross_vendor", "Near Cross-Vendor Duplicate"),
                    ("needs_review", "Needs Review"),
                    ("admin_override", "Admin Allowed"),
                    ("rejected", "Rejected"),
                ],
                db_index=True,
                default="original",
                max_length=30,
            ),
        ),
        migrations.RunPython(rename_legacy_status, migrations.RunPython.noop),
    ]
