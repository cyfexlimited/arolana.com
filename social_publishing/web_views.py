import base64
import hashlib
import hmac
import json
import secrets
import uuid

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .crypto import encrypt_token
from .models import SocialAccount, SocialConnectionStatus, SocialOwnerRole, SocialPlatform
from .oauth import (
    INSTAGRAM_LONG_LIVED_TOKEN_KIND,
    INSTAGRAM_TOKEN_ISSUED_AT_KEY,
    INSTAGRAM_TOKEN_KIND_KEY,
    build_authorization_url,
    exchange_code,
    exchange_instagram_long_lived_token,
    platform_config,
    resolve_identity,
    token_expiry,
)
from .services import normalize_owner_role, platform_enabled, social_publishing_access

User = get_user_model()
LAUNCH_SALT = "arolana.social-publishing.launch.v1"
OAUTH_STATE_SALT = "arolana.social-publishing.oauth-state.v1"


def _role_allowed(user, role):
    role = normalize_owner_role(role)
    if role == SocialOwnerRole.ADMIN:
        return bool(user.is_staff or user.is_superuser)
    if role == SocialOwnerRole.VENDOR:
        return hasattr(user, "vendor_profile")
    if role == SocialOwnerRole.PROVIDER:
        return hasattr(user, "service_provider_profile")
    return False


def _safe_return_url(value):
    value = str(value or "").strip()
    if value.startswith("arolanastaffmobile://"):
        return value
    return ""


def make_launch_token(user, role, platform, return_url=""):
    return signing.dumps(
        {
            "user_id": user.pk,
            "role": normalize_owner_role(role),
            "platform": platform,
            "return_url": _safe_return_url(return_url),
        },
        salt=LAUNCH_SALT,
        compress=True,
    )



def _make_oauth_state(user, role, platform, return_url=""):
    return signing.dumps(
        {
            "user_id": user.pk,
            "role": normalize_owner_role(role),
            "platform": platform,
            "return_url": _safe_return_url(return_url),
            "nonce": secrets.token_urlsafe(16),
        },
        salt=OAUTH_STATE_SALT,
        compress=True,
    )


def _load_oauth_state(value, platform):
    try:
        data = signing.loads(value, salt=OAUTH_STATE_SALT, max_age=600)
    except signing.SignatureExpired as exc:
        raise PermissionError("This social authorization request has expired.") from exc
    except signing.BadSignature as exc:
        raise PermissionError("Invalid social authorization state.") from exc

    if data.get("platform") != platform:
        raise PermissionError("Social authorization platform mismatch.")

    user = User.objects.filter(pk=data.get("user_id"), is_active=True).first()
    if not user:
        raise PermissionError("Arolana account could not be resolved.")

    role = normalize_owner_role(data.get("role"))
    if not _role_allowed(user, role):
        raise PermissionError("This role is not available for this Arolana account.")

    return {
        "state": value,
        "user_id": user.pk,
        "role": role,
        "platform": platform,
        "return_url": _safe_return_url(data.get("return_url")),
    }


def _launch_identity(request, platform):
    launch = request.GET.get("launch", "")
    if launch:
        try:
            data = signing.loads(launch, salt=LAUNCH_SALT, max_age=600)
        except signing.BadSignature:
            raise PermissionError("This social connection link has expired or is invalid.")
        if data.get("platform") != platform:
            raise PermissionError("Social connection platform mismatch.")
        user = User.objects.filter(pk=data.get("user_id"), is_active=True).first()
        if not user:
            raise PermissionError("Arolana account could not be resolved.")
        role = normalize_owner_role(data.get("role"))
        if not _role_allowed(user, role):
            raise PermissionError("This role is not available for this Arolana account.")
        return user, role, _safe_return_url(data.get("return_url"))

    if not request.user.is_authenticated:
        raise PermissionError("Sign in to connect a social account.")
    role = normalize_owner_role(request.GET.get("role", "vendor"))
    if not _role_allowed(request.user, role):
        raise PermissionError("This role is not available for your Arolana account.")
    return request.user, role, ""


