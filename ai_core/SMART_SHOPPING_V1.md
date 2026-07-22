# Smart Shopping V1 hardening contracts

Tool contracts are validated by the dependency-free internal validator in
`ai_core.schema_validation`. Inputs are validated before handler execution and
outputs (including recursive source references) before they can reach
SmartChat. Contract failures are recorded by the canonical usage/audit path and
surface only controlled error text through SmartChat's deterministic fallback.

Public source references have exactly `label`, `type`, `ref`, and `url`. The URL
is an Arolana public HTTPS URL/path, or an empty URL paired with the stable
opaque `arolana:<type>:<ref>` identity. Admin/private-media URLs and external
hosts are rejected. Public slugs are used instead of database identifiers.

Provider matching reuses `ServiceProviderProfile.objects.public()` for active,
approved/verified visibility, `installers.services.filter_public_providers` or
`suggested_providers_for_product` for coverage/category matching, approved KYC,
and `ServiceProviderProfile.can_receive_serious_jobs`. That property delegates
to `subscriptions.lifecycle.get_effective_subscription(...,
role_context="provider").can_receive_serious_jobs`, preserving the shared
subscription and limited-job exception rules.

## Reproducible staging configuration

Run `python manage.py seed_smart_shopping_v1 --inactive --dry-run` to inspect
the planned synchronization, then run
`python manage.py seed_smart_shopping_v1 --inactive` in staging. The command
creates or synchronizes all of the following from code:

- inactive OpenAI provider `Smart Shopping OpenAI`, which stores only the
  credential environment-variable name `OPENAI_API_KEY`;
- non-default `smart_shopping` model using `AROLANA_AI_MODEL` (default
  `gpt-5.5`), structured outputs, tool calls, 16,000 input tokens and 2,048
  output tokens;
- draft prompt `smart_shopping_assistant` version 1, restricted to `customer`
  and `guest`;
- five inactive Smart Shopping tool definitions.

No API key or other credential is copied into the database. Configure
`OPENAI_API_KEY` only in the staging secret manager/runtime environment and set
`AROLANA_AI_MODEL` to the staging-approved model before seeding. The command
does not change any feature flag.

After seeding, run `python manage.py verify_smart_shopping_v1`. Activate in this
order only after staging review: provider, model default, prompt, the approved
tools, then `AI_CORE_ENABLED`, `AI_TOOL_EXECUTION_ENABLED`,
`AI_SMART_SHOPPING_ENABLED`, and finally `AI_EXTERNAL_PROVIDER_ENABLED` when an
external provider test is authorized. Keep production flags false throughout
this staging rollout.

Inactive records are synchronized idempotently. Active staff-edited provider,
model, and prompt records are reported as conflicts and preserved. The
explicit `--override-active-provider`, `--override-active-model`, and
`--override-active-prompt` options may replace the corresponding active record;
use them only after staff review and never as part of routine staging seeding.

Rollback by setting all four AI flags false, deactivating the five tools and
prompt, clearing the model's default marker, and deactivating the provider.
Retain audit records. Do not delete quote requests or other customer records as
part of configuration rollback. Production activation and deployment are out
of scope for this staging-only procedure.

## Confirmed customer quote handoff

`POST /api/smartchat/quote-request/` is the shared web/mobile confirmation
endpoint. It verifies the authenticated customer or the guest conversation's
device and session ownership before executing
`ai_core.tools.execute_ai_tool("quotes.create_quote_request", ...)`. It never
calls the commerce handler directly. `AI_CORE_ENABLED`,
`AI_TOOL_EXECUTION_ENABLED`, `AI_SMART_SHOPPING_ENABLED`, and an active tool
record are required. `AI_EXTERNAL_PROVIDER_ENABLED` is deliberately not
required: confirmed quote submission is a deterministic first-party handoff
and remains available when the external model provider is unavailable.

Currency conversion is optional and backend-only. The supplied amount and
currency are always preserved. A valid current rate adds base amount, base
currency, rate, and timestamp provenance; a missing or stale rate adds a human
review warning and does not reject the draft request.
