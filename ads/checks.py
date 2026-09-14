"""Value-free, database-free Meta configuration checks."""
from django.core.checks import Error, Tags, Warning, register

from .meta_runtime import runtime_safety_snapshot


RUNTIME_CHECKS = {
    "meta_live_boolean_invalid": (Error, "ads.E001", "Meta live-write configuration must be a literal boolean."),
    "meta_live_allowlist_invalid": (Error, "ads.E002", "Meta live-write account allowlist is malformed; access is denied."),
    "meta_acceptance_harness_not_for_normal_runtime": (Error, "ads.E003", "Meta acceptance harness must be disabled in normal runtime."),
    "meta_activation_unsupported": (Error, "ads.E004", "Meta activation configuration is unsupported."),
    "meta_freshness_configuration_invalid": (Error, "ads.E005", "Meta receipt and authorization lifetimes must be positive integers."),
    "meta_live_allowlist_empty": (Warning, "ads.W001", "Meta live writes are enabled with no allowed account; execution remains blocked."),
}


@register(Tags.security)
def meta_live_runtime_check(app_configs, **kwargs):
    if app_configs is not None and not any(app.name == "ads" for app in app_configs):
        return []
    messages = []
    for code in runtime_safety_snapshot()["blockers"]:
        severity, check_id, message = RUNTIME_CHECKS[code]
        messages.append(severity(message, id=check_id))
    return messages
