# Generated migration for adCreative field
from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):

    dependencies = [
        ('ads', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='adimpression',
            name='adCreative',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='ads.adcreative'),
        ),
    ]
