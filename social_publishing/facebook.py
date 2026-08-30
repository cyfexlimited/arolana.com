"""Minimal Facebook Page video publishing adapter.

The connected ``SocialAccount`` contains a Meta-approved Page access token
encrypted at rest.  This module never returns that token or raw provider data.
"""

import logging

import requests
from django.conf import settings

from .crypto import decrypt_token
from .models import SocialPlatform


DEFAULT_HTTP_TIMEOUT = 30
logger = logging.getLogger(__name__)


class FacebookPublishingError(RuntimeError):
    def __init__(self, message, *, status_code=None, error_code=""):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = str(error_code or "")


def _graph_version():
    version = str(getattr(settings, "SOCIAL_PUBLISHING_META_GRAPH_VERSION", "v25.0") or "v25.0").strip()
    return version if version.startswith("v") else f"v{version}"


def _credentials(account):
    if account.platform != SocialPlatform.FACEBOOK or not account.is_connected:
        raise FacebookPublishingError("The Facebook Page is not currently connected.")
    page_id = str(account.external_account_id or "").strip()
    token = decrypt_token(account.access_token_encrypted)
    if not page_id or not token:
        raise FacebookPublishingError("The Facebook Page connection is incomplete.")
    return page_id, token


def _safe_error(response, action):
    try:
        data = response.json() or {}
    except ValueError:
        data = {}
    error = data.get("error") if isinstance(data, dict) else {}
    error = error if isinstance(error, dict) else {}
    raise FacebookPublishingError(
        str(error.get("message") or f"Facebook {action} failed."),
        status_code=response.status_code,
        error_code=error.get("code", ""),
    )


def validate_selected_page_access(account):
    """Confirm the stored Page token still authorizes exactly this Page.

    This intentionally queries only the persisted Page ID. It never enumerates
    a user's other Pages and never substitutes a different Page as a fallback.
    """
    page_id, access_token = _credentials(account)
    try:
        response = requests.get(
            f"https://graph.facebook.com/{_graph_version()}/{page_id}",
            params={"fields": "id", "access_token": access_token},
            timeout=DEFAULT_HTTP_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise FacebookPublishingError(
            "Facebook Page validation could not be completed."
        ) from exc
    if not response.ok:
        _safe_error(response, "Page validation")
    try:
        returned_page_id = str((response.json() or {}).get("id") or "").strip()
    except ValueError as exc:
        raise FacebookPublishingError("Facebook returned an invalid Page validation response.") from exc
    if returned_page_id != page_id:
        raise FacebookPublishingError(
            "The selected Facebook Page could not be validated.",
            error_code="page_identity_mismatch",
        )
    logger.info(
        "Facebook Page validation succeeded social_account_id=%s page_id=%s",
        account.pk,
        page_id,
    )
    return page_id, access_token


def publish_page_video(account, *, video_url, description=""):
    """Publish a staged HTTPS video to the selected Facebook Page."""

    page_id, access_token = validate_selected_page_access(account)
    video_url = str(video_url or "").strip()
    if not video_url.startswith("https://"):
        raise FacebookPublishingError("Facebook video delivery requires HTTPS.")

    response = requests.post(
        f"https://graph.facebook.com/{_graph_version()}/{page_id}/videos",
        data={
            "file_url": video_url,
            "description": str(description or "")[:2200],
            "access_token": access_token,
        },
        timeout=DEFAULT_HTTP_TIMEOUT,
    )
    if not response.ok:
        _safe_error(response, "video publishing")
    try:
        data = response.json() or {}
    except ValueError as exc:
        raise FacebookPublishingError("Facebook returned an invalid publishing response.") from exc
    video_id = str(data.get("id") or data.get("video_id") or "").strip()
    if not video_id:
        raise FacebookPublishingError("Facebook returned no video ID.")
    return {"video_id": video_id, "post_id": str(data.get("post_id") or "").strip()}