def _platform_rows(user, role):
    existing = {
        account.platform: account
        for account in SocialAccount.objects.filter(user=user, owner_role=role)
    }
    rows = []
    for platform, label in SocialPlatform.choices:
        if platform == SocialPlatform.YOUTUBE:
            rows.append({
                "platform": platform,
                "label": label,
                "hosting": True,
                "available": True,
                "configured": True,
                "connected": True,
                "status": "managed",
                "account": None,
            })
            continue
        account = existing.get(platform)
        try:
            configured = platform_config(platform).configured
        except ValueError:
            configured = False
        rows.append({
            "platform": platform,
            "label": label,
            "hosting": False,
            "available": platform_enabled(platform),
            "configured": configured,
            "connected": bool(account and account.is_connected),
            "status": account.status if account else "not_connected",
            "account": account,
        })
    return rows


@login_required
def accounts_page(request):
    try:
        role = normalize_owner_role(request.GET.get("role", "vendor"))
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))
    if not _role_allowed(request.user, role):
        return HttpResponseForbidden("This account does not have the requested role.")

    access = social_publishing_access(request.user, role)
    context = {
        "role": role,
        "access": access,
        "platforms": _platform_rows(request.user, role),
        "workspace_active": "social_accounts",
    }
    if role == SocialOwnerRole.PROVIDER:
        context["provider"] = request.user.service_provider_profile
        template = "social_publishing/provider_accounts.html"
    elif role == SocialOwnerRole.ADMIN:
        template = "social_publishing/admin_accounts.html"
    else:
        template = "social_publishing/vendor_accounts.html"
    return render(request, template, context)


def connect_account(request, platform):
    platform = str(platform or "").strip().lower()
    if platform == SocialPlatform.YOUTUBE or platform not in dict(SocialPlatform.choices):
        return HttpResponseBadRequest("This platform is not connectable here.")
    try:
        user, role, return_url = _launch_identity(request, platform)
    except (PermissionError, ValueError) as exc:
        return HttpResponseForbidden(str(exc))

    access = social_publishing_access(user, role)
    if not access.allowed:
        return HttpResponseForbidden(access.reason)
    if not platform_enabled(platform):
        return HttpResponseForbidden(f"{platform.title()} connection is not enabled yet.")

    state = _make_oauth_state(user, role, platform, return_url)
    request.session["social_oauth"] = {
        "state": state,
        "user_id": user.pk,
        "role": role,
        "platform": platform,
        "return_url": return_url,
    }
    request.session.save()
    try:
        url = build_authorization_url(request, platform, state)
    except RuntimeError as exc:
        return HttpResponseBadRequest(str(exc))
    return redirect(url)


def oauth_callback(request, platform):
    platform = str(platform or "").strip().lower()
    returned_state = request.GET.get("state", "")
    pending = request.session.get("social_oauth") or {}

    if pending.get("platform") == platform and pending.get("state"):
        if returned_state != pending.get("state"):
            return HttpResponseBadRequest("Social authorization state validation failed.")
    else:
        try:
            pending = _load_oauth_state(returned_state, platform)
        except (PermissionError, ValueError) as exc:
            return HttpResponseBadRequest(str(exc))

    return_url = _safe_return_url(pending.get("return_url"))
    role = normalize_owner_role(pending.get("role"))
    user = User.objects.filter(pk=pending.get("user_id"), is_active=True).first()
    if not user or not _role_allowed(user, role):
        return HttpResponseForbidden("Arolana account could not be resolved.")

    error = request.GET.get("error")
    if error:
        request.session.pop("social_oauth", None)
        request.session.save()
        if return_url:
            return redirect(f"{return_url}?status=cancelled&platform={platform}")
        messages.warning(request, f"{platform.title()} connection was cancelled.")
        return redirect(f"{reverse('social_publishing_web:accounts')}?role={role}")

    code = request.GET.get("code", "")
    if not code:
        return HttpResponseBadRequest("Authorization code was not returned.")

    try:
        token_data = exchange_code(request, platform, code)
        if platform == SocialPlatform.INSTAGRAM:
            long_lived = exchange_instagram_long_lived_token(token_data["access_token"])
            token_data = {**token_data, **long_lived}
        identity = resolve_identity(platform, token_data)
        if platform == SocialPlatform.INSTAGRAM:
            identity["platform_metadata"] = {
                **identity.get("platform_metadata", {}),
                INSTAGRAM_TOKEN_KIND_KEY: INSTAGRAM_LONG_LIVED_TOKEN_KIND,
                INSTAGRAM_TOKEN_ISSUED_AT_KEY: timezone.now().isoformat(),
            }
        account, _ = SocialAccount.objects.update_or_create(
            user=user,
            owner_role=role,
            platform=platform,
            defaults={
                **identity,
                "status": SocialConnectionStatus.CONNECTED,
                "access_token_encrypted": encrypt_token(token_data.get("access_token", "")),
                "refresh_token_encrypted": encrypt_token(token_data.get("refresh_token", "")),
                "token_expires_at": token_expiry(token_data),
                "scopes": (
                    [part for part in str(token_data.get("scope", "")).replace(",", " ").split() if part]
                    if isinstance(token_data.get("scope"), str)
                    else (token_data.get("scopes", []) or [])
                ),
                "last_error": "",
            },
        )
        account.save()
    except Exception as exc:
        request.session.pop("social_oauth", None)
        request.session.save()
        if return_url:
            return redirect(f"{return_url}?status=error&platform={platform}")
        messages.error(request, f"Could not connect {platform.title()}. Please try again.")
        return redirect(f"{reverse('social_publishing_web:accounts')}?role={role}")

    request.session.pop("social_oauth", None)
    request.session.save()
    if return_url:
        return redirect(f"{return_url}?status=connected&platform={platform}")
    messages.success(request, f"{platform.title()} connected successfully.")
    return redirect(f"{reverse('social_publishing_web:accounts')}?role={role}")


