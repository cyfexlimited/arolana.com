from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ads", "0010_external_campaign_execution_foundation"),
    ]

    operations = [
        migrations.AddField(
            model_name="adchannelexecution",
            name="external_creative_id",
            field=models.CharField(blank=True, max_length=200),
        ),
    ]
