"""YouTube OAuth 2.0 and resumable upload helpers for Arolana.

Secrets stay server-side. The service uses the YouTube Data API v3 directly
with requests so Arolana does not need the Google client SDK.
"""

import json
import logging
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
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"

logger = logging.getLogger(__name__)

SCOPE = " ".join(
    (
        "https://www.googleapis.com/auth/youtube.upload",
        "https://www.googleapis.com/auth/youtube.readonly",
    )
)


class YouTubeUploadError(RuntimeError):
    """A sanitized, structured failure from the primary YouTube upload path."""

    def __init__(self, message, *, stage="unknown", code="youtube_unknown_error", http_status=None):
        super().__init__(message)
        self.stage = stage
        self.code = code
        self.http_status = http_status


def safe_upload_error_details(exc):
    """Return only presentation-safe upload diagnostics for an AJAX response."""
    if isinstance(exc, YouTubeUploadError):
        return {
            "stage": exc.stage,
            "code": exc.code,
            "message": str(exc),
        }
    return {
        "stage": "unknown",
        "code": "youtube_unknown_error",
        "message": "YouTube upload failed. Please try again.",
    }


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
    try:
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
    except requests.RequestException as exc:
        raise YouTubeUploadError(
            "Could not refresh the Arolana YouTube connection.",
            stage="token_refresh",
            code="youtube_token_refresh_failed",
        ) from exc

    if not response.ok:
        raise YouTubeUploadError(
            "Could not refresh the Arolana YouTube connection.",
            stage="token_refresh",
            code="youtube_token_refresh_failed",
            http_status=response.status_code,
        )
    try:
        return response.json()["access_token"]
    except (KeyError, TypeError, ValueError) as exc:
        raise YouTubeUploadError(
            "Could not refresh the Arolana YouTube connection.",
            stage="token_refresh",
            code="youtube_token_refresh_failed",
            http_status=response.status_code,
        ) from exc


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
        raise YouTubeUploadError(
            "Could not refresh the Arolana YouTube connection.",
            stage="token_refresh",
            code="youtube_token_refresh_failed",
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
        raise YouTubeUploadError(
            "The selected video could not be prepared for YouTube.",
            stage="validation",
            code="youtube_validation_failed",
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
            "embeddable": True,
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

    try:
        response = requests.post(
            session_url,
            headers=headers,
            data=json.dumps(metadata),
            timeout=30,
        )
    except requests.RequestException as exc:
        raise YouTubeUploadError(
            "Could not start the YouTube upload.",
            stage="upload_initialization",
            code="youtube_upload_init_failed",
        ) from exc

    if not response.ok:
        raise YouTubeUploadError(
            "Could not start the YouTube upload.",
            stage="upload_initialization",
            code="youtube_upload_init_failed",
            http_status=response.status_code,
        )

    location = response.headers.get("Location")

    if not location:
        raise YouTubeUploadError(
            "Could not start the YouTube upload.",
            stage="upload_initialization",
            code="youtube_upload_init_failed",
            http_status=response.status_code,
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

    try:
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
    except requests.RequestException as exc:
        raise YouTubeUploadError(
            "YouTube could not complete the video upload.",
            stage="video_upload",
            code="youtube_upload_failed",
        ) from exc

    if not upload_response.ok:
        raise YouTubeUploadError(
            "YouTube could not complete the video upload.",
            stage="video_upload",
            code="youtube_upload_failed",
            http_status=upload_response.status_code,
        )

    try:
        payload = upload_response.json()
    except ValueError:
        raise YouTubeUploadError(
            "YouTube could not complete the video upload.",
            stage="video_upload",
            code="youtube_upload_failed",
            http_status=upload_response.status_code,
        )

    video_id = str(
        payload.get("id") or ""
    ).strip()

    if not video_id:
        raise YouTubeUploadError(
            "YouTube could not complete the video upload.",
            stage="video_upload",
            code="youtube_upload_failed",
            http_status=upload_response.status_code,
        )

    returned_status = payload.get("status") or {}
    returned_embeddable = returned_status.get("embeddable")
    if returned_embeddable is False:
        logger.error(
            "Arolana YouTube upload returned non-embeddable status video_id=%s",
            video_id,
        )
        raise YouTubeUploadError(
            "YouTube could not complete the video upload.",
            stage="video_upload",
            code="youtube_upload_failed",
            http_status=upload_response.status_code,
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
            f"https://www.youtube.com/embed/{video_id}?rel=0&playsinline=1&enablejsapi=1"
        ),
        "thumbnail_url": (
            f"https://img.youtube.com/vi/"
            f"{video_id}/hqdefault.jpg"
        ),
        "privacy_status": privacy_status,
        "category_id": category_id,
        "embeddable": returned_embeddable,
        "ownership": "arolana",
    }


def get_video_embeddability(video_id, *, access_token=None):
    """Return a sanitized, read-only YouTube status for one existing video."""
    video_id = str(video_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,32}", video_id):
        return {"video_id": video_id, "state": "invalid", "embeddable": None}

    if not access_token:
        refresh_token = str(
            getattr(settings, "YOUTUBE_REFRESH_TOKEN", "") or ""
        ).strip()
        if not configured() or not refresh_token:
            return {"video_id": video_id, "state": "unavailable", "embeddable": None}
        access_token = refresh_access_token(refresh_token)

    response = requests.get(
        VIDEOS_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        params={"part": "status,snippet,processingDetails", "id": video_id},
        timeout=30,
    )
    if not response.ok:
        reason = "youtube_status_check_failed"
        try:
            reason = (
                response.json().get("error", {}).get("errors", [{}])[0].get("reason")
                or reason
            )
        except (ValueError, TypeError, IndexError):
            pass
        logger.warning(
            "YouTube embeddability check failed video_id=%s http_status=%s reason=%s",
            video_id,
            response.status_code,
            reason,
        )
        return {
            "video_id": video_id,
            "state": "unavailable",
            "embeddable": None,
            "http_status": response.status_code,
            "reason": reason,
        }

    items = response.json().get("items") or []
    if not items:
        return {"video_id": video_id, "state": "missing", "embeddable": False}

    item = items[0]
    status = item.get("status") or {}
    snippet = item.get("snippet") or {}
    processing = item.get("processingDetails") or {}
    embeddable = status.get("embeddable")
    return {
        "video_id": video_id,
        "state": "embeddable" if embeddable is True else "non_embeddable",
        "embeddable": embeddable,
        "privacy_status": status.get("privacyStatus"),
        "upload_status": status.get("uploadStatus"),
        "processing_status": processing.get("processingStatus"),
        "channel_id": snippet.get("channelId"),
        "channel_title": snippet.get("channelTitle"),
    }
