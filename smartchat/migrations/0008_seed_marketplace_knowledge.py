from django.db import migrations


def seed_marketplace_knowledge(apps, schema_editor):
    AIKnowledgeBase = apps.get_model("smartchat", "AIKnowledgeBase")
    from smartchat.knowledge_seed import build_seed_entries

    existing = set(AIKnowledgeBase.objects.values_list("question", flat=True))
    rows = [
        AIKnowledgeBase(**entry)
        for entry in build_seed_entries()
        if entry["question"] not in existing
    ]
    AIKnowledgeBase.objects.bulk_create(rows, batch_size=250)


class Migration(migrations.Migration):
    dependencies = [
        ("smartchat", "0007_ai_marketplace_analytics"),
    ]

    operations = [
        migrations.RunPython(seed_marketplace_knowledge, migrations.RunPython.noop),
    ]
