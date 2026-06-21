import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import ClickEvent
from .utils import (
    clean_clicked_text,
    clean_url,
    detect_traffic_source,
    get_browser,
    get_client_ip,
    get_country,
    get_device_type,
    get_operating_system,
    get_referrer,
    get_referrer_domain,
    get_user_agent,
    get_utm_data,
    guess_event_type,
    is_bot_user_agent,
    normalize_path,
)


@csrf_exempt
@require_POST
def track_click_event(request):
    """
    Receives click analytics from Arolana frontend.

    Important:
    - This view saves click events.
    - Do not call should_skip_tracking(request) here because this endpoint itself
      starts with /visitor-analytics/.
    - Admin/private page clicks are still skipped.
    """

    try:
        try:
            payload = json.loads(request.body.decode("utf-8") or "{}")
        except Exception:
            payload = request.POST.dict()

        page_path = payload.get("path", "") or request.META.get("HTTP_REFERER", "") or ""

        # Do not track admin activity.
        if str(page_path).startswith("/admin/") or "/admin/" in str(page_path):
            return JsonResponse(
                {
                    "ok": True,
                    "created": False,
                    "skipped": True,
                    "reason": "admin",
                }
            )

        user_agent = get_user_agent(request)
        ip_address = get_client_ip(request)

        clicked_text = clean_clicked_text(payload.get("clicked_text", ""))
        clicked_url = clean_url(payload.get("clicked_url", ""))

        page_url = clean_url(
            payload.get("page_url", "")
            or request.META.get("HTTP_REFERER", "")
            or request.build_absolute_uri()
        )

        referrer = get_referrer(request)
        referrer_domain = get_referrer_domain(referrer)
        traffic_source = detect_traffic_source(referrer=referrer, page_url=page_url)
        utm = get_utm_data(page_url)

        element_tag = clean_clicked_text(payload.get("element_tag", ""))[:50]
        element_id = clean_clicked_text(payload.get("element_id", ""))[:200]
        element_classes = clean_clicked_text(payload.get("element_classes", ""))[:500]

        event_type = guess_event_type(
            clicked_url=clicked_url,
            clicked_text=clicked_text,
            element_tag=element_tag,
            data_event_type=payload.get("event_type", ""),
        )

        user = None
        is_authenticated = False

        if hasattr(request, "user") and request.user.is_authenticated:
            user = request.user
            is_authenticated = True

        session_key = ""
        if hasattr(request, "session"):
            if not request.session.session_key:
                request.session.save()
            session_key = request.session.session_key or ""

        ClickEvent.objects.create(
            user=user,
            ip_address=ip_address or None,
            country=get_country(request),
            user_agent=user_agent,
            device_type=get_device_type(user_agent),
            browser=get_browser(user_agent),
            operating_system=get_operating_system(user_agent),

            referrer=referrer,
            referrer_domain=referrer_domain,
            traffic_source=traffic_source,
            utm_source=utm.get("utm_source", ""),
            utm_medium=utm.get("utm_medium", ""),
            utm_campaign=utm.get("utm_campaign", ""),
            utm_content=utm.get("utm_content", ""),
            utm_term=utm.get("utm_term", ""),

            page_url=page_url,
            path=normalize_path(payload.get("path", "")),
            clicked_text=clicked_text,
            clicked_url=clicked_url,

            element_tag=element_tag,
            element_id=element_id,
            element_classes=element_classes,
            event_type=event_type,

            product_id=clean_clicked_text(payload.get("product_id", ""))[:100],
            category_id=clean_clicked_text(payload.get("category_id", ""))[:100],
            vendor_id=clean_clicked_text(payload.get("vendor_id", ""))[:100],
            landing_page_id=clean_clicked_text(payload.get("landing_page_id", ""))[:100],

            session_key=session_key,
            is_authenticated=is_authenticated,
            is_bot=is_bot_user_agent(user_agent),
        )

        return JsonResponse(
            {
                "ok": True,
                "created": True,
                "event_type": event_type,
                "traffic_source": traffic_source,
                "country": get_country(request),
            }
        )

    except Exception as error:
        return JsonResponse(
            {
                "ok": False,
                "created": False,
                "error": str(error),
            },
            status=200,
        )