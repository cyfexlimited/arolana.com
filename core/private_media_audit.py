from __future__ import annotations

import hashlib
import ipaddress
import logging

from core.private_media import (
    PRIVATE_MEDIA_RULES,
    PrivateMediaDecision,
    normalize_private_media_path,
)


logger = logging.getLogger(
    "arolana.private_media.audit"
)


RULE_SCOPE_MAP = {
    rule.key: rule.scope
    for rule in PRIVATE_MEDIA_RULES
}


def _clean_text(
    value,
    max_length: int,
) -> str:
    return str(
        value or ""
    ).strip()[:max_length]


def _valid_ip(
    value,
) -> str | None:
    value = str(
        value or ""
    ).strip()

    if not value:
        return None

    try:
        return str(
            ipaddress.ip_address(value)
        )
    except ValueError:
        return None


def get_request_ip(
    request,
) -> str | None:
    """
    Resolve the best available client IP for security auditing.

    Order:
    1. Cloudflare connecting IP
    2. First X-Forwarded-For address
    3. Direct REMOTE_ADDR
    """
    meta = getattr(
        request,
        "META",
        {},
    )

    cloudflare_ip = _valid_ip(
        meta.get(
            "HTTP_CF_CONNECTING_IP",
            ""
        )
    )

    if cloudflare_ip:
        return cloudflare_ip

    forwarded_for = str(
        meta.get(
            "HTTP_X_FORWARDED_FOR",
            "",
        )
        or ""
    )

    if forwarded_for:
        first_forwarded_ip = (
            forwarded_for
            .split(",")[0]
            .strip()
        )

        valid_forwarded_ip = _valid_ip(
            first_forwarded_ip
        )

        if valid_forwarded_ip:
            return valid_forwarded_ip

    return _valid_ip(
        meta.get(
            "REMOTE_ADDR",
            ""
        )
    )


def get_request_id(
    request,
) -> str:
    """
    Capture an infrastructure request identifier when available.
    """
    meta = getattr(
        request,
        "META",
        {},
    )

    candidates = (
        meta.get(
            "HTTP_CF_RAY",
            "",
        ),
        meta.get(
            "HTTP_X_RAILWAY_REQUEST_ID",
            "",
        ),
        meta.get(
            "HTTP_X_REQUEST_ID",
            "",
        ),
    )

    for value in candidates:
        clean_value = _clean_text(
            value,
            160,
        )

        if clean_value:
            return clean_value

    return ""


def hash_private_media_path(
    path: str,
) -> str:
    """
    Hash the normalized storage path.

    We intentionally avoid saving the raw path because private filenames
    may reveal personal information or sensitive document details.
    """
    normalized_path = normalize_private_media_path(
        path
    )

    if not normalized_path:
        return ""

    return hashlib.sha256(
        normalized_path.encode(
            "utf-8"
        )
    ).hexdigest()


def record_private_media_access(
    request,
    path: str,
    decision: PrivateMediaDecision,
) -> bool:
    """
    Save an immutable private-media access record.

    Logging failure must not accidentally alter the existing authorization
    decision. Database/logging problems are sent to the application logger.

    Returns:
        True when the audit row was saved.
        False when persistence failed.
    """
    try:
        # Local import avoids unnecessary model import work during
        # Django application initialization.
        from core.models import PrivateMediaAccessLog

        decision_value = (
            PrivateMediaAccessLog.DECISION_ALLOWED
            if decision.allowed
            else PrivateMediaAccessLog.DECISION_DENIED
        )

        user_agent = _clean_text(
            getattr(
                request,
                "META",
                {},
            ).get(
                "HTTP_USER_AGENT",
                "",
            ),
            700,
        )

        request_method = _clean_text(
            getattr(
                request,
                "method",
                "",
            ),
            10,
        ).upper()

        object_id = (
            ""
            if decision.object_id is None
            else _clean_text(
                decision.object_id,
                100,
            )
        )

        PrivateMediaAccessLog.objects.create(
            user_id=(
                decision.principal_user_id
                or None
            ),
            rule_key=_clean_text(
                decision.rule_key,
                120,
            ),
            scope=_clean_text(
                RULE_SCOPE_MAP.get(
                    decision.rule_key,
                    "",
                ),
                50,
            ),
            model_label=_clean_text(
                decision.model_label,
                150,
            ),
            object_id=object_id,
            decision=decision_value,
            reason=_clean_text(
                decision.reason,
                100,
            ),
            path_hash=hash_private_media_path(
                path
            ),
            ip_address=get_request_ip(
                request
            ),
            user_agent=user_agent,
            request_method=request_method,
            request_id=get_request_id(
                request
            ),
        )

        return True

    except Exception:
        logger.exception(
            (
                "Failed to persist private media access audit record. "
                "rule=%s object_id=%s user_id=%s allowed=%s"
            ),
            decision.rule_key,
            decision.object_id,
            decision.principal_user_id,
            decision.allowed,
        )

        return False