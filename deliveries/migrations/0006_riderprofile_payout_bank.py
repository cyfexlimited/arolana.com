from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("deliveries", "0005_riderprofile_dashboard_preferences"),
    ]

    operations = [
        migrations.AddField(
            model_name="riderprofile",
            name="payout_account_name",
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.AddField(
            model_name="riderprofile",
            name="payout_account_number",
            field=models.CharField(blank=True, max_length=40),
        ),
        migrations.AddField(
            model_name="riderprofile",
            name="payout_bank_country",
            field=models.CharField(blank=True, default="Nigeria", max_length=80),
        ),
        migrations.AddField(
            model_name="riderprofile",
            name="payout_bank_name",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="riderprofile",
            name="payout_preferred_currency",
            field=models.CharField(blank=True, default="NGN", max_length=10),
        ),
    ]
