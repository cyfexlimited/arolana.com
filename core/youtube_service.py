"""YouTube OAuth 2.0 and resumable upload helpers for Arolana.

Secrets stay server-side. The service uses the YouTube Data API v3 directly
with requests so Arolana does not need the Google client SDK.
"""

import json
import re
import secrets
from html import unescape
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.urls import reverse
from django.utils.html import strip_tags


AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"

SCOPE = "https://www.googleapis.com/auth/youtube.upload"

def _youtube_safe_description(value):
    """
    Convert Arolana/CKEditor HTML into clean plain text suitable
    for the YouTube Data API.

    Preserves paragraph/heading/list spacing instead of joining
    text such as:

        <h3>G-Sync Compatible</h3><p>While this...</p>

    into:

        G-Sync CompatibleWhile this...
    """

    text = str(value or "")

    # ---------------------------------------------------------
    # Preserve meaningful HTML structure as line breaks first.
    # ---------------------------------------------------------
    text = re.sub(
        r"(?is)<\s*(br|/p|/div|/section|/article|/h[1-6]|/li|/tr)\s*/?\s*>",
        "\n",
        text,
    )

    text = re.sub(
        r"(?is)<\s*(p|div|section|article|h[1-6]|li|tr)(?:\s[^>]*)?>",
        "\n",
        text,
    )

    # Lists should read naturally as separate lines.
    text = re.sub(
        r"(?is)<\s*(ul|ol)(?:\s[^>]*)?>",
        "\n",
        text,
    )

    # ---------------------------------------------------------
    # Remove remaining HTML tags.
    # ---------------------------------------------------------
    text = strip_tags(text)

    # ---------------------------------------------------------
    # Decode HTML entities.
    # ---------------------------------------------------------
    text = unescape(text)

    # ---------------------------------------------------------
    # Remove invalid control characters.
    # ---------------------------------------------------------
    text = re.sub(
        r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]",
        "",
        text,
    )

    # Normalize non-breaking spaces.
    text = text.replace("\xa0", " ")

    # Normalize horizontal whitespace.
    text = re.sub(
        r"[ \t]+",
        " ",
        text,
    )

    # Clean whitespace around line breaks.
    text = re.sub(
        r" *\n *",
        "\n",
        text,
    )

    # Prevent huge blank areas.
    text = re.sub(
        r"\n{3,}",
        "\n\n",
        text,
    )

    return text.strip()[:5000]


def configured():
    return bool(
        settings.YOUTUBE_CLIENT_ID
        and settings.YOUTUBE_CLIENT_SECRET
    )


def redirect_uri(request=None):
    configured_uri = str(
        getattr(settings, "YOUTUBE_REDIRECT_URI", "")
        or getattr(settings, "YOUTUBE_OAUTH_REDIRECT_URI", "")
        or ""
    ).strip()

    if configured_uri:
        return configured_uri

    if request is None:
        return ""

    return request.build_absolute_uri(
        reverse("core:youtube_oauth_callback")
    )


def build_authorization_url(request):
    state = secrets.token_urlsafe(32)

    request.session["youtube_oauth_state"] = state
    request.session.save()

    params = {
        "client_id": settings.YOUTUBE_CLIENT_ID,
        "redirect_uri": redirect_uri(request),
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }

    return f"{AUTH_URL}?{urlencode(params)}"


def exchange_code(code, request=None):
    response = requests.post(
        TOKEN_URL,
        data={
            "code": code,
            "client_id": settings.YOUTUBE_CLIENT_ID,
            "client_secret": settings.YOUTUBE_CLIENT_SECRET,
            "redirect_uri": redirect_uri(request),
            "grant_type": "authorization_code",
        },
        timeout=30,
    )

    if not response.ok:
        raise RuntimeError(
            f"YouTube OAuth token exchange failed "
            f"({response.status_code}): {response.text}"
        )

    return response.json()