@login_required
@require_POST
def disconnect_account(request, platform):
    try:
        role = normalize_owner_role(request.POST.get("role", "vendor"))
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))
    if not _role_allowed(request.user, role):
        return HttpResponseForbidden("This role is not available for your Arolana account.")
    account = SocialAccount.objects.filter(
        user=request.user,
        owner_role=role,
        platform=platform,
    ).first()
    if account:
        account.delete()
        messages.success(request, f"{platform.title()} disconnected.")
    return redirect(f"{reverse('social_publishing_web:accounts')}?role={role}")

def _meta_b64url_decode(value):
    value = str(value or "")
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("utf-8"))


def _parse_instagram_signed_request(value):
    value = str(value or "").strip()
    secret = str(
        getattr(settings, "SOCIAL_PUBLISHING_INSTAGRAM_APP_SECRET", "") or ""
    ).strip()

    if not value:
        raise ValueError("signed_request is required.")
    if not secret:
        raise ValueError("Instagram app secret is not configured.")

    try:
        encoded_sig, encoded_payload = value.split(".", 1)
    except ValueError as exc:
        raise ValueError("Invalid signed_request format.") from exc

    supplied_sig = _meta_b64url_decode(encoded_sig)
    expected_sig = hmac.new(
        secret.encode("utf-8"),
        encoded_payload.encode("utf-8"),
        hashlib.sha256,
    ).digest()

    if not hmac.compare_digest(supplied_sig, expected_sig):
        raise ValueError("Invalid signed_request signature.")

    return json.loads(_meta_b64url_decode(encoded_payload).decode("utf-8"))


@csrf_exempt
@require_POST
def meta_instagram_deauthorize(request):
    try:
        payload = _parse_instagram_signed_request(
            request.POST.get("signed_request")
        )
    except (ValueError, json.JSONDecodeError) as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=400)

    meta_user_id = str(
        payload.get("user_id") or payload.get("id") or ""
    ).strip()

    SocialAccount.objects.filter(
        platform=SocialPlatform.INSTAGRAM,
        external_account_id=meta_user_id,
    ).delete()

    return JsonResponse({"success": True, "deauthorized": True})


@csrf_exempt
@require_POST
def meta_instagram_data_deletion(request):
    try:
        payload = _parse_instagram_signed_request(
            request.POST.get("signed_request")
        )
    except (ValueError, json.JSONDecodeError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    meta_user_id = str(
        payload.get("user_id") or payload.get("id") or ""
    ).strip()

    SocialAccount.objects.filter(
        platform=SocialPlatform.INSTAGRAM,
        external_account_id=meta_user_id,
    ).delete()

    confirmation_code = uuid.uuid4().hex
    status_url = request.build_absolute_uri(
        reverse("social_publishing_web:meta_data_deletion_status")
    )
    status_url = f"{status_url}?code={confirmation_code}"

    return JsonResponse({
        "url": status_url,
        "confirmation_code": confirmation_code,
    })


@require_GET
def meta_instagram_data_deletion_status(request):
    code = str(request.GET.get("code") or "").strip()
    if not code:
        return HttpResponseBadRequest("A deletion confirmation code is required.")

    return HttpResponse(
        f"Arolana Instagram data deletion request processed. Confirmation code: {code}",
        content_type="text/plain; charset=utf-8",
    )
