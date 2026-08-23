from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("social_publishing", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="socialpublication",
            name="deferred_video_lease",
            field=models.ForeignKey(
                blank=True,
                help_text="Temporary source retained only while moderation/publication is pending.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="deferred_publications",
                to="social_publishing.temporaryvideolease",
            ),
        ),
    ]
