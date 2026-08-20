from django.urls import reverse
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import SocialAccount, SocialPlatform
from .oauth import platform_config
from .services import normalize_owner_role, platform_enabled, social_publishing_access
from .web_views import make_launch_token


def _role_available(user, role):
    if role == "admin":
        return bool(getattr(user, "is_staff", False) or getattr(user, "is_superuser", False))
    if role == "vendor":
        return hasattr(user, "vendor_profile")
    if role == "provider":
        return hasattr(user, "service_provider_profile")
    return False


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
        }
    try:
        configured = platform_config(platform).configured
    except ValueError:
        configured = False
    return {
        "platform": platform,
        "label": label,
        "available": platform_enabled(platform),
        "configured": configured,
        "connected": bool(account and account.is_connected),
        "status": account.status if account else "not_connected",
        "hosting": "external",
        "account_name": account.account_name if account else "",
        "account_username": account.account_username if account else "",
    }


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def social_accounts_status(request):
    role = request.query_params.get("role", "vendor")
    try:
        role = normalize_owner_role(role)
    except ValueError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    if not _role_available(request.user, role):
        return Response({"detail": "This role is not available for your account."}, status=status.HTTP_403_FORBIDDEN)

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
@permission_classes([IsAuthenticated])
def social_account_connect_launch(request, platform):
    platform = str(platform or "").strip().lower()
    if platform == SocialPlatform.YOUTUBE or platform not in dict(SocialPlatform.choices):
        return Response({"detail": "This platform is not connectable here."}, status=status.HTTP_400_BAD_REQUEST)
    try:
        role = normalize_owner_role(request.data.get("role", "vendor"))
    except ValueError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    if not _role_available(request.user, role):
        return Response({"detail": "This role is not available for your account."}, status=status.HTTP_403_FORBIDDEN)

    access = social_publishing_access(request.user, role)
    if not access.allowed:
        return Response({"detail": access.reason, "upgrade_required": True}, status=status.HTTP_403_FORBIDDEN)
    if not platform_enabled(platform):
        return Response({"detail": f"{platform.title()} connection is not enabled yet."}, status=status.HTTP_409_CONFLICT)
    try:
        configured = platform_config(platform).configured
    except ValueError:
        configured = False
    if not configured:
        return Response({"detail": f"{platform.title()} OAuth is not configured."}, status=status.HTTP_409_CONFLICT)

    return_url = str(request.data.get("return_url", "") or "").strip()
    launch = make_launch_token(request.user, role, platform, return_url=return_url)
    connect_path = reverse("social_publishing_web:connect", kwargs={"platform": platform})
    connect_url = request.build_absolute_uri(f"{connect_path}?launch={launch}")
    return Response({"platform": platform, "role": role, "authorization_url": connect_url})


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def social_account_disconnect(request, platform):
    platform = str(platform or "").strip().lower()
    try:
        role = normalize_owner_role(request.data.get("role") or request.query_params.get("role") or "vendor")
    except ValueError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    if not _role_available(request.user, role):
        return Response({"detail": "This role is not available for your account."}, status=status.HTTP_403_FORBIDDEN)
    if platform == SocialPlatform.YOUTUBE:
        return Response({"detail": "Arolana YouTube hosting cannot be disconnected here."}, status=status.HTTP_400_BAD_REQUEST)
    deleted, _ = SocialAccount.objects.filter(user=request.user, owner_role=role, platform=platform).delete()
    return Response({"success": True, "disconnected": bool(deleted), "platform": platform})
