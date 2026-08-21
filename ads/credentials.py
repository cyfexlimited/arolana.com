import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


class CredentialEncryptionError(Exception):
    pass


class AdvertisingCredentialEncryptionService:
    """Authenticated encryption boundary for advertiser OAuth tokens."""

    def _key(self):
        raw_key = getattr(settings, "ADS_CREDENTIAL_ENCRYPTION_KEY", "")
        if raw_key:
            key = raw_key.encode("utf-8")
            # Prefer a real Fernet key, but support env-provided high-entropy
            # secrets by deriving a Fernet-compatible key with SHA-256.
            try:
                Fernet(key)
                return key
            except (ValueError, TypeError):
                return base64.urlsafe_b64encode(hashlib.sha256(key).digest())
        if not getattr(settings, "DEBUG", False):
            raise ImproperlyConfigured("ADS_CREDENTIAL_ENCRYPTION_KEY is required outside DEBUG.")
        fallback = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
        return base64.urlsafe_b64encode(fallback)

    def encrypt(self, plaintext):
        if plaintext in ("", None):
            return None
        return Fernet(self._key()).encrypt(str(plaintext).encode("utf-8"))

    def decrypt(self, ciphertext):
        if not ciphertext:
            return ""
        try:
            return Fernet(self._key()).decrypt(bytes(ciphertext)).decode("utf-8")
        except InvalidToken as exc:
            raise CredentialEncryptionError("credential_decryption_failed") from exc


credential_encryption_service = AdvertisingCredentialEncryptionService()
