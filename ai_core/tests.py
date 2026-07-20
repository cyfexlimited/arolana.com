from decimal import Decimal

from django.test import TestCase, override_settings

from accounts.models import User
from products.models import Category, Product

from .feature_flags import (
    ai_core_enabled,
    external_provider_enabled,
    smart_shopping_enabled,
    tool_execution_enabled,
)
from .intent import UNSUPPORTED_INTENT, validate_single_primary_intent
from .models import AIModelConfig, AIProviderConfig, AIPromptTemplate, AIQuota, AIToolDefinition, AIUsageEvent
from .permissions import ROLE_ADMIN, ROLE_CUSTOMER, require_role, role_for_user
from .providers import AIProviderError, OpenAIProvider
from .quota import assert_quota_available
from .redaction import REDACTION_LABEL, redact_mapping
from .serializers import serialize_ai_safe
from .tools import QUOTE_CREATE_TOOL, execute_registered_tool


class AICoreFoundationTests(TestCase):
    def test_role_detection_prefers_admin_for_staff_user(self):
        user = User.objects.create_user(
            email="ai-admin@arolana.com",
            username="ai-admin",
            password="StrongPassword123!",
            is_staff=True,
        )
        self.assertEqual(role_for_user(user), ROLE_ADMIN)

    def test_role_enforcement_blocks_unlisted_roles(self):
        with self.assertRaises(PermissionError):
            require_role(ROLE_CUSTOMER, [ROLE_ADMIN])

    def test_redaction_blocks_sensitive_keys_and_inline_pii(self):
        clean = redact_mapping({
            "customer_email": "buyer@example.com",
            "product": "Projector",
            "gateway_response": {"authorization": "secret"},
        })
        self.assertEqual(clean["customer_email"], REDACTION_LABEL)
        self.assertEqual(clean["gateway_response"], REDACTION_LABEL)
        self.assertEqual(clean["product"], "Projector")

    def test_safe_serializer_allows_product_without_private_fields(self):
        vendor = User.objects.create_user(
            email="vendor@arolana.com",
            username="vendor",
            password="StrongPassword123!",
            user_type="vendor",
        )
        category = Category.objects.create(name="Projectors", slug="projectors")
        product = Product.objects.create(
            name="Boardroom Projector",
            slug="boardroom-projector",
            sku="BP-001",
            description="A full HD boardroom projector.",
            category=category,
            vendor=vendor,
            price=Decimal("1000.00"),
            stock_quantity=4,
            approval_status="approved",
            is_active=True,
        )
        payload = serialize_ai_safe(product)
        self.assertEqual(payload["type"], "product")
        self.assertEqual(payload["name"], "Boardroom Projector")
        self.assertNotIn("cost_per_item", payload)

    def test_quota_blocks_when_daily_request_limit_is_reached(self):
        user = User.objects.create_user(
            email="quota@arolana.com",
            username="quota",
            password="StrongPassword123!",
        )
        AIQuota.objects.create(role="customer", feature="test", max_requests_per_day=1)
        AIUsageEvent.objects.create(user=user, role="customer", feature="test", status=AIUsageEvent.STATUS_SUCCESS)
        with self.assertRaises(PermissionError):
            assert_quota_available("customer", "test", user=user)

    def test_model_config_estimates_cost(self):
        provider = AIProviderConfig.objects.create(name="OpenAI", provider="openai")
        model = AIModelConfig.objects.create(
            provider=provider,
            model_name="gpt-test",
            feature="foundation",
            input_token_cost_per_1k=Decimal("0.001000"),
            output_token_cost_per_1k=Decimal("0.002000"),
        )
        self.assertEqual(model.estimate_cost(1000, 500), Decimal("0.002000"))

    def test_ai_feature_flags_default_to_false(self):
        self.assertFalse(ai_core_enabled())
        self.assertFalse(external_provider_enabled())
        self.assertFalse(smart_shopping_enabled())
        self.assertFalse(tool_execution_enabled())

    def test_external_provider_fails_closed_when_flags_are_disabled(self):
        provider = AIProviderConfig.objects.create(name="OpenAI disabled", provider="openai")
        model = AIModelConfig.objects.create(provider=provider, model_name="gpt-test", feature="foundation")
        prompt = AIPromptTemplate.objects.create(
            key="disabled-provider",
            version=1,
            title="Disabled provider",
            feature="foundation",
            system_prompt="Return JSON.",
            status=AIPromptTemplate.STATUS_ACTIVE,
            allowed_roles=[ROLE_ADMIN],
        )
        with self.assertRaises(AIProviderError):
            OpenAIProvider(provider).structured_response(
                model_config=model,
                prompt=prompt,
                input_payload={"message": "hello"},
                role=ROLE_ADMIN,
            )
        self.assertEqual(
            AIUsageEvent.objects.get(prompt_key="disabled-provider").metadata["reason"],
            "external_provider_disabled",
        )

    def test_single_primary_intent_rejects_multi_intent_payload(self):
        with self.assertRaises(ValueError):
            validate_single_primary_intent({"intents": ["product_search", "quote_request"]})
        with self.assertRaises(ValueError):
            validate_single_primary_intent({"intent": ["product_search", "quote_request"]})
        self.assertEqual(
            validate_single_primary_intent({"intent": "vehicle"}),
            UNSUPPORTED_INTENT,
        )

    def test_tool_execution_defaults_to_disabled(self):
        AIToolDefinition.objects.create(
            name="catalog.read",
            feature="foundation",
            description="Read-only catalog lookup.",
            allowed_roles=[ROLE_ADMIN],
        )
        with self.assertRaises(PermissionError):
            execute_registered_tool(
                "catalog.read",
                {},
                role=ROLE_ADMIN,
                read_only=True,
                handler=lambda payload: {"ok": True},
            )

    @override_settings(AI_CORE_ENABLED=True, AI_TOOL_EXECUTION_ENABLED=True)
    def test_only_quote_tool_can_write_and_requires_duplicate_protection(self):
        AIToolDefinition.objects.create(
            name="catalog.write",
            feature="foundation",
            description="Unsafe write.",
            allowed_roles=[ROLE_ADMIN],
        )
        with self.assertRaises(PermissionError):
            execute_registered_tool(
                "catalog.write",
                {},
                role=ROLE_ADMIN,
                read_only=False,
                handler=lambda payload: {"ok": True},
            )

        AIToolDefinition.objects.create(
            name=QUOTE_CREATE_TOOL,
            feature="quotes",
            description="Create a draft quote request.",
            allowed_roles=[ROLE_CUSTOMER, ROLE_ADMIN],
            requires_human_approval=True,
        )
        payload = {
            "customer_consent": True,
            "approved_guest_contact": True,
            "conversation_id": "conv-1",
            "idempotency_key": "idem-1",
            "requirements": {"summary": "Install two projectors in a boardroom with HDMI switching."},
        }
        result = execute_registered_tool(
            QUOTE_CREATE_TOOL,
            payload,
            role=ROLE_CUSTOMER,
            read_only=False,
            duplicate_lookup=lambda data: {"id": "existing-draft"},
            handler=lambda data: {"id": "new-draft"},
        )
        self.assertFalse(result.created)
        self.assertEqual(result.payload["id"], "existing-draft")
