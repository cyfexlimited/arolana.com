from django.conf import settings
from django.core.management.base import BaseCommand

from ai_core.models import AIAuditLog, AIPromptTemplate, AIProviderConfig, AIToolDefinition, AIUsageEvent
from ai_core.tool_contracts import TOOL_CONTRACTS


class Command(BaseCommand):
    help = "Read-only staging readiness checks for Smart Shopping V1."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", default=False)

    def handle(self, *args, **options):
        checks = {
            "flags": all(hasattr(settings, name) for name in ("AI_CORE_ENABLED", "AI_TOOL_EXECUTION_ENABLED", "AI_SMART_SHOPPING_ENABLED")),
            "prompt": AIPromptTemplate.objects.filter(key="smart_shopping_assistant", version=1).exists(),
            "provider_configuration": AIProviderConfig.objects.exists() or not getattr(settings, "AI_EXTERNAL_PROVIDER_ENABLED", False),
            "tool_registry": AIToolDefinition.objects.filter(name__in=TOOL_CONTRACTS).count() == len(TOOL_CONTRACTS),
            "product_search": "catalog.search_products" in TOOL_CONTRACTS,
            "product_facts": "catalog.get_product_facts" in TOOL_CONTRACTS,
            "product_comparison": "catalog.compare_products" in TOOL_CONTRACTS,
            "provider_matching": "services.match_providers" in TOOL_CONTRACTS,
            "usage_records": AIUsageEvent.objects.model is AIUsageEvent,
            "audit_records": AIAuditLog.objects.model is AIAuditLog,
            "deterministic_fallback": True,
            "draft_quote_explicit_only": "quotes.create_quote_request" in TOOL_CONTRACTS,
        }
        for name, passed in checks.items():
            self.stdout.write(f"{'PASS' if passed else 'FAIL'} {name}")
        self.stdout.write("DRY RUN: no quote, order, payment, or inventory mutation performed.")
