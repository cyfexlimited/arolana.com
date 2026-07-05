import re

from django.core.management.base import BaseCommand

from smartchat.models import AIKnowledgeBase, AITrainingData


RULES = (
    (
        "internal_rule",
        re.compile(
            r"\b(system prompt|conversation context|customer memory|detected intent|"
            r"do not expose|if confidence is low|admin can take over)\b",
            re.I,
        ),
    ),
    (
        "routing_rule",
        re.compile(r"\b(route decision|route to|detect intent|category routing|before product search)\b", re.I),
    ),
    (
        "escalation_rule",
        re.compile(r"\b(escalat(?:e|ion)|human handover|connect to support)\b", re.I),
    ),
    (
        "catalog_lookup_rule",
        re.compile(r"\b(search (?:the )?(?:product|catalog|database)|live product data)\b", re.I),
    ),
    (
        "recommendation_rule",
        re.compile(r"\b(compare related products|recommend(?:ation)? engine|rank products)\b", re.I),
    ),
)


def classify(item):
    content = f"{item.question}\n{item.answer}\n{item.keywords}"
    for answer_type, pattern in RULES:
        if pattern.search(content):
            return answer_type
    return "customer_answer"


class Command(BaseCommand):
    help = "Audit Smart Chat knowledge answer types without rewriting customer content."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--apply-safe-classifications", action="store_true")

    def handle(self, *args, **options):
        apply_changes = options["apply_safe_classifications"] and not options["dry_run"]
        changed = 0
        scanned = 0
        counts = {}
        for model in (AIKnowledgeBase, AITrainingData):
            for item in model.objects.all().iterator():
                scanned += 1
                suggested = classify(item)
                counts[suggested] = counts.get(suggested, 0) + 1
                if suggested != item.answer_type and suggested != "customer_answer":
                    self.stdout.write(
                        f"{model.__name__} #{item.pk}: {item.answer_type} -> {suggested}"
                    )
                    if apply_changes:
                        item.answer_type = suggested
                        item.save(update_fields=["answer_type", "updated_at"])
                        changed += 1
        self.stdout.write(
            self.style.SUCCESS(
                f"Scanned {scanned}; classifications={counts}; updated={changed}; "
                f"mode={'apply' if apply_changes else 'dry-run'}"
            )
        )