def refresh_access_token(refresh_token):
    response = requests.post(
        TOKEN_URL,
        data={
            "client_id": settings.YOUTUBE_CLIENT_ID,
            "client_secret": settings.YOUTUBE_CLIENT_SECRET,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=30,
    )

    if not response.ok:
        raise RuntimeError(
            f"YouTube access-token refresh failed "
            f"({response.status_code}): {response.text}"
        )

    return response.json()["access_token"]


def upload_video(
    uploaded_file,
    *,
    title,
    description="",
    privacy_status=None,
    category_id=None,
):
    """Upload a Django UploadedFile/File-like object to YouTube.

    Uses YouTube's resumable upload protocol.

    The uploaded file is streamed directly to YouTube and is not
    automatically stored in an Arolana FileField by this service.
    """

    refresh_token = str(
        getattr(settings, "YOUTUBE_REFRESH_TOKEN", "") or ""
    ).strip()

    if not configured() or not refresh_token:
        raise RuntimeError(
            "YouTube is not connected. Configure "
            "YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, "
            "and YOUTUBE_REFRESH_TOKEN."
        )

    # ---------------------------------------------------------
    # 1. Get a fresh access token
    # ---------------------------------------------------------

    token = refresh_access_token(refresh_token)

    # ---------------------------------------------------------
    # 2. Normalize metadata
    # ---------------------------------------------------------

    privacy_status = (
        privacy_status
        or getattr(
            settings,
            "YOUTUBE_DEFAULT_PRIVACY",
            "unlisted",
        )
    )

    if privacy_status not in {
        "public",
        "unlisted",
        "private",
    }:
        privacy_status = "unlisted"

    category_id = str(
        category_id
        or getattr(
            settings,
            "YOUTUBE_CATEGORY_ID",
            "28",
        )
    )

    title = str(
        title or "Arolana Video"
    )[:100]

    description = _youtube_safe_description(description)

    # ---------------------------------------------------------
    # 3. Determine file information
    # ---------------------------------------------------------

    content_type = str(
        getattr(
            uploaded_file,
            "content_type",
            "",
        )
        or "video/mp4"
    )

    size = int(
        getattr(
            uploaded_file,
            "size",
            0,
        )
        or 0
    )

    if size <= 0:
        raise RuntimeError(
            "YouTube upload failed: video file is empty or "
            "its size could not be determined."
        )

    # ---------------------------------------------------------
    # 4. YouTube video metadata
    # ---------------------------------------------------------

    metadata = {
        "snippet": {
            "title": title,
            "description": description,
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": False,
        },
    }

    # ---------------------------------------------------------
    # 5. Start resumable upload session
    #
    # IMPORTANT:
    # uploadType=resumable is required.
    # ---------------------------------------------------------

    session_url = (
        f"{UPLOAD_URL}"
        f"?uploadType=resumable"
        f"&part=snippet,status"
    )

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Type": content_type,
        "X-Upload-Content-Length": str(size),
    }

    response = requests.post(
        session_url,
        headers=headers,
        data=json.dumps(metadata),
        timeout=30,
    )

    if not response.ok:
        raise RuntimeError(
            "YouTube resumable upload initialization failed "
            f"({response.status_code}): {response.text}"
        )

    location = response.headers.get("Location")

    if not location:
        raise RuntimeError(
            "YouTube did not return a resumable upload URL."
        )

    # ---------------------------------------------------------
    # 6. Reset file position
    # ---------------------------------------------------------

    try:
        uploaded_file.seek(0)
    except Exception:
        pass

    file_object = getattr(
        uploaded_file,
        "file",
        uploaded_file,
    )

    # ---------------------------------------------------------
    # 7. Upload actual video
    # ---------------------------------------------------------

    upload_response = requests.put(
        location,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": content_type,
            "Content-Length": str(size),
        },
        data=file_object,
        timeout=1800,
    )

    if not upload_response.ok:
        raise RuntimeError(
            "YouTube video upload failed "
            f"({upload_response.status_code}): "
            f"{upload_response.text}"
        )

    try:
        payload = upload_response.json()
    except ValueError:
        raise RuntimeError(
            "YouTube upload completed but returned "
            "an invalid JSON response."
        )

    video_id = str(
        payload.get("id") or ""
    ).strip()

    if not video_id:
        raise RuntimeError(
            "YouTube upload completed without returning "
            "a video ID."
        )

    # ---------------------------------------------------------
    # 8. Return normalized Arolana result
    # ---------------------------------------------------------

    return {
        "id": video_id,
        "url": (
            f"https://www.youtube.com/watch?v={video_id}"
        ),
        "embed_url": (
            f"https://www.youtube.com/embed/{video_id}"
        ),
        "thumbnail_url": (
            f"https://img.youtube.com/vi/"
            f"{video_id}/hqdefault.jpg"
        ),
        "privacy_status": privacy_status,
        "category_id": category_id,
    }