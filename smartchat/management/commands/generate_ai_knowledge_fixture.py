import json
from pathlib import Path

from django.core.management.base import BaseCommand

from smartchat.knowledge_seed import build_seed_entries


class Command(BaseCommand):
    help = "Generate the approved Arolana Smart Chat knowledge fixture."

    def handle(self, *args, **options):
        output = Path("smartchat/fixtures/ai_knowledge_base.json")
        output.parent.mkdir(parents=True, exist_ok=True)
        fixture = [
            {
                "model": "smartchat.aiknowledgebase",
                "pk": 100000 + index,
                "fields": {
                    **entry,
                    "usage_count": 0,
                    "last_used_at": None,
                    "created_by": None,
                    "approved_by": None,
                    "created_at": "2026-06-12T00:00:00Z",
                    "updated_at": "2026-06-12T00:00:00Z",
                },
            }
            for index, entry in enumerate(build_seed_entries(), start=1)
        ]
        output.write_text(json.dumps(fixture, indent=2, ensure_ascii=True) + "\n")
        self.stdout.write(self.style.SUCCESS(f"Generated {len(fixture)} FAQs at {output}"))
