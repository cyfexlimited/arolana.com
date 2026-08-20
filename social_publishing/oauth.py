"""OAuth connection adapters for Arolana social publishing.

Phase 2 establishes account authorization only. Actual video publishing remains
behind the platform feature flags and is implemented by later publisher adapters.
"""

from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from .models import SocialPlatform


@dataclass(frozen=True)
class OAuthPlatformConfig:
    platform: str
    client_id: str
    client_secret: str
    authorization_url: str
    token_url: str
    scopes: tuple[str, ...]

    @property
    def configured(self):
        return bool(self.client_id and self.client_secret and self.authorization_url and self.token_url)


def _split_scopes(value, defaults):
    if not value:
        return tuple(defaults)
    if isinstance(value, (list, tuple)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return tuple(part.strip() for part in str(value).replace(",", " ").split() if part.strip())


def platform_config(platform):
    platform = str(platform or "").strip().lower()
    meta_version = str(getattr(settings, "SOCIAL_PUBLISHING_META_GRAPH_VERSION", "v25.0") or "v25.0").strip()
    if not meta_version.startswith("v"):
        meta_version = f"v{meta_version}"

    if platform == SocialPlatform.INSTAGRAM:
        return OAuthPlatformConfig(
            platform=platform,
            client_id=str(getattr(settings, "SOCIAL_PUBLISHING_INSTAGRAM_APP_ID", "") or "").strip(),
            client_secret=str(getattr(settings, "SOCIAL_PUBLISHING_INSTAGRAM_APP_SECRET", "") or "").strip(),
            authorization_url="https://www.instagram.com/oauth/authorize",
            token_url="https://api.instagram.com/oauth/access_token",
            scopes=_split_scopes(
                getattr(settings, "SOCIAL_PUBLISHING_INSTAGRAM_SCOPES", ""),
                ("instagram_business_basic", "instagram_business_content_publish"),
            ),
        )

    if platform == SocialPlatform.FACEBOOK:
        return OAuthPlatformConfig(
            platform=platform,
            client_id=str(getattr(settings, "SOCIAL_PUBLISHING_META_APP_ID", "") or "").strip(),
            client_secret=str(getattr(settings, "SOCIAL_PUBLISHING_META_APP_SECRET", "") or "").strip(),
            authorization_url=f"https://www.facebook.com/{meta_version}/dialog/oauth",
            token_url=f"https://graph.facebook.com/{meta_version}/oauth/access_token",
            scopes=_split_scopes(
                getattr(settings, "SOCIAL_PUBLISHING_FACEBOOK_SCOPES", ""),
                ("pages_show_list", "pages_read_engagement", "pages_manage_posts"),
            ),
        )

    if platform == SocialPlatform.TIKTOK:
        return OAuthPlatformConfig(
            platform=platform,
            client_id=str(getattr(settings, "SOCIAL_PUBLISHING_TIKTOK_CLIENT_KEY", "") or "").strip(),
            client_secret=str(getattr(settings, "SOCIAL_PUBLISHING_TIKTOK_CLIENT_SECRET", "") or "").strip(),
            authorization_url="https://www.tiktok.com/v2/auth/authorize/",
            token_url="https://open.tiktokapis.com/v2/oauth/token/",
            scopes=_split_scopes(
                getattr(settings, "SOCIAL_PUBLISHING_TIKTOK_SCOPES", ""),
                ("user.info.basic", "video.publish"),
            ),
        )

    if platform == SocialPlatform.LINKEDIN:
        return OAuthPlatformConfig(
            platform=platform,
            client_id=str(getattr(settings, "SOCIAL_PUBLISHING_LINKEDIN_CLIENT_ID", "") or "").strip(),
            client_secret=str(getattr(settings, "SOCIAL_PUBLISHING_LINKEDIN_CLIENT_SECRET", "") or "").strip(),
            authorization_url="https://www.linkedin.com/oauth/v2/authorization",
            token_url="https://www.linkedin.com/oauth/v2/accessToken",
            scopes=_split_scopes(
                getattr(settings, "SOCIAL_PUBLISHING_LINKEDIN_SCOPES", ""),
                ("openid", "profile", "w_member_social"),
            ),
        )

    raise ValueError("This platform does not use vendor/provider OAuth in Arolana.")


def callback_uri(request, platform):
    configured = str(
        getattr(settings, f"SOCIAL_PUBLISHING_{str(platform).upper()}_REDIRECT_URI", "") or ""
    ).strip()
    if configured:
        return configured
    return request.build_absolute_uri(
        reverse("social_publishing_web:oauth_callback", kwargs={"platform": platform})
    )


def build_authorization_url(request, platform, state):
    cfg = platform_config(platform)
    if not cfg.configured:
        raise RuntimeError(f"{platform.title()} OAuth is not configured.")

    redirect_uri = callback_uri(request, platform)
    if platform == SocialPlatform.TIKTOK:
        params = {
            "client_key": cfg.client_id,
            "response_type": "code",
            "scope": ",".join(cfg.scopes),
            "redirect_uri": redirect_uri,
            "state": state,
        }
    else:
        params = {
            "client_id": cfg.client_id,
            "response_type": "code",
            "scope": " ".join(cfg.scopes) if platform == SocialPlatform.LINKEDIN else ",".join(cfg.scopes),
            "redirect_uri": redirect_uri,
            "state": state,
        }
    return f"{cfg.authorization_url}?{urlencode(params)}"


def exchange_code(request, platform, code):
    cfg = platform_config(platform)
    redirect_uri = callback_uri(request, platform)

    if platform == SocialPlatform.TIKTOK:
        payload = {
            "client_key": cfg.client_id,
            "client_secret": cfg.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        }
    else:
        payload = {
            "client_id": cfg.client_id,
            "client_secret": cfg.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        }

    response = requests.post(cfg.token_url, data=payload, timeout=30)
    if not response.ok:
        raise RuntimeError(
            f"{platform.title()} token exchange failed ({response.status_code})."
        )
    data = response.json()
    if not data.get("access_token"):
        raise RuntimeError(f"{platform.title()} did not return an access token.")
    return data


def token_expiry(token_data):
    seconds = token_data.get("expires_in")
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return None
    return timezone.now() + timedelta(seconds=max(0, seconds))


def resolve_identity(platform, token_data):
    """Return a safe baseline identity without requiring publishing permissions.

    Deeper Page/Instagram-account selection is intentionally deferred to the
    publishing adapter gate. The OAuth connection itself remains valid and can
    be re-verified later.
    """
    if platform == SocialPlatform.TIKTOK:
        identifier = token_data.get("open_id") or token_data.get("union_id") or ""
        return {
            "external_account_id": identifier,
            "account_name": "TikTok account",
            "account_username": "",
            "platform_metadata": {"open_id": token_data.get("open_id", "")},
        }

    if platform == SocialPlatform.LINKEDIN:
        return {
            "external_account_id": "",
            "account_name": "LinkedIn account",
            "account_username": "",
            "platform_metadata": {},
        }

    return {
        "external_account_id": token_data.get("user_id", "") or token_data.get("id", ""),
        "account_name": "Instagram account" if platform == SocialPlatform.INSTAGRAM else "Facebook account",
        "account_username": "",
        "platform_metadata": {},
    }
