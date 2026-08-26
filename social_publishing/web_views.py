import base64
import hashlib
import hmac
import json
import secrets

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
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from .connection_security import (
    SocialOAuthStateError, audit_connection, consume_oauth_state, create_oauth_state,
)
from .crypto import decrypt_token, encrypt_token
from .models import (
    SocialAccount, SocialConnectionStatus, SocialDataDeletionRequest,
    SocialOAuthState, SocialOwnerRole, SocialPlatform,
)
from .oauth import (
    INSTAGRAM_LONG_LIVED_TOKEN_KIND,
    INSTAGRAM_TOKEN_ISSUED_AT_KEY,
    INSTAGRAM_TOKEN_KIND_KEY,
    build_authorization_url,
    exchange_code,
    exchange_instagram_long_lived_token,
    exchange_facebook_long_lived_token,
    discover_facebook_pages,
    platform_config,
    resolve_identity,
    resolve_facebook_user_identity,
    revoke_facebook_access,
    token_expiry,
)
from .services import (
    ensure_instagram_account_identity,
    normalize_owner_role,
    platform_connection_enabled,
    social_publishing_access,
)

User = get_user_model()
LAUNCH_SALT = "arolana.social-publishing.launch.v1"
OAUTH_STATE_SALT = "arolana.social-publishing.oauth-state.v1"
FACEBOOK_SELECTION_SALT = "arolana.social-publishing.facebook-selection.v1"


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
    if value.startswith("/") and not value.startswith("//"):
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



def _signed_oauth_state(state, raw_token, session_identity="", mobile_identity=""):
    return signing.dumps(
        {
            "state_id": state.pk,
            "token": raw_token,
            "user_id": state.user_id,
            "role": state.owner_role,
            "platform": state.platform,
            "mobile_identity": mobile_identity,
        },
        salt=OAUTH_STATE_SALT,
        compress=True,
    )


def _load_oauth_state(value, platform, request=None):
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

    mobile_identity = data.get("mobile_identity", "")
    session_identity = ""
    if request is not None and not mobile_identity:
        session_identity = request.session.session_key or ""
    state = consume_oauth_state(
        raw_token=data.get("token"), user_id=user.pk, owner_role=role, platform=platform,
        session_identity=session_identity, mobile_identity=mobile_identity,
    )
    if state.pk != data.get("state_id"):
        raise PermissionError("Invalid social authorization state.")
    return state


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
        return user, role, _safe_return_url(data.get("return_url")), launch

    if not request.user.is_authenticated:
        raise PermissionError("Sign in to connect a social account.")
    role = normalize_owner_role(request.GET.get("role", "vendor"))
    if not _role_allowed(request.user, role):
        raise PermissionError("This role is not available for your Arolana account.")
    return request.user, role, "", ""


def _platform_rows(user, role):
    existing = {
        account.platform: account
        for account in SocialAccount.objects.filter(user=user, owner_role=role)
    }
    ensure_instagram_account_identity(existing.get(SocialPlatform.INSTAGRAM))
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
            "available": platform_connection_enabled(platform),
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
        user, role, return_url, mobile_identity = _launch_identity(request, platform)
    except (PermissionError, ValueError) as exc:
        return HttpResponseForbidden(str(exc))

    access = social_publishing_access(user, role)
    if not access.allowed:
        return HttpResponseForbidden(access.reason)
    if not platform_connection_enabled(platform):
        return HttpResponseForbidden(f"{platform.title()} connection is not enabled yet.")

    if not request.session.session_key:
        request.session.save()
    session_identity = "" if mobile_identity else request.session.session_key
    mobile_proof = secrets.token_urlsafe(24) if mobile_identity else ""
    state_row, raw_token = create_oauth_state(
        user=user, owner_role=role, platform=platform,
        session_identity=session_identity, mobile_identity=mobile_proof,
        return_target=return_url,
    )
    state = _signed_oauth_state(state_row, raw_token, session_identity, mobile_proof)
    request.session["social_oauth"] = {
        "state": state,
        "user_id": user.pk,
        "role": role,
        "platform": platform,
        "return_url": return_url,
    }
    request.session.save()
    audit_connection("connect_started", user=user, owner_role=role, platform=platform, stage="authorization_start")
    try:
        url = build_authorization_url(request, platform, state)
    except RuntimeError as exc:
        return HttpResponseBadRequest(str(exc))
    return redirect(url)


