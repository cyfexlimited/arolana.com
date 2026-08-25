"""Server-side token encryption for social publishing OAuth credentials."""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _fallback_key():
    digest = hashlib.sha256(str(settings.SECRET_KEY).encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _fernet():
    configured = str(getattr(settings, "SOCIAL_PUBLISHING_TOKEN_KEY", "") or "").strip()
    if configured:
        key = configured.encode("utf-8")
    else:
        # Stable fallback for local development. Production should set a dedicated
        # SOCIAL_PUBLISHING_TOKEN_KEY so token encryption can be rotated separately.
        key = _fallback_key()
    return Fernet(key)


def encrypt_token(value):
    value = str(value or "")
    if not value:
        return ""
    return _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_token(value):
    value = str(value or "")
    if not value:
        return ""
    candidates = [_fernet()]
    # Dual-read permits adding a dedicated key without rewriting existing
    # SECRET_KEY-derived Instagram ciphertext during deployment.
    if str(getattr(settings, "SOCIAL_PUBLISHING_TOKEN_KEY", "") or "").strip():
        candidates.append(Fernet(_fallback_key()))
    for cipher in candidates:
        try:
            return cipher.decrypt(value.encode("utf-8")).decode("utf-8")
        except InvalidToken:
            continue
    raise RuntimeError("Stored social credential could not be decrypted.")
