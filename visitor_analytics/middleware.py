from .models import PageVisit
from .utils import (
    get_browser,
    get_client_ip,
    get_country,
    get_device_type,
    get_operating_system,
    get_referrer,
    get_user_agent,
    is_bot_user_agent,
    normalize_path,
    should_skip_tracking,
)


class PageVisitTrackingMiddleware:
    """
    Records page visits without affecting the website if analytics fails.

    It skips:
    - admin
    - static/media files
    - analytics endpoint
    - health checks
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        try:
            if should_skip_tracking(request):
                return response

            if request.method not in ["GET", "HEAD"]:
                return response

            content_type = response.get("Content-Type", "")
            if content_type and "text/html" not in content_type:
                return response

            user_agent = get_user_agent(request)
            ip_address = get_client_ip(request)

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

            page_url = request.build_absolute_uri()[:1000]

            PageVisit.objects.create(
                user=user,
                ip_address=ip_address or None,
                country=get_country(request),
                user_agent=user_agent,
                device_type=get_device_type(user_agent),
                browser=get_browser(user_agent),
                operating_system=get_operating_system(user_agent),
                referrer=get_referrer(request),
                page_url=page_url,
                path=normalize_path(request.path),
                session_key=session_key,
                method=request.method,
                status_code=getattr(response, "status_code", None),
                is_authenticated=is_authenticated,
                is_bot=is_bot_user_agent(user_agent),
            )

        except Exception:
            # Never break Arolana because analytics failed.
            pass

        return response