from decimal import Decimal

from django.test import TestCase

from accounts.models import User
from products.models import Category, Product

from .models import AIModelConfig, AIProviderConfig, AIQuota, AIUsageEvent
from .permissions import require_role, role_for_user
from .quota import assert_quota_available
from .redaction import REDACTION_LABEL, redact_mapping
from .serializers import serialize_ai_safe


class AICoreFoundationTests(TestCase):
    def test_role_detection_prefers_admin_for_staff_user(self):
        user = User.objects.create_user(
            email="ai-admin@arolana.com",
            username="ai-admin",
            password="StrongPassword123!",
            is_staff=True,
        )
        self.assertEqual(role_for_user(user), "admin")

    def test_role_enforcement_blocks_unlisted_roles(self):
        with self.assertRaises(PermissionError):
            require_role("customer", ["admin"])

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
