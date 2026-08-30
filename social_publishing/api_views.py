from django.contrib.contenttypes.models import ContentType
from django.http import Http404
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.authentication import BasicAuthentication, SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from staff_mobile.models import StaffMobileToken

from .authentication import StaffMobileTokenAuthentication
from .connection_security import audit_connection
from .crypto import decrypt_token
from .models import PublicationStatus, SocialAccount, SocialPlatform, SocialPublication
from .oauth import platform_config, revoke_facebook_access
from .publisher import (
    FacebookPublicationError,
    InstagramPublicationError,
    prepare_uploaded_video_for_facebook,
    publish_uploaded_video_to_instagram,
)
from .serializers import FacebookVideoPublicationSerializer, InstagramVideoPublicationSerializer
from .services import (
    facebook_page_publishing_ready,
    normalize_owner_role,
    platform_connection_enabled,
    platform_enabled,
    social_publishing_access,
)
from .web_views import make_launch_token


def _role_available(user, role):
    if role == "admin":
        return bool(getattr(user, "is_staff", False) or getattr(user, "is_superuser", False))
    if role == "vendor":
        return hasattr(user, "vendor_profile")
    if role == "provider":
        return hasattr(user, "service_provider_profile")
    return False


def _publishing_role(request, requested_role):
    mobile_session = request.auth if isinstance(request.auth, StaffMobileToken) else None
    if mobile_session:
        role = normalize_owner_role(mobile_session.role)
        if requested_role and normalize_owner_role(requested_role) != role:
            raise PermissionDenied("The requested role does not match this mobile session.")
    else:
        role = normalize_owner_role(requested_role or "vendor")
    if not _role_available(request.user, role):
        raise PermissionDenied("This role is not available for your account.")
    return role


def _resolve_publication_content(*, user, owner_role, content_reference, object_id):
    app_label, model = content_reference.split(".", 1)
    try:
        content_type = ContentType.objects.get(app_label=app_label, model=model)
    except ContentType.DoesNotExist as exc:
        raise Http404("Content was not found.") from exc
    model_class = content_type.model_class()
    if model_class is None:
        raise Http404("Content was not found.")
    try:
        content_object = model_class._default_manager.get(pk=object_id)
    except model_class.DoesNotExist as exc:
        raise Http404("Content was not found.") from exc

    if owner_role == "admin":
        return content_object
    if content_reference == "products.product" and owner_role == "vendor":
        allowed = content_object.vendor_id == user.pk
    elif content_reference == "products.productvideo" and owner_role == "vendor":
        vendor_profile_id = getattr(getattr(user, "vendor_profile", None), "pk", None)
        allowed = (
            content_object.vendor_id == vendor_profile_id
            or content_object.product.vendor_id == user.pk
        )
    elif content_reference == "installers.serviceportfolio" and owner_role == "provider":
        allowed = content_object.provider.user_id == user.pk
    elif content_reference == "installers.serviceprojectmedia" and owner_role == "provider":
        allowed = content_object.project.provider.user_id == user.pk
    else:
        allowed = False
    if not allowed:
        raise PermissionDenied("This content is not available for the requested role.")
    return content_object


def _publication_payload(publication):
    return {
        "publication_id": publication.pk,
        "status": publication.status,
        "instagram_media_id": publication.external_id or "",
        "instagram_permalink": publication.external_url or "",
        "awaiting_moderation": bool(
            publication.status == "pending"
            and (publication.request_metadata or {}).get("awaiting_moderation")
        ),
    }


def _facebook_publication_payload(publication):
    return {
        "publication_id": publication.pk,
        "status": publication.status,
        "facebook_video_id": publication.external_id or "",
        "facebook_permalink": publication.external_url or "",
        "awaiting_moderation": bool(
            publication.status == "pending"
            and (publication.request_metadata or {}).get("awaiting_moderation")
        ),
    }


_PUBLIC_PUBLISHING_ERRORS = {
    "social_publishing_access_denied": (
        status.HTTP_403_FORBIDDEN,
        "Social publishing is not available for this account.",
    ),
    "instagram_publishing_disabled": (
        status.HTTP_409_CONFLICT,
        "Instagram publishing is not enabled.",
    ),
    "instagram_not_connected": (
        status.HTTP_409_CONFLICT,
        "A connected Instagram account is required.",
    ),
    "instagram_reauthorization_required": (
        status.HTTP_409_CONFLICT,
        "The connected Instagram account requires reauthorization.",
    ),
    "already_published": (
        status.HTTP_409_CONFLICT,
        "This content has already been published to Instagram.",
    ),
    "publish_in_progress": (
        status.HTTP_409_CONFLICT,
        "This content is already being published to Instagram.",
    ),
    "content_awaiting_moderation": (
        status.HTTP_409_CONFLICT,
        "This video must be approved before it can be published to Instagram.",
    ),
    "invalid_content_object": (
        status.HTTP_400_BAD_REQUEST,
        "The selected content is invalid.",
    ),
    "https_video_url_required": (
        status.HTTP_502_BAD_GATEWAY,
        "Instagram video delivery is temporarily unavailable.",
    ),
}


