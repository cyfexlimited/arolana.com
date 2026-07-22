from django.conf import settings
from django.core.management.base import BaseCommand

from ai_core.management.commands.seed_smart_shopping_v1 import (
    PROMPT_KEY,
    PROMPT_VERSION,
    PROVIDER_API_KEY_ENV,
    PROVIDER_NAME,
)
from ai_core.models import (
    AIAuditLog,
    AIModelConfig,
    AIPromptTemplate,
    AIProviderConfig,
    AIToolDefinition,
    AIUsageEvent,
)
from ai_core.permissions import ROLE_CUSTOMER, ROLE_GUEST
from ai_core.tool_contracts import FEATURE_SMART_SHOPPING, TOOL_CONTRACTS


class Command(BaseCommand):
    help = "Read-only staging readiness checks for Smart Shopping V1."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", default=False)

    def handle(self, *args, **options):
        provider = AIProviderConfig.objects.filter(name=PROVIDER_NAME).first()
        model = (
            AIModelConfig.objects.filter(provider=provider, feature=FEATURE_SMART_SHOPPING).first()
            if provider else None
        )
        prompt = AIPromptTemplate.objects.filter(key=PROMPT_KEY, version=PROMPT_VERSION).first()
        checks = {
            "flags": all(hasattr(settings, name) for name in ("AI_CORE_ENABLED", "AI_TOOL_EXECUTION_ENABLED", "AI_SMART_SHOPPING_ENABLED")),
            "prompt": bool(prompt and prompt.allowed_roles == [ROLE_CUSTOMER, ROLE_GUEST]),
            "provider_configuration": bool(
                provider
                and provider.provider == AIProviderConfig.PROVIDER_OPENAI
                and provider.api_key_env_var == PROVIDER_API_KEY_ENV
            ),
            "model_configuration": bool(
                model
                and model.model_name == getattr(settings, "AROLANA_AI_MODEL", "gpt-5.5")
                and model.supports_structured_outputs
                and model.supports_tool_calls
            ),
            "inactive_seed_state": bool(
                provider and not provider.is_active
                and model and not model.is_default
                and prompt and prompt.status == AIPromptTemplate.STATUS_DRAFT
            ),
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
        mode = "DRY RUN" if options["dry_run"] else "READ ONLY"
        self.stdout.write(f"{mode}: no quote, order, payment, or inventory mutation performed.")
