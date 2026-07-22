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

Run `python manage.py seed_smart_shopping_v1 --inactive` to synchronize the
draft prompt and inactive tool records. Use `--dry-run` to inspect counts. An
active staff-edited prompt is a conflict and is preserved unless
`--override-active-prompt` is supplied.
