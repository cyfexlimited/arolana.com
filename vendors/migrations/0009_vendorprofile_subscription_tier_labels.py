from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("vendors", "0008_vendorprofile_subscription_benefits"),
    ]

    operations = [
        migrations.AlterField(
            model_name="vendorprofile",
            name="subscription_tier",
            field=models.CharField(
                choices=[
                    ("free", "Free Vendor"),
                    ("basic", "Basic Vendor"),
                    ("plus", "Plus Vendor"),
                    ("pro", "Pro Vendor"),
                    ("special", "Special Vendor"),
                    ("enterprise", "Enterprise Vendor"),
                ],
                default="free",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="vendorsubscriptionplan",
            name="tier",
            field=models.CharField(
                choices=[
                    ("free", "Free Vendor"),
                    ("basic", "Basic Vendor"),
                    ("plus", "Plus Vendor"),
                    ("pro", "Pro Vendor"),
                    ("special", "Special Vendor"),
                    ("enterprise", "Enterprise Vendor"),
                ],
                max_length=20,
                unique=True,
            ),
        ),
    ]
