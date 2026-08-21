from django.conf import settings

from .adapters import v2_recommendation_adapter
from .decisioning import decisioning_service


MOBILE_USER_AGENT_MARKERS = (
    "android",
    "iphone",
    "ipod",
    "mobile",
    "webview",
)


def internal_ads_v2_enabled(request):
    user = getattr(request, "user", None)
    return bool(
        getattr(settings, "ADS_RECOMMENDATION_V2_API_ENABLED", False)
        and getattr(settings, "ADS_RECOMMENDATION_V2_INTERNAL_TESTING_ENABLED", False)
        and user
        and user.is_authenticated
        and getattr(user, "is_staff", False)
        and getattr(request, "session", {}).get("ads_v2_internal_test") is True
    )


def client_for_request(request):
    user_agent = (
        request.META.get("HTTP_USER_AGENT", "")
        if request is not None
        else ""
    ).lower()
    return (
        "mobile_web"
        if any(marker in user_agent for marker in MOBILE_USER_AGENT_MARKERS)
        else "web"
    )


def surface_flag_enabled(client):
    if client == "mobile_web":
        return bool(getattr(settings, "ADS_RECOMMENDATION_V2_MOBILE_WEB_ENABLED", False))
    return bool(getattr(settings, "ADS_RECOMMENDATION_V2_WEB_ENABLED", False))


def recommendation_shelf(request, *, placement, limit=8, **context_params):
    """Return renderer-safe Ads V2 recommendations for staff internal testing.

    This boundary intentionally fails closed. Normal customers get no V2 shelf,
    and existing page/V1 rendering continues unaffected.
    """
    client = client_for_request(request)
    if not internal_ads_v2_enabled(request) or not surface_flag_enabled(client):
        return {
            "enabled": False,
            "client": client,
            "placement": placement,
            "results": [],
        }

    try:
        limit = max(1, min(int(limit), 24))
    except (TypeError, ValueError):
        limit = 8

    try:
        context = decisioning_service.context_from_request(request)
        context.placement = str(placement or context.placement or "default")[:80]
        for key, value in context_params.items():
            if value in ("", None) or not hasattr(context, key):
                continue
            setattr(context, key, value)
        candidates = decisioning_service.recommendations_for_request(
            request,
            limit=limit,
            context=context,
        )
        results = v2_recommendation_adapter.adapt_results(
            candidates,
            surface=context.placement,
            client=client,
        )
    except Exception:
        return {
            "enabled": True,
            "client": client,
            "placement": placement,
            "results": [],
            "fallback": True,
        }

    return {
        "enabled": True,
        "client": client,
        "placement": placement,
        "results": results,
    }
