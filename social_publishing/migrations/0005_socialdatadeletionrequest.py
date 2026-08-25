import django.utils.timezone
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('social_publishing', '0004_socialconnectionauditlog_socialoauthstate'),
    ]

    operations = [
        migrations.CreateModel(
            name='SocialDataDeletionRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('platform', models.CharField(choices=[('youtube', 'YouTube'), ('instagram', 'Instagram'), ('facebook', 'Facebook'), ('tiktok', 'TikTok'), ('linkedin', 'LinkedIn')], max_length=20)),
                ('external_account_id', models.CharField(max_length=255)),
                ('confirmation_code', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('requested_at', models.DateTimeField(auto_now_add=True)),
                ('completed_at', models.DateTimeField(default=django.utils.timezone.now)),
            ],
            options={
                'constraints': [models.UniqueConstraint(fields=('platform', 'external_account_id'), name='uniq_social_data_deletion_platform_identity')],
            },
        ),
    ]
