"""Local Meta runtime policy. No ORM, provider client, or environment writes.

Parsing is separate from policy so settings can discard invalid input without
logging it, while system checks can still identify the configuration error.
"""
import re

from django.conf import settings


FRESHNESS_DEFAULTS = {
    "META_ADS_LIVE_AUTHORIZATION_MAX_AGE_SECONDS": (900, 60),
    "META_ADS_VERIFICATION_MAX_AGE_SECONDS": (600, 1),
    "META_ADS_PERMISSION_MAX_AGE_SECONDS": (600, 1),
}


def parse_live_write_setting(value):
    """Canonicalize only literal true/false; None denotes invalid input."""
    if type(value) is bool:
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "false", ""}:
            return normalized == "true"
    return None


def canonical_account_id(value):
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if value[:4].lower() == "act_":
        value = value[4:]
    return value if re.fullmatch(r"[0-9]{1,200}", value) else ""


def parse_account_allowlist(value):
    """Any malformed nonblank entry closes the entire configuration."""
    if value is None:
        return frozenset(), True
    if isinstance(value, str):
        value = value.split(",")
    if not isinstance(value, (list, tuple)) or len(value) > 1000:
        return frozenset(), False
    result = set()
    for item in value:
        if isinstance(item, str) and not item.strip():
            continue
        account_id = canonical_account_id(item)
        if not account_id:
            return frozenset(), False
        result.add(account_id)
    return frozenset(result), True


def parse_max_age_setting(value):
    if type(value) is int:
        return value if value > 0 else None
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,10}", value.strip()):
        parsed = int(value.strip())
        return parsed if parsed > 0 else None
    return None


def freshness_seconds(name, settings_source=None):
    source = settings if settings_source is None else settings_source
    default, minimum = FRESHNESS_DEFAULTS[name]
    parsed = parse_max_age_setting(getattr(source, name, default))
    return max(minimum, min(parsed, 3600)) if parsed is not None else 0


def freshness_blockers(settings_source=None):
    return ["meta_freshness_configuration_invalid"] if any(
        not freshness_seconds(name, settings_source) for name in FRESHNESS_DEFAULTS
    ) else []


def acceptance_harness_allowed():
    """Only an explicit Django in-process test override can open the harness.

This setting is never read from environment variables. The command retains
its independent synthetic-context check and unconditional mocked writer.
"""
    from django.conf import UserSettingsHolder

    if getattr(settings, "META_ADS_ACCEPTANCE_HARNESS_ENABLED", False) is not True:
        return False
    holder = settings._wrapped
    while isinstance(holder, UserSettingsHolder):
        if "META_ADS_ACCEPTANCE_HARNESS_ENABLED" in vars(holder):
            return vars(holder)["META_ADS_ACCEPTANCE_HARNESS_ENABLED"] is True
        holder = holder.default_settings
    return False


def runtime_safety_snapshot(settings_source=None):
    """Only bounded booleans, count, and constant codes leave this service."""
    source = settings if settings_source is None else settings_source
    live = getattr(source, "META_ADS_LIVE_WRITES_ENABLED", False)
    allowed, allowlist_valid = parse_account_allowlist(
        getattr(source, "META_ADS_LIVE_WRITE_ACCOUNT_ALLOWLIST", None)
    )
    harness = getattr(source, "META_ADS_ACCEPTANCE_HARNESS_ENABLED", False)
    blockers = []
    if type(live) is not bool:
        blockers.append("meta_live_boolean_invalid")
    if not allowlist_valid:
        blockers.append("meta_live_allowlist_invalid")
    if live is True and not allowed:
        blockers.append("meta_live_allowlist_empty")
    if harness is not False:
        blockers.append("meta_acceptance_harness_not_for_normal_runtime")
    # Recognize accidental unsupported configuration; do not define or use it
    # to enable an operation. There is no activation implementation.
    if getattr(source, "META_ADS_ACTIVATION_ENABLED", False) is not False:
        blockers.append("meta_activation_unsupported")
    blockers.extend(freshness_blockers(source))
    return {
        "live_writes_enabled": live is True,
        "allowlist_configured": bool(allowed),
        "allowlisted_account_count": len(allowed),
        "acceptance_harness_enabled": harness is True,
        "delivery_mode": "PAUSED",
        "activation_supported": False,
        "provider_reads_during_execute": False,
        "safe_to_start": not blockers,
        "blockers": blockers,
    }