def oauth_callback(request, platform):
    platform = str(platform or "").strip().lower()
    returned_state = request.GET.get("state", "")
    try:
        state_row = _load_oauth_state(returned_state, platform, request=request)
    except (PermissionError, ValueError, SocialOAuthStateError) as exc:
        return HttpResponseBadRequest(str(exc))
    return_url = _safe_return_url(state_row.safe_return_target)
    role = normalize_owner_role(state_row.owner_role)
    user = User.objects.filter(pk=state_row.user_id, is_active=True).first()
    if not user or not _role_allowed(user, role):
        return HttpResponseForbidden("Arolana account could not be resolved.")
    audit_connection("state_consumed", user=user, owner_role=role, platform=platform, stage="state_validation")

    error = request.GET.get("error")
    if error:
        audit_connection("callback_failed", user=user, owner_role=role, platform=platform,
                         stage="provider_authorization", failure_reason="provider_cancelled")
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
        audit_connection("token_exchange_succeeded", user=user, owner_role=role, platform=platform, stage="token_exchange")
        if platform == SocialPlatform.FACEBOOK:
            long_lived = exchange_facebook_long_lived_token(token_data["access_token"])
            token_data = {**token_data, **long_lived}
            facebook_identity = resolve_facebook_user_identity(token_data["access_token"])
            pages = discover_facebook_pages(token_data["access_token"])
            audit_connection("identity_discovered", user=user, owner_role=role, platform=platform,
                             external_identity_id=facebook_identity["id"], stage="page_discovery")
            safe_pages = []
            for page in pages:
                safe_pages.append({
                    "id": page["id"], "name": page["name"], "tasks": page.get("tasks", []),
                    "authorizing_user_id": facebook_identity["id"],
                    "access_token_encrypted": encrypt_token(page["access_token"]),
                })
            state_row.pending_token_expires_at = token_expiry(token_data)
            state_row.pending_scopes = list(platform_config(platform).scopes)
            state_row.pending_destinations = safe_pages
            state_row.save(update_fields=[
                "pending_token_expires_at",
                "pending_scopes", "pending_destinations",
            ])
            audit_connection(
                "destination_selection_required", user=user, owner_role=role,
                platform=platform, stage="page_selection",
                failure_reason="no_manageable_pages" if not safe_pages else "",
            )
            selection = signing.dumps({"state_id": state_row.pk, "user_id": user.pk}, salt=FACEBOOK_SELECTION_SALT)
            return redirect(f"{reverse('social_publishing_web:facebook_select')}?selection={selection}")
        if platform == SocialPlatform.INSTAGRAM:
            long_lived = exchange_instagram_long_lived_token(token_data["access_token"])
            token_data = {**token_data, **long_lived}
        identity = resolve_identity(platform, token_data)
        audit_connection("identity_discovered", user=user, owner_role=role, platform=platform,
                         external_identity_id=identity.get("external_account_id", ""), stage="identity_discovery")
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
        audit_connection("connected", user=user, owner_role=role, platform=platform,
                         social_account_id=account.pk,
                         external_identity_id=account.external_account_id,
                         stage="credential_persistence")
    except Exception as exc:
        event = "token_exchange_failed" if "token" in str(exc).lower() else "callback_failed"
        audit_connection(
            event, user=user, owner_role=role, platform=platform,
            stage="token_exchange" if event == "token_exchange_failed" else "callback",
            http_status=getattr(exc, "http_status", None),
            provider_error_code=getattr(exc, "provider_code", ""),
            failure_reason=exc.__class__.__name__,
        )
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


