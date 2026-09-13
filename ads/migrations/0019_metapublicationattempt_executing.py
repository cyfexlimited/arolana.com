from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("ads", "0018_metapublicationauthorization_metapublicationauditevent")]
    operations = [migrations.AlterField(
        model_name="metapublicationattempt", name="status",
        field=models.CharField(choices=[("ready", "Ready"), ("stale", "Stale"), ("executing", "Executing"), ("failed", "Failed"), ("completed", "Completed")], db_index=True, default="ready", max_length=20),
    )]
