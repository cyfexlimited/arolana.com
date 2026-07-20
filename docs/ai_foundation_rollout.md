# Arolana AI foundation architecture, data boundary and rollout plan

Date: 2026-07-20

This document describes the reusable AI foundation implemented before any new Shopping Assistant or autonomous marketing features.

## Architecture

`ai_core` is the shared backend layer for future AI features. It provides:

- provider configuration and abstraction through `AIProviderConfig`
- OpenAI provider integration behind a provider interface
- model configuration and per-feature model selection with `AIModelConfig`
- structured output schemas on approved prompts
- prompt registry with versioning, approval metadata and allowed roles
- tool registry with explicit role allowlists and safe serializer names
- role and permission enforcement for customer, vendor, provider, rider, admin and guest contexts
- safety/redaction helpers for sensitive keys and inline PII
- usage/token/cost logging via `AIUsageEvent`
- daily request/token/cost quotas via `AIQuota`
- append-only audit events via `AIAuditLog`
- a staff-only status endpoint at `/api/ai-core/status/`

SmartChat remains the user-facing conversation surface. `ai_core` is infrastructure only; it does not introduce a Shopping Assistant, multi-agent workflows, autonomous marketing, vehicles or real estate product changes.

## Data-boundary policy

AI features must use explicit AI-safe serializers. They must not query arbitrary ORM models or dynamically expose model fields.

Allowed starting serializers:

- products: public catalog fields only
- vendors: public storefront/profile fields only
- service providers/installers: public service profile fields only
- orders: minimal customer-facing order status fields only

Blocked data classes:

- payment transactions, gateway responses, webhook payloads and checkout data
- KYC documents, government IDs and verification artifacts
- bank and payout details
- authentication tokens, API tokens, passwords, PINs and OTPs
- full addresses, private contact details and location precision not already public
- private media and protected file URLs
- fraud/risk/internal review fields
- internal admin notes and private support messages

If a future feature needs additional data, add a named serializer and tests for that serializer first. Do not pass model instances, QuerySets or raw dictionaries directly to providers.

## API and admin controls

Admins can manage providers, model configs, prompt templates, tool definitions, data-boundary rules and quotas in Django admin. Usage events and audit logs are read-only in admin.

The `/api/ai-core/status/` endpoint is staff-only and reports configuration counts for operational visibility without exposing secrets or prompts to non-staff clients.

## Rollout plan

1. Rotate exposed secrets and verify production settings.
2. Deploy the registration/auth compatibility fix.
3. Deploy `ai_core` migrations and admin controls.
4. Configure a disabled or low-quota OpenAI provider in production.
5. Add approved prompts and tools only for internal/staff validation.
6. Connect SmartChat to `ai_core` behind a feature flag.
7. Run usage, quota and audit-log review for real traffic.
8. Only then begin the Shopping Assistant implementation.

## Verification commands

```bash
python manage.py makemigrations --check --dry-run
python manage.py check
python manage.py test mobile_customers.tests.MobileCustomerWebAccountAuthenticationTests.test_native_registration_creates_real_user_then_verifies_otp ai_core -v 2
```