@require_http_methods(["GET", "POST"])
def facebook_select_page(request):
    try:
        selection = signing.loads(
            request.GET.get("selection") or request.POST.get("selection") or "",
            salt=FACEBOOK_SELECTION_SALT, max_age=600,
        )
        state = SocialOAuthState.objects.select_related("user").get(
            pk=selection.get("state_id"), user_id=selection.get("user_id"),
            platform=SocialPlatform.FACEBOOK, used_at__isnull=False,
        )
    except (signing.BadSignature, SocialOAuthState.DoesNotExist):
        return HttpResponseBadRequest("Facebook Page selection is invalid or expired.")
    if state.expires_at <= timezone.now():
        return HttpResponseBadRequest("Facebook Page selection has expired.")
    if state.session_binding_hash:
        current_session_hash = hashlib.sha256(str(request.session.session_key or "").encode("utf-8")).hexdigest()
        if not request.user.is_authenticated or request.user.pk != state.user_id or current_session_hash != state.session_binding_hash:
            return HttpResponseForbidden("Facebook Page selection does not belong to this session.")
    pages = state.pending_destinations or []
    if request.method == "GET":
        return render(request, "social_publishing/facebook_page_select.html", {
            "pages": [{"id": p.get("id", ""), "name": p.get("name", "")} for p in pages],
            "selection": request.GET.get("selection", ""), "role": state.owner_role,
        })
    selected_id = str(request.POST.get("page_id") or "")
    selected = next((page for page in pages if str(page.get("id")) == selected_id), None)
    if not selected:
        return HttpResponseBadRequest("Select a Facebook Page returned by Meta.")
    account, _ = SocialAccount.objects.update_or_create(
        user=state.user, owner_role=state.owner_role, platform=SocialPlatform.FACEBOOK,
        defaults={
            "external_account_id": selected_id,
            "account_name": str(selected.get("name") or "Facebook Page")[:255],
            "account_username": "", "status": SocialConnectionStatus.CONNECTED,
            "access_token_encrypted": selected.get("access_token_encrypted", ""),
            "refresh_token_encrypted": "", "token_expires_at": state.pending_token_expires_at,
            "scopes": state.pending_scopes,
            "platform_metadata": {
                "destination_type": "facebook_page", "tasks": selected.get("tasks", []),
                "authorizing_user_id": selected.get("authorizing_user_id", ""),
            },
            "last_error": "",
        },
    )
    audit_connection("destination_selected", user=state.user, owner_role=state.owner_role,
                     platform=SocialPlatform.FACEBOOK, social_account_id=account.pk,
                     selected_destination_id=selected_id, stage="page_selection")
    audit_connection("connected", user=state.user, owner_role=state.owner_role,
                     platform=SocialPlatform.FACEBOOK, social_account_id=account.pk,
                     external_identity_id=selected_id, stage="credential_persistence")
    state.pending_destinations = []
    state.save(update_fields=["pending_destinations"])
    target = _safe_return_url(state.safe_return_target)
    if target:
        return redirect(f"{target}?status=connected&platform=facebook")
    messages.success(request, "Facebook Page connected successfully.")
    return redirect(f"{reverse('social_publishing_web:accounts')}?role={state.owner_role}")


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
        audit_connection("disconnect_started", user=request.user, owner_role=role, platform=platform,
                         social_account_id=account.pk, stage="disconnect")
        if platform == SocialPlatform.FACEBOOK and account.access_token_encrypted:
            try:
                revoke_facebook_access(decrypt_token(account.access_token_encrypted))
                audit_connection("provider_revoke_succeeded", user=request.user, owner_role=role,
                                 platform=platform, social_account_id=account.pk, stage="provider_revoke")
            except Exception as exc:
                audit_connection("provider_revoke_failed", user=request.user, owner_role=role,
                                 platform=platform, social_account_id=account.pk,
                                 stage="provider_revoke", failure_reason=exc.__class__.__name__,
                                 http_status=getattr(exc, "http_status", None),
                                 provider_error_code=getattr(exc, "provider_code", ""))
        account.delete()
        audit_connection("disconnected", user=request.user, owner_role=role, platform=platform,
                         stage="disconnect", external_identity_id="", social_account_id=None)
        messages.success(request, f"{platform.title()} disconnected.")
    return redirect(f"{reverse('social_publishing_web:accounts')}?role={role}")

def _meta_b64url_decode(value):
    value = str(value or "")
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("utf-8"))


class MetaSignedRequestError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _parse_meta_signed_request(value, platform):
    value = str(value or "").strip()
    secret_setting = (
        "SOCIAL_PUBLISHING_META_APP_SECRET"
        if platform == SocialPlatform.FACEBOOK
        else "SOCIAL_PUBLISHING_INSTAGRAM_APP_SECRET"
    )
    secret = str(getattr(settings, secret_setting, "") or "").strip()

    if not value:
        raise MetaSignedRequestError("missing_signed_request")
    if not secret:
        raise MetaSignedRequestError("provider_not_configured")

    try:
        encoded_sig, encoded_payload = value.split(".", 1)
    except ValueError as exc:
        raise MetaSignedRequestError("malformed_signed_request") from exc

    try:
        supplied_sig = _meta_b64url_decode(encoded_sig)
    except (ValueError, TypeError) as exc:
        raise MetaSignedRequestError("malformed_signed_request") from exc
    expected_sig = hmac.new(
        secret.encode("utf-8"),
        encoded_payload.encode("utf-8"),
        hashlib.sha256,
    ).digest()

    if not hmac.compare_digest(supplied_sig, expected_sig):
        raise MetaSignedRequestError("invalid_signature")

    try:
        payload = json.loads(_meta_b64url_decode(encoded_payload).decode("utf-8"))
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MetaSignedRequestError("malformed_payload") from exc
    if not isinstance(payload, dict):
        raise MetaSignedRequestError("malformed_payload")
    return payload


def _signed_request_error(platform, exc):
    audit_connection("callback_failed", platform=platform, stage="signed_request_validation",
                     provider_error_code=exc.code, failure_reason="invalid_signed_request")
    return JsonResponse({"success": False, "error": "Invalid signed request."}, status=400)


