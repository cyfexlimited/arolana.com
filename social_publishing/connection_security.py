"""Durable state and sanitized audit helpers for social account OAuth."""

import hashlib
import secrets
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import SocialConnectionAuditLog, SocialOAuthState


STATE_TTL = timedelta(minutes=10)
ALLOWED_AUDIT_FIELDS = {
    "social_account_id", "external_identity_id", "selected_destination_id",
    "http_status", "provider_error_code", "failure_reason", "stage",
}


class SocialOAuthStateError(PermissionError):
    pass


def _digest(value):
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def create_oauth_state(*, user, owner_role, platform, session_identity="", mobile_identity="", return_target=""):
    raw_token = secrets.token_urlsafe(32)
    state = SocialOAuthState.objects.create(
        user=user,
        owner_role=owner_role,
        platform=platform,
        token_hash=_digest(raw_token),
        session_binding_hash=_digest(session_identity) if session_identity else "",
        mobile_launch_hash=_digest(mobile_identity) if mobile_identity else "",
        safe_return_target=return_target,
        expires_at=timezone.now() + STATE_TTL,
    )
    return state, raw_token


def consume_oauth_state(*, raw_token, user_id, owner_role, platform, session_identity="", mobile_identity=""):
    """Consume in its own transaction so later callback rollback cannot revive it."""
    now = timezone.now()
    with transaction.atomic():
        try:
            state = SocialOAuthState.objects.select_for_update().get(token_hash=_digest(raw_token))
        except SocialOAuthState.DoesNotExist as exc:
            raise SocialOAuthStateError("Invalid social authorization state.") from exc
        if state.used_at:
            raise SocialOAuthStateError("This social authorization state has already been used.")
        if state.expires_at <= now:
            raise SocialOAuthStateError("This social authorization request has expired.")
        if state.user_id != user_id:
            raise SocialOAuthStateError("Social authorization user mismatch.")
        if state.owner_role != owner_role:
            raise SocialOAuthStateError("Social authorization role mismatch.")
        if state.platform != platform:
            raise SocialOAuthStateError("Social authorization platform mismatch.")
        if state.session_binding_hash and state.session_binding_hash != _digest(session_identity):
            raise SocialOAuthStateError("Social authorization session mismatch.")
        if state.mobile_launch_hash and state.mobile_launch_hash != _digest(mobile_identity):
            raise SocialOAuthStateError("Social authorization mobile launch mismatch.")
        updated = SocialOAuthState.objects.filter(pk=state.pk, used_at__isnull=True).update(used_at=now)
        if updated != 1:
            raise SocialOAuthStateError("This social authorization state has already been used.")
        state.used_at = now
        return state


def audit_connection(event, *, user=None, owner_role="", platform="", **metadata):
    safe = {key: metadata.get(key) for key in ALLOWED_AUDIT_FIELDS if metadata.get(key) not in (None, "")}
    account_id = safe.pop("social_account_id", None)
    # Bound all provider-controlled strings and never accept arbitrary metadata.
    for key in ("external_identity_id", "selected_destination_id", "provider_error_code", "failure_reason", "stage"):
        if key in safe:
            safe[key] = str(safe[key])[:255 if key != "stage" else 80]
    return SocialConnectionAuditLog.objects.create(
        user=user, owner_role=owner_role, platform=platform, event=str(event)[:64],
        social_account_id=account_id, **safe,
    )