def _public_publishing_error(exc):
    public_code = exc.code if exc.code in _PUBLIC_PUBLISHING_ERRORS else "instagram_publish_failed"
    response_status, detail = _PUBLIC_PUBLISHING_ERRORS.get(
        public_code,
        (status.HTTP_502_BAD_GATEWAY, "Instagram publishing failed."),
    )
    return public_code, detail, response_status


_PUBLIC_FACEBOOK_ERRORS = {
    "social_publishing_access_denied": (status.HTTP_403_FORBIDDEN, "Social publishing is not available for this account."),
    "facebook_publishing_disabled": (status.HTTP_409_CONFLICT, "Facebook publishing is not enabled."),
    "facebook_not_connected": (status.HTTP_409_CONFLICT, "A connected Facebook Page is required."),
    "facebook_reauthorization_required": (status.HTTP_409_CONFLICT, "The connected Facebook Page requires reauthorization."),
    "facebook_publish_permission_required": (status.HTTP_409_CONFLICT, "Reconnect the Facebook Page to grant publishing permission."),
    "already_published": (status.HTTP_409_CONFLICT, "This content has already been published to Facebook."),
    "publish_in_progress": (status.HTTP_409_CONFLICT, "This content is already being published to Facebook."),
    "invalid_content_object": (status.HTTP_400_BAD_REQUEST, "The selected content is invalid."),
}


def _public_facebook_error(exc):
    public_code = exc.code if exc.code in _PUBLIC_FACEBOOK_ERRORS else "facebook_publish_failed"
    response_status, detail = _PUBLIC_FACEBOOK_ERRORS.get(
        public_code, (status.HTTP_502_BAD_GATEWAY, "Facebook publishing could not be prepared.")
    )
    return public_code, detail, response_status


def _platform_payload(platform, label, account=None):
    if platform == SocialPlatform.YOUTUBE:
        return {
            "platform": platform,
            "label": label,
            "available": True,
            "configured": True,
            "connected": True,
            "status": "managed",
            "hosting": "arolana",
            "account_name": "Arolana YouTube hosting",
            "account_username": "",
            "external_account_id": "",
            "profile_picture_url": "",
        }
    try:
        configured = platform_config(platform).configured
    except ValueError:
        configured = False
    facebook_permission_ready = (
        facebook_page_publishing_ready(account)
        if platform == SocialPlatform.FACEBOOK
        else False
    )
    payload = {
        "platform": platform,
        "label": label,
        "available": platform_connection_enabled(platform),
        "publishing_enabled": platform_enabled(platform),
        "publishing_ready": (
            platform_enabled(platform)
            and (
                platform != SocialPlatform.FACEBOOK
                or facebook_permission_ready
            )
        ),
        "configured": configured,
        "connected": bool(account and account.is_connected),
        "status": account.status if account else "not_connected",
        "hosting": "external",
        "account_name": account.account_name if account else "",
        "account_username": account.account_username if account else "",
        "external_account_id": account.external_account_id if account else "",
        "profile_picture_url": (
            str((account.platform_metadata or {}).get("profile_picture_url") or "")
            if account and platform == SocialPlatform.INSTAGRAM
            else ""
        ),
    }
    if platform == SocialPlatform.FACEBOOK:
        # Keep the Page's stored Meta grant distinct from the global publishing
        # feature gate so clients never prompt a connected, authorized Page to
        # reconnect merely because publishing is intentionally disabled.
        payload["account_publishing_ready"] = facebook_permission_ready
    return payload


@api_view(["GET"])
@authentication_classes(
    [SessionAuthentication, BasicAuthentication, StaffMobileTokenAuthentication]
)
@permission_classes([IsAuthenticated])
def social_accounts_status(request):
    try:
        role = _publishing_role(request, request.query_params.get("role"))
    except ValueError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    access = social_publishing_access(request.user, role)
    accounts = {
        item.platform: item
        for item in SocialAccount.objects.filter(user=request.user, owner_role=role)
    }
    platforms = [
        _platform_payload(platform, label, accounts.get(platform))
        for platform, label in SocialPlatform.choices
    ]

    return Response({
        "role": role,
        "subscription": {
            "allowed": access.allowed,
            "tier": access.tier,
            "reason": access.reason,
        },
        "platforms": platforms,
    })