def _deauthorize_platform(request, platform):
    try:
        payload = _parse_meta_signed_request(request.POST.get("signed_request"), platform)
    except MetaSignedRequestError as exc:
        return _signed_request_error(platform, exc)
    provider_user_id = str(payload.get("user_id") or payload.get("id") or "").strip()
    if not provider_user_id:
        return _signed_request_error(platform, MetaSignedRequestError("missing_external_identity"))
    if platform == SocialPlatform.FACEBOOK:
        accounts = SocialAccount.objects.filter(
            platform=platform, platform_metadata__authorizing_user_id=provider_user_id,
        )
    else:
        accounts = SocialAccount.objects.filter(platform=platform, external_account_id=provider_user_id)
    matched = 0
    for account in accounts:
        matched += 1
        audit_connection("revoked", user=account.user, owner_role=account.owner_role,
                         platform=platform, social_account_id=account.pk,
                         external_identity_id=provider_user_id, stage="provider_deauthorization")
        if platform == SocialPlatform.INSTAGRAM:
            # Preserve the established Instagram deauthorization contract.
            account.delete()
        else:
            account.status = SocialConnectionStatus.REVOKED
            account.access_token_encrypted = ""
            account.refresh_token_encrypted = ""
            account.last_error = f"{account.get_platform_display()} authorization was revoked. Reconnect is required."
            account.save(update_fields=[
                "status", "access_token_encrypted", "refresh_token_encrypted", "last_error", "updated_at",
            ])
    if not matched:
        audit_connection("revoked", platform=platform, external_identity_id=provider_user_id,
                         stage="provider_deauthorization", failure_reason="unknown_external_account")
    return JsonResponse({"success": True, "deauthorized": True})


def _delete_platform_data(request, platform, status_route):
    try:
        payload = _parse_meta_signed_request(request.POST.get("signed_request"), platform)
    except MetaSignedRequestError as exc:
        return _signed_request_error(platform, exc)
    provider_user_id = str(payload.get("user_id") or payload.get("id") or "").strip()
    if not provider_user_id:
        return _signed_request_error(platform, MetaSignedRequestError("missing_external_identity"))
    if platform == SocialPlatform.FACEBOOK:
        accounts = SocialAccount.objects.filter(
            platform=platform, platform_metadata__authorizing_user_id=provider_user_id,
        )
    else:
        accounts = SocialAccount.objects.filter(platform=platform, external_account_id=provider_user_id)
    matched = 0
    for account in accounts:
        matched += 1
        audit_connection("disconnected", user=account.user, owner_role=account.owner_role,
                         platform=platform, social_account_id=account.pk,
                         external_identity_id=provider_user_id, stage="provider_data_deletion")
        account.delete()
    if not matched:
        audit_connection("disconnected", platform=platform, external_identity_id=provider_user_id,
                         stage="provider_data_deletion", failure_reason="unknown_external_account")
    deletion, _ = SocialDataDeletionRequest.objects.get_or_create(
        platform=platform, external_account_id=provider_user_id,
    )
    status_url = request.build_absolute_uri(reverse(status_route))
    status_url = f"{status_url}?code={deletion.confirmation_code}"
    return JsonResponse({"url": status_url, "confirmation_code": str(deletion.confirmation_code)})


@csrf_exempt
@require_POST
def meta_instagram_deauthorize(request):
    return _deauthorize_platform(request, SocialPlatform.INSTAGRAM)


@csrf_exempt
@require_POST
def meta_facebook_deauthorize(request):
    return _deauthorize_platform(request, SocialPlatform.FACEBOOK)


@csrf_exempt
@require_POST
def meta_instagram_data_deletion(request):
    return _delete_platform_data(
        request, SocialPlatform.INSTAGRAM, "social_publishing_web:meta_data_deletion_status"
    )


@csrf_exempt
@require_POST
def meta_facebook_data_deletion(request):
    return _delete_platform_data(
        request, SocialPlatform.FACEBOOK, "social_publishing_web:meta_facebook_data_deletion_status"
    )


@require_GET
def meta_instagram_data_deletion_status(request):
    return _data_deletion_status(request, SocialPlatform.INSTAGRAM)


@require_GET
def meta_facebook_data_deletion_status(request):
    return _data_deletion_status(request, SocialPlatform.FACEBOOK)


def _data_deletion_status(request, platform):
    code = str(request.GET.get("code") or "").strip()
    if not code:
        return HttpResponseBadRequest("A deletion confirmation code is required.")
    exists = SocialDataDeletionRequest.objects.filter(platform=platform, confirmation_code=code).exists()
    if not exists:
        return HttpResponseBadRequest("The deletion confirmation code is invalid.")
    return HttpResponse(
        f"Arolana {platform.title()} data deletion request processed. Confirmation code: {code}",
        content_type="text/plain; charset=utf-8",
    )
