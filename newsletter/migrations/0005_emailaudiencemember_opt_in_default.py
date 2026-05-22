from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('newsletter', '0004_seed_email_audience'),
    ]

    operations = [
        migrations.AlterField(
            model_name='emailaudiencemember',
            name='accepts_promos',
            field=models.BooleanField(default=False),
        ),
    ]
