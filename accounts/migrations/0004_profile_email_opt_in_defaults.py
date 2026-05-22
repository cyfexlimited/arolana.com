from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0003_seed_registration_messages'),
    ]

    operations = [
        migrations.AlterField(
            model_name='userprofile',
            name='newsletter_subscription',
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name='userprofile',
            name='promo_emails',
            field=models.BooleanField(default=False),
        ),
    ]