@api_view(["POST"])
@authentication_classes(
    [SessionAuthentication, BasicAuthentication, StaffMobileTokenAuthentication]
)
@permission_classes([IsAuthenticated])
def social_account_connect_launch(request, platform):
    platform = str(platform or "").strip().lower()
    if platform == SocialPlatform.YOUTUBE or platform not in dict(SocialPlatform.choices):
        return Response({"detail": "This platform is not connectable here."}, status=status.HTTP_400_BAD_REQUEST)
    try:
        role = _publishing_role(request, request.data.get("role"))
    except ValueError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    access = social_publishing_access(request.user, role)
    if not access.allowed:
        return Response({"detail": access.reason, "upgrade_required": True}, status=status.HTTP_403_FORBIDDEN)
    if not platform_connection_enabled(platform):
        return Response({"detail": f"{platform.title()} connection is not enabled yet."}, status=status.HTTP_409_CONFLICT)
    try:
        configured = platform_config(platform).configured
    except ValueError:
        configured = False
    if not configured:
        return Response({"detail": f"{platform.title()} OAuth is not configured."}, status=status.HTTP_409_CONFLICT)

    return_url = str(request.data.get("return_url", "") or "").strip()
    launch = make_launch_token(
        request.user, role, platform, return_url=return_url, request=request
    )
    connect_path = reverse("social_publishing_web:connect", kwargs={"platform": platform})
    connect_url = request.build_absolute_uri(f"{connect_path}?launch={launch}")
    return Response({"platform": platform, "role": role, "authorization_url": connect_url})


@api_view(["DELETE"])
@authentication_classes(
    [SessionAuthentication, BasicAuthentication, StaffMobileTokenAuthentication]
)
@permission_classes([IsAuthenticated])
def social_account_disconnect(request, platform):
    platform = str(platform or "").strip().lower()
    try:
        role = _publishing_role(
            request,
            request.data.get("role") or request.query_params.get("role"),
        )
    except ValueError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    if platform == SocialPlatform.YOUTUBE:
        return Response({"detail": "Arolana YouTube hosting cannot be disconnected here."}, status=status.HTTP_400_BAD_REQUEST)
    account = SocialAccount.objects.filter(user=request.user, owner_role=role, platform=platform).first()
    deleted = 0
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
                                 platform=platform, social_account_id=account.pk, stage="provider_revoke",
                                 failure_reason=exc.__class__.__name__, http_status=getattr(exc, "http_status", None),
                                 provider_error_code=getattr(exc, "provider_code", ""))
        deleted, _ = account.delete()
        audit_connection("disconnected", user=request.user, owner_role=role, platform=platform, stage="disconnect")
    return Response({"success": True, "disconnected": bool(deleted), "platform": platform})


@api_view(["POST"])
@authentication_classes(
    [SessionAuthentication, BasicAuthentication, StaffMobileTokenAuthentication]
)
@permission_classes([IsAuthenticated])
def publish_instagram_video(request):
    serializer = InstagramVideoPublicationSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    try:
        owner_role = _publishing_role(request, data.get("role"))
        content_object = _resolve_publication_content(
            user=request.user,
            owner_role=owner_role,
            content_reference=data["content_type"],
            object_id=data["object_id"],
        )
        uploaded_video = data.get("video")
        if uploaded_video is None:
            content_type = ContentType.objects.get_for_model(
                content_object, for_concrete_model=False
            )
            reusable = SocialPublication.objects.filter(
                owner_user=request.user,
                owner_role=owner_role,
                platform=SocialPlatform.INSTAGRAM,
                content_type=content_type,
                object_id=content_object.pk,
                status=PublicationStatus.FAILED,
                deferred_video_lease__isnull=False,
                deferred_video_lease__cleanup_completed_at__isnull=True,
                deferred_video_lease__expires_at__gt=timezone.now(),
            ).exists()
            if not reusable:
                return Response(
                    {"video": ["A video upload is required."]},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        publication = publish_uploaded_video_to_instagram(
            user=request.user,
            owner_role=owner_role,
            content_object=content_object,
            uploaded_file=uploaded_video,
            caption=data["caption"],
            share_to_feed=data["share_to_feed"],
        )
    except InstagramPublicationError as exc:
        public_code, detail, response_status = _public_publishing_error(exc)
        payload = {
            "detail": detail,
            "error_code": public_code,
        }
        if exc.publication is not None:
            payload.update(_publication_payload(exc.publication))
        return Response(payload, status=response_status)

    response_status = (
        status.HTTP_202_ACCEPTED if publication.status == "pending" else status.HTTP_201_CREATED
    )
    return Response(_publication_payload(publication), status=response_status)


@api_view(["POST"])
@authentication_classes(
    [SessionAuthentication, BasicAuthentication, StaffMobileTokenAuthentication]
)
@permission_classes([IsAuthenticated])
def prepare_facebook_video_publication(request):
    """Persist a moderation-gated Facebook Page publication intent."""
    serializer = FacebookVideoPublicationSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    try:
        owner_role = _publishing_role(request, data.get("role"))
        content_object = _resolve_publication_content(
            user=request.user,
            owner_role=owner_role,
            content_reference=data["content_type"],
            object_id=data["object_id"],
        )
        publication = prepare_uploaded_video_for_facebook(
            user=request.user,
            owner_role=owner_role,
            content_object=content_object,
            uploaded_file=data["video"],
            caption=data["caption"],
        )
    except FacebookPublicationError as exc:
        public_code, detail, response_status = _public_facebook_error(exc)
        payload = {"detail": detail, "error_code": public_code}
        if exc.publication is not None:
            payload.update(_facebook_publication_payload(exc.publication))
        return Response(payload, status=response_status)
    return Response(_facebook_publication_payload(publication), status=status.HTTP_202_ACCEPTED)
