from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("deliveries", "0007_riderprofile_profile_edit_review"),
        ("orders", "0010_order_customer_email_order_customer_name_and_more"),
        ("products", "0019_product_detail_config"),
        ("smartchat", "0003_smartchatmessage_image"),
        ("vendors", "0010_vendorprofile_preferred_language"),
    ]

    operations = [
        migrations.AddField(
            model_name="smartchatconversation",
            name="audience",
            field=models.CharField(
                choices=[
                    ("customer", "Customer"),
                    ("vendor", "Vendor"),
                    ("rider", "Rider"),
                    ("admin", "Admin"),
                    ("guest", "Guest"),
                ],
                db_index=True,
                default="customer",
                max_length=30,
            ),
        ),
        migrations.AddField(
            model_name="smartchatconversation",
            name="context",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="smartchatconversation",
            name="current_intent",
            field=models.CharField(blank=True, db_index=True, max_length=80),
        ),
        migrations.AddField(
            model_name="smartchatconversation",
            name="order",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="smart_chat_conversations",
                to="orders.order",
            ),
        ),
        migrations.AddField(
            model_name="smartchatconversation",
            name="rider_profile",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="smart_chat_conversations",
                to="deliveries.riderprofile",
            ),
        ),
        migrations.AddField(
            model_name="smartchatconversation",
            name="urgency",
            field=models.CharField(blank=True, db_index=True, default="normal", max_length=30),
        ),
        migrations.AddField(
            model_name="smartchatconversation",
            name="vendor_profile",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="smart_chat_conversations",
                to="vendors.vendorprofile",
            ),
        ),
        migrations.CreateModel(
            name="SmartChatSupportTicket",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=220)),
                ("description", models.TextField()),
                (
                    "audience",
                    models.CharField(
                        choices=[
                            ("customer", "Customer"),
                            ("vendor", "Vendor"),
                            ("rider", "Rider"),
                            ("admin", "Admin"),
                            ("guest", "Guest"),
                        ],
                        default="customer",
                        max_length=30,
                    ),
                ),
                ("intent", models.CharField(blank=True, db_index=True, max_length=80)),
                (
                    "priority",
                    models.CharField(
                        choices=[
                            ("low", "Low"),
                            ("normal", "Normal"),
                            ("high", "High"),
                            ("urgent", "Urgent"),
                        ],
                        db_index=True,
                        default="normal",
                        max_length=20,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("open", "Open"),
                            ("in_progress", "In Progress"),
                            ("waiting_customer", "Waiting Customer"),
                            ("resolved", "Resolved"),
                            ("closed", "Closed"),
                        ],
                        db_index=True,
                        default="open",
                        max_length=30,
                    ),
                ),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("resolved_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "assigned_admin",
                    models.ForeignKey(
                        blank=True,
                        limit_choices_to={"is_staff": True},
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="assigned_smartchat_support_tickets",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "conversation",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="support_tickets",
                        to="smartchat.smartchatconversation",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="smartchat_support_tickets",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "order",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="smartchat_support_tickets",
                        to="orders.order",
                    ),
                ),
                (
                    "product",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="smartchat_support_tickets",
                        to="products.product",
                    ),
                ),
                (
                    "rider_profile",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="smartchat_support_tickets",
                        to="deliveries.riderprofile",
                    ),
                ),
                (
                    "vendor_profile",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="smartchat_support_tickets",
                        to="vendors.vendorprofile",
                    ),
                ),
            ],
            options={
                "verbose_name": "Smart Chat Support Ticket",
                "verbose_name_plural": "Smart Chat Support Tickets",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="smartchatconversation",
            index=models.Index(fields=["audience", "status", "-last_message_at"], name="smartchat_s_audienc_4bda2f_idx"),
        ),
        migrations.AddIndex(
            model_name="smartchatconversation",
            index=models.Index(fields=["current_intent", "-last_message_at"], name="smartchat_s_current_a57fcb_idx"),
        ),
        migrations.AddIndex(
            model_name="smartchatsupportticket",
            index=models.Index(fields=["status", "-created_at"], name="smartchat_s_status_c3b86a_idx"),
        ),
        migrations.AddIndex(
            model_name="smartchatsupportticket",
            index=models.Index(fields=["priority", "status"], name="smartchat_s_priorit_222956_idx"),
        ),
        migrations.AddIndex(
            model_name="smartchatsupportticket",
            index=models.Index(fields=["audience", "status"], name="smartchat_s_audienc_5f0f14_idx"),
        ),
        migrations.AddIndex(
            model_name="smartchatsupportticket",
            index=models.Index(fields=["intent", "-created_at"], name="smartchat_s_intent_a22af1_idx"),
        ),
    ]
