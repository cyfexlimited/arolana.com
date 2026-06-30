from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("products", "0025_alter_accessory_image_alter_brand_logo_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="product",
            name="approval_status",
            field=models.CharField(
                choices=[
                    ("draft", "Draft"),
                    ("pending", "Pending Approval"),
                    ("approved", "Approved"),
                    ("rejected", "Rejected"),
                    ("requires_changes", "Requires Changes"),
                ],
                db_index=True,
                default="pending",
                max_length=20,
            ),
        ),
    ]
