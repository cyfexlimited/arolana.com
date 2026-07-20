from django.conf import settings


def ai_core_enabled():
    return bool(getattr(settings, "AI_CORE_ENABLED", False))


def external_provider_enabled():
    return bool(getattr(settings, "AI_EXTERNAL_PROVIDER_ENABLED", False))


def smart_shopping_enabled():
    return bool(getattr(settings, "AI_SMART_SHOPPING_ENABLED", False))


def tool_execution_enabled():
    return bool(getattr(settings, "AI_TOOL_EXECUTION_ENABLED", False))


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

