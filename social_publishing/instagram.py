import time

import requests
from django.conf import settings

from .crypto import decrypt_token
from .models import SocialPlatform


DEFAULT_HTTP_TIMEOUT = 30
DEFAULT_PROCESSING_TIMEOUT = 300
DEFAULT_POLL_INTERVAL = 5

TERMINAL_ERROR_STATUSES = {
    "ERROR",
    "EXPIRED",
}

READY_STATUSES = {
    "FINISHED",
    "PUBLISHED",
}


class InstagramPublishingError(RuntimeError):
    """Raised when Instagram rejects or cannot complete a publishing action."""

    def __init__(
        self,
        message,
        *,
        status_code=None,
        error_code="",
        error_subcode="",
        response_data=None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = str(error_code or "")
        self.error_subcode = str(error_subcode or "")
        self.response_data = response_data or {}


def _graph_version():
    version = str(
        getattr(
            settings,
            "SOCIAL_PUBLISHING_META_GRAPH_VERSION",
            "v25.0",
        )
        or "v25.0"
    ).strip()

    if not version.startswith("v"):
        version = f"v{version}"

    return version


def _graph_base_url():
    return f"https://graph.instagram.com/{_graph_version()}"


def _safe_response_json(response):
    try:
        data = response.json()
    except ValueError:
        data = {}

    if not isinstance(data, dict):
        return {}

    # Never allow credentials to leak into logs or exception metadata.
    data.pop("access_token", None)

    return data


def _raise_for_instagram_error(response, action):
    if response.ok:
        return

    data = _safe_response_json(response)
    error = data.get("error") or {}

    if not isinstance(error, dict):
        error = {}

    message = (
        error.get("message")
        or data.get("message")
        or f"Instagram {action} failed."
    )

    raise InstagramPublishingError(
        message,
        status_code=response.status_code,
        error_code=error.get("code", ""),
        error_subcode=error.get("error_subcode", ""),
        response_data=data,
    )


def _account_credentials(account):
    if account.platform != SocialPlatform.INSTAGRAM:
        raise InstagramPublishingError(
            "The selected social account is not an Instagram account."
        )

    if not account.is_connected:
        raise InstagramPublishingError(
            "The Instagram account is not currently connected."
        )

    instagram_user_id = str(
        account.external_account_id or ""
    ).strip()

    if not instagram_user_id:
        raise InstagramPublishingError(
            "The Instagram account has no external account ID."
        )

    access_token = decrypt_token(
        account.access_token_encrypted
    )

    if not access_token:
        raise InstagramPublishingError(
            "The Instagram account has no usable access token."
        )

    return instagram_user_id, access_token


def verify_instagram_account(account):
    """
    Verify the stored Instagram account and return its safe identity.
    """

    _instagram_user_id, access_token = _account_credentials(
        account
    )

    response = requests.get(
        f"{_graph_base_url()}/me",
        params={
            "fields": "id,username,account_type,profile_picture_url",
            "access_token": access_token,
        },
        timeout=DEFAULT_HTTP_TIMEOUT,
    )

    _raise_for_instagram_error(
        response,
        "account verification",
    )

    return _safe_response_json(response)


def create_reel_container(
    account,
    *,
    video_url,
    caption="",
    share_to_feed=True,
):
    """
    Ask Instagram to fetch a staged video and create a Reel container.
    """

    instagram_user_id, access_token = _account_credentials(
        account
    )

    video_url = str(video_url or "").strip()

    if not video_url.startswith("https://"):
        raise InstagramPublishingError(
            "Instagram requires an HTTPS video delivery URL."
        )

    payload = {
        "media_type": "REELS",
        "video_url": video_url,
        "access_token": access_token,
    }

    caption = str(caption or "").strip()

    if caption:
        payload["caption"] = caption

    if share_to_feed:
        payload["share_to_feed"] = "true"

    response = requests.post(
        f"{_graph_base_url()}/{instagram_user_id}/media",
        data=payload,
        timeout=DEFAULT_HTTP_TIMEOUT,
    )

    _raise_for_instagram_error(
        response,
        "Reel container creation",
    )

    data = _safe_response_json(response)
    container_id = str(data.get("id") or "").strip()

    if not container_id:
        raise InstagramPublishingError(
            "Instagram created no media container ID.",
            response_data=data,
        )

    return {
        "container_id": container_id,
        "response": data,
    }


def get_container_status(account, container_id):
    """
    Return Instagram's processing status for a media container.
    """

    _instagram_user_id, access_token = _account_credentials(
        account
    )

    container_id = str(container_id or "").strip()

    if not container_id:
        raise InstagramPublishingError(
            "Instagram container ID is required."
        )

    response = requests.get(
        f"{_graph_base_url()}/{container_id}",
        params={
            "fields": "status_code,status",
            "access_token": access_token,
        },
        timeout=DEFAULT_HTTP_TIMEOUT,
    )

    _raise_for_instagram_error(
        response,
        "container status check",
    )

    data = _safe_response_json(response)

    status_code = str(
        data.get("status_code")
        or data.get("status")
        or ""
    ).upper()

    return {
        "container_id": container_id,
        "status_code": status_code,
        "response": data,
    }


def wait_for_container(
    account,
    container_id,
    *,
    timeout=DEFAULT_PROCESSING_TIMEOUT,
    poll_interval=DEFAULT_POLL_INTERVAL,
):
    """
    Poll Instagram until the Reel container is ready to publish.
    """

    started_at = time.monotonic()

    while True:
        status = get_container_status(
            account,
            container_id,
        )

        status_code = status["status_code"]

        if status_code in READY_STATUSES:
            return status

        if status_code in TERMINAL_ERROR_STATUSES:
            raise InstagramPublishingError(
                f"Instagram Reel processing ended with status "
                f"{status_code}.",
                response_data=status["response"],
            )

        elapsed = time.monotonic() - started_at

        if elapsed >= timeout:
            raise InstagramPublishingError(
                "Instagram Reel processing timed out.",
                response_data=status["response"],
            )

        time.sleep(max(1, poll_interval))


def publish_reel_container(account, container_id):
    """
    Publish a Reel container after Instagram has finished processing it.
    """

    instagram_user_id, access_token = _account_credentials(
        account
    )

    container_id = str(container_id or "").strip()

    if not container_id:
        raise InstagramPublishingError(
            "Instagram container ID is required."
        )

    response = requests.post(
        f"{_graph_base_url()}/{instagram_user_id}/media_publish",
        data={
            "creation_id": container_id,
            "access_token": access_token,
        },
        timeout=DEFAULT_HTTP_TIMEOUT,
    )

    _raise_for_instagram_error(
        response,
        "Reel publishing",
    )

    data = _safe_response_json(response)
    media_id = str(data.get("id") or "").strip()

    if not media_id:
        raise InstagramPublishingError(
            "Instagram published no media ID.",
            response_data=data,
        )

    return {
        "media_id": media_id,
        "response": data,
    }


def get_published_media(account, media_id):
    """
    Retrieve safe metadata and permalink for published Instagram media.
    """

    _instagram_user_id, access_token = _account_credentials(
        account
    )

    media_id = str(media_id or "").strip()

    if not media_id:
        raise InstagramPublishingError(
            "Instagram media ID is required."
        )

    response = requests.get(
        f"{_graph_base_url()}/{media_id}",
        params={
            "fields": (
                "id,permalink,media_type,"
                "username,timestamp"
            ),
            "access_token": access_token,
        },
        timeout=DEFAULT_HTTP_TIMEOUT,
    )

    _raise_for_instagram_error(
        response,
        "published media lookup",
    )

    return _safe_response_json(response)


def publish_reel(
    account,
    *,
    video_url,
    caption="",
    share_to_feed=True,
    processing_timeout=DEFAULT_PROCESSING_TIMEOUT,
):
    """
    Complete synchronous Reel publishing flow.

    This is suitable for controlled validation and tests.
    Long-running production publishing should eventually execute
    through Arolana's background/retry worker rather than block an
    HTTP request.
    """

    container = create_reel_container(
        account,
        video_url=video_url,
        caption=caption,
        share_to_feed=share_to_feed,
    )

    container_id = container["container_id"]

    processing = wait_for_container(
        account,
        container_id,
        timeout=processing_timeout,
    )

    published = publish_reel_container(
        account,
        container_id,
    )

    media = get_published_media(
        account,
        published["media_id"],
    )

    return {
        "container_id": container_id,
        "processing": processing,
        "media_id": published["media_id"],
        "permalink": media.get("permalink", ""),
        "media": media,
    }
