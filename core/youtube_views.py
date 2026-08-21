from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.html import escape

from .youtube_service import build_authorization_url, configured, exchange_code, redirect_uri


@staff_member_required
def youtube_connect(request):
    if not configured():
        return HttpResponse(
            "<h1>Arolana YouTube</h1><p>Configure YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET first.</p>",
            status=503,
        )
    return redirect(build_authorization_url(request))


@staff_member_required
def youtube_oauth_callback(request):
    expected = request.session.pop("youtube_oauth_state", "")
    supplied = request.GET.get("state", "")
    if not expected or not supplied or not secrets_compare(expected, supplied):
        return HttpResponse("Invalid YouTube OAuth state.", status=400)
    if request.GET.get("error"):
        return HttpResponse(f"YouTube authorization was cancelled: {escape(request.GET.get('error'))}", status=400)
    code = request.GET.get("code", "")
    if not code:
        return HttpResponse("Google did not return an authorization code.", status=400)
    try:
        tokens = exchange_code(code, request)
    except Exception as exc:
        return HttpResponse(f"YouTube OAuth failed: {escape(exc)}", status=502)
    refresh_token = str(tokens.get("refresh_token") or "").strip()
    if not refresh_token:
        return HttpResponse(
            "Google did not return a refresh token. Revoke Arolana's existing Google access and reconnect with consent.",
            status=502,
        )
    # Deliberately display the one-time credential rather than writing secrets
    # into the database. Put it in Railway as YOUTUBE_REFRESH_TOKEN.
    return HttpResponse(
        "<h1>Arolana YouTube connected</h1>"
        "<p>Copy this refresh token into Railway as <b>YOUTUBE_REFRESH_TOKEN</b>. "
        "Do not commit it to Git or put it in the mobile app.</p>"
        f"<textarea style='width:90%;height:140px'>{escape(refresh_token)}</textarea>"
        f"<p>OAuth redirect URI: <code>{escape(redirect_uri(request))}</code></p>"
        f"<p><a href='{escape(reverse('core:youtube_status'))}'>Check connection status</a></p>",
        content_type="text/html",
    )


def secrets_compare(a, b):
    import hmac
    return hmac.compare_digest(str(a), str(b))


@staff_member_required
def youtube_status(request):
    from django.conf import settings
    payload = {
        "configured": configured(),
        "client_id_configured": bool(settings.YOUTUBE_CLIENT_ID),
        "client_secret_configured": bool(settings.YOUTUBE_CLIENT_SECRET),
        "refresh_token_configured": bool(settings.YOUTUBE_REFRESH_TOKEN),
        "category_id": settings.YOUTUBE_CATEGORY_ID,
        "default_privacy": settings.YOUTUBE_DEFAULT_PRIVACY,
        "redirect_uri": redirect_uri(request),
    }
    return JsonResponse(payload)
