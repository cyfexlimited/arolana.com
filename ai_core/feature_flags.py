from django.conf import settings


_TRUE_VALUES = {"1", "true", "yes", "on", "enabled"}
_FALSE_VALUES = {"0", "false", "no", "off", "disabled", "", "none", "null"}


def _setting_enabled(name, default=False):
    """Read a Django setting as a real boolean."""
    value = getattr(settings, name, default)

    if isinstance(value, bool):
        return value
    if value is None:
        return bool(default)
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalised = value.strip().lower()
        if normalised in _TRUE_VALUES:
            return True
        if normalised in _FALSE_VALUES:
            return False
    return bool(value)


def ai_core_enabled():
    return _setting_enabled("AI_CORE_ENABLED", False)


def external_provider_enabled():
    return _setting_enabled("AI_EXTERNAL_PROVIDER_ENABLED", False)


def smart_shopping_enabled():
    return _setting_enabled("AI_SMART_SHOPPING_ENABLED", False)


def tool_execution_enabled():
    return _setting_enabled("AI_TOOL_EXECUTION_ENABLED", False)


def require_ai_core_enabled():
    if not ai_core_enabled():
        raise PermissionError("AI core is disabled.")
    return True


def require_external_provider_enabled():
    require_ai_core_enabled()
    if not external_provider_enabled():
        raise PermissionError("External AI providers are disabled.")
    return True


def require_tool_execution_enabled():
    require_ai_core_enabled()
    if not tool_execution_enabled():
        raise PermissionError("AI tool execution is disabled.")
    return True

