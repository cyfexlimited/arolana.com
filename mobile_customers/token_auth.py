from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import MobileCustomer, MobileCustomerAccessToken


TOKEN_PREFIX = "ar_mob_"


@dataclass(frozen=True)
class MobileTokenAuthentication:
    customer: MobileCustomer
    token: MobileCustomerAccessToken
    migrated_legacy: bool = False


def _token_pepper() -> bytes:
    """
    Use a dedicated production secret when configured.

    Changing this value invalidates every token hash, so keep the production
    value stable and rotate through an explicit migration plan.
    """
    value = str(
        getattr(settings, "MOBILE_CUSTOMER_TOKEN_PEPPER", "")
        or settings.SECRET_KEY
    )
    return value.encode("utf-8")


def mobile_token_digest(raw_token: str) -> str:
    raw_token = str(raw_token or "").strip()
    if not raw_token:
        return ""

    return hmac.new(
        _token_pepper(),
        raw_token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def mobile_token_fingerprint(raw_token: str) -> str:
    return mobile_token_digest(raw_token)[:16]


def _token_ttl():
    days = int(
        getattr(
            settings,
            "MOBILE_CUSTOMER_TOKEN_TTL_DAYS",
            30,
        )
    )
    return timedelta(days=max(1, days))


def _legacy_token_ttl():
    days = int(
        getattr(
            settings,
            "MOBILE_CUSTOMER_LEGACY_TOKEN_TTL_DAYS",
            30,
        )
    )
    return timedelta(days=max(1, days))


def _max_active_sessions() -> int:
    return max(
        1,
        int(
            getattr(
                settings,
                "MOBILE_CUSTOMER_MAX_ACTIVE_TOKENS",
                8,
            )
        ),
    )


def _request_ip(request) -> Optional[str]:
    if request is None:
        return None

    # Do not trust arbitrary X-Forwarded-For values here. REMOTE_ADDR is used
    # only for audit metadata, never as an authentication factor.
    return str(request.META.get("REMOTE_ADDR") or "").strip() or None


def _request_user_agent(request) -> str:
    if request is None:
        return ""
    return str(request.META.get("HTTP_USER_AGENT") or "")[:2000]


@transaction.atomic
def issue_mobile_customer_token(
    customer: MobileCustomer,
    *,
    request=None,
    device_name: str = "",
):
    """
    Issue one raw bearer token and persist only its keyed digest.

    Returns:
        (raw_token, MobileCustomerAccessToken)
    """
    locked_customer = (
        MobileCustomer.objects
        .select_for_update()
        .get(pk=customer.pk)
    )

    now = timezone.now()
    raw_token = f"{TOKEN_PREFIX}{secrets.token_urlsafe(32)}"
    digest = mobile_token_digest(raw_token)

    token = MobileCustomerAccessToken.objects.create(
        customer=locked_customer,
        token_hash=digest,
        fingerprint=digest[:16],
        device_name=str(device_name or "")[:160],
        expires_at=now + _token_ttl(),
        last_used_at=now,
        last_seen_ip=_request_ip(request),
        user_agent=_request_user_agent(request),
    )

    active_ids = list(
        MobileCustomerAccessToken.objects
        .filter(
            customer=locked_customer,
            revoked_at__isnull=True,
            expires_at__gt=now,
        )
        .order_by("-created_at")
        .values_list("id", flat=True)
    )

    keep = _max_active_sessions()
    stale_ids = active_ids[keep:]

    if stale_ids:
        MobileCustomerAccessToken.objects.filter(
            id__in=stale_ids,
            revoked_at__isnull=True,
        ).update(
            revoked_at=now,
            updated_at=now,
        )

    return raw_token, token


def _touch_token_usage(token: MobileCustomerAccessToken, request=None):
    now = timezone.now()
    interval_minutes = max(
        1,
        int(
            getattr(
                settings,
                "MOBILE_CUSTOMER_TOKEN_TOUCH_MINUTES",
                15,
            )
        ),
    )

    if (
        token.last_used_at is not None
        and token.last_used_at > now - timedelta(minutes=interval_minutes)
    ):
        return

    MobileCustomerAccessToken.objects.filter(
        pk=token.pk,
        revoked_at__isnull=True,
    ).update(
        last_used_at=now,
        last_seen_ip=_request_ip(request),
        user_agent=_request_user_agent(request),
        updated_at=now,
    )


@transaction.atomic
def _migrate_one_legacy_token(
    customer: MobileCustomer,
    raw_token: str,
    *,
    request=None,
) -> MobileTokenAuthentication:
    """
    Lazily convert one existing plaintext customer token into a hashed,
    expiring token row while preserving the raw token already stored by the app.
    """
    locked_customer = (
        MobileCustomer.objects
        .select_for_update()
        .select_related("user")
        .get(pk=customer.pk)
    )

    current_legacy = str(locked_customer.api_token or "")

    if (
        not current_legacy
        or not secrets.compare_digest(current_legacy, raw_token)
    ):
        raise PermissionError(
            "Login expired or invalid. Login/register again."
        )

    digest = mobile_token_digest(raw_token)
    now = timezone.now()

    existing = (
        MobileCustomerAccessToken.objects
        .select_related("customer", "customer__user")
        .filter(token_hash=digest)
        .first()
    )

    if existing is not None and existing.customer_id != locked_customer.pk:
        raise PermissionError(
            "Token collision detected. Login/register again."
        )

    if existing is None:
        try:
            existing = MobileCustomerAccessToken.objects.create(
                customer=locked_customer,
                token_hash=digest,
                fingerprint=digest[:16],
                device_name="Legacy mobile session",
                expires_at=now + _legacy_token_ttl(),
                last_used_at=now,
                last_seen_ip=_request_ip(request),
                user_agent=_request_user_agent(request),
            )
        except IntegrityError:
            existing = (
                MobileCustomerAccessToken.objects
                .select_related("customer", "customer__user")
                .get(token_hash=digest)
            )

            if existing.customer_id != locked_customer.pk:
                raise PermissionError(
                    "Token collision detected. Login/register again."
                )

    locked_customer.api_token = ""
    update_fields = ["api_token"]

    if hasattr(locked_customer, "updated_at"):
        update_fields.append("updated_at")

    locked_customer.save(update_fields=update_fields)

    return MobileTokenAuthentication(
        customer=locked_customer,
        token=existing,
        migrated_legacy=True,
    )


def authenticate_mobile_customer_token(
    raw_token: str,
    *,
    phone_number: str = "",
    request=None,
    allow_legacy: bool = True,
) -> MobileTokenAuthentication:
    raw_token = str(raw_token or "").strip()

    if not raw_token:
        raise PermissionError(
            "Login token is required. Login/register again."
        )

    digest = mobile_token_digest(raw_token)
    now = timezone.now()

    queryset = (
        MobileCustomerAccessToken.objects
        .select_related("customer", "customer__user")
        .filter(
            token_hash=digest,
            revoked_at__isnull=True,
            expires_at__gt=now,
            customer__is_active=True,
        )
    )

    if phone_number:
        queryset = queryset.filter(
            customer__phone_number=phone_number,
        )

    token = queryset.first()

    if token is not None:
        _touch_token_usage(token, request=request)
        return MobileTokenAuthentication(
            customer=token.customer,
            token=token,
            migrated_legacy=False,
        )

    if allow_legacy:
        legacy_queryset = MobileCustomer.objects.filter(
            api_token=raw_token,
            is_active=True,
        ).select_related("user")

        if phone_number:
            legacy_queryset = legacy_queryset.filter(
                phone_number=phone_number,
            )

        legacy_customer = legacy_queryset.first()

        if legacy_customer is not None:
            return _migrate_one_legacy_token(
                legacy_customer,
                raw_token,
                request=request,
            )

    raise PermissionError(
        "Login expired or invalid. Login/register again."
    )


def revoke_mobile_customer_token(token, *, when=None) -> bool:
    if token is None:
        return False

    when = when or timezone.now()

    updated = MobileCustomerAccessToken.objects.filter(
        pk=token.pk,
        revoked_at__isnull=True,
    ).update(
        revoked_at=when,
        updated_at=when,
    )

    return bool(updated)


def revoke_all_mobile_customer_tokens(
    customer: MobileCustomer,
    *,
    when=None,
) -> int:
    when = when or timezone.now()

    return MobileCustomerAccessToken.objects.filter(
        customer=customer,
        revoked_at__isnull=True,
    ).update(
        revoked_at=when,
        updated_at=when,
    )


def extract_bearer_token(request) -> str:
    if request is None:
        return ""

    authorization = str(
        request.headers.get("Authorization")
        or ""
    ).strip()

    if authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()

    return ""
