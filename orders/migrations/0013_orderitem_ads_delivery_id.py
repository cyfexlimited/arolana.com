# Generated manually for the Ads V2 mobile attribution contract.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0012_cartitem_recommendation_algorithm_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="orderitem",
            name="ads_delivery_id",
            field=models.UUIDField(
                blank=True,
                db_index=True,
                help_text="Opaque Ads V2 delivery identifier preserved until server-side attribution.",
                null=True,
            ),
        ),
    ]
