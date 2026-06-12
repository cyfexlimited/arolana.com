from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("products", "0019_product_detail_config"),
        ("smartchat", "0006_aiconversation_aimessage_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AIIntentLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("intent", models.CharField(db_index=True, max_length=80)),
                ("previous_intent", models.CharField(blank=True, db_index=True, max_length=80)),
                ("confidence", models.DecimalField(decimal_places=4, default=1, max_digits=5)),
                ("channel", models.CharField(blank=True, db_index=True, max_length=20)),
                ("used_memory", models.BooleanField(default=False)),
                ("triggered_search", models.BooleanField(default=False)),
                ("triggered_handover", models.BooleanField(default=False)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("conversation", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="intent_logs", to="smartchat.smartchatconversation")),
                ("message", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="intent_logs", to="smartchat.smartchatmessage")),
            ],
            options={"verbose_name": "AI Intent Log", "verbose_name_plural": "AI Intent Analytics", "ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="AICategoryRouterLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("marketplace_category", models.CharField(db_index=True, max_length=80)),
                ("confidence", models.DecimalField(decimal_places=4, default=0, max_digits=5)),
                ("matched_terms", models.JSONField(blank=True, default=list)),
                ("route_source", models.CharField(blank=True, max_length=80)),
                ("entity_type", models.CharField(blank=True, max_length=40)),
                ("entity_id", models.PositiveBigIntegerField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("catalog_category", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="ai_router_logs", to="products.category")),
                ("conversation", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="category_router_logs", to="smartchat.smartchatconversation")),
                ("message", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="category_router_logs", to="smartchat.smartchatmessage")),
            ],
            options={"verbose_name": "AI Category Router Log", "verbose_name_plural": "AI Category Analytics", "ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="AIUnansweredQuestion",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("question", models.TextField()),
                ("normalized_question", models.CharField(db_index=True, max_length=500)),
                ("detected_intent", models.CharField(blank=True, db_index=True, max_length=80)),
                ("marketplace_category", models.CharField(blank=True, db_index=True, max_length=80)),
                ("confidence", models.DecimalField(decimal_places=4, default=0, max_digits=5)),
                ("reason", models.CharField(blank=True, max_length=240)),
                ("context_snapshot", models.JSONField(blank=True, default=dict)),
                ("occurrence_count", models.PositiveIntegerField(default=1)),
                ("is_resolved", models.BooleanField(db_index=True, default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("conversation", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="unanswered_questions", to="smartchat.smartchatconversation")),
                ("message", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="unanswered_question_records", to="smartchat.smartchatmessage")),
                ("resolved_knowledge", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="resolved_unanswered_questions", to="smartchat.aiknowledgebase")),
                ("reviewed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="reviewed_ai_unanswered_questions", to=settings.AUTH_USER_MODEL)),
            ],
            options={"verbose_name": "AI Unanswered Question", "verbose_name_plural": "AI Unanswered Questions", "ordering": ["-occurrence_count", "-updated_at"]},
        ),
        migrations.AddIndex(model_name="aiintentlog", index=models.Index(fields=["intent", "-created_at"], name="smartchat_a_intent_841ee7_idx")),
        migrations.AddIndex(model_name="aiintentlog", index=models.Index(fields=["channel", "-created_at"], name="smartchat_a_channel_e581cf_idx")),
        migrations.AddIndex(model_name="aicategoryrouterlog", index=models.Index(fields=["marketplace_category", "-created_at"], name="smartchat_a_marketp_778797_idx")),
        migrations.AddIndex(model_name="aicategoryrouterlog", index=models.Index(fields=["entity_type", "entity_id"], name="smartchat_a_entity__5e38d9_idx")),
        migrations.AddIndex(model_name="aiunansweredquestion", index=models.Index(fields=["is_resolved", "-updated_at"], name="smartchat_a_is_reso_3877ec_idx")),
        migrations.AddIndex(model_name="aiunansweredquestion", index=models.Index(fields=["marketplace_category", "detected_intent"], name="smartchat_a_marketp_472c1c_idx")),
    ]
