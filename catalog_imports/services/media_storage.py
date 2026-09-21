import hashlib
import io
import os
from dataclasses import dataclass

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import storages


class ReviewStorageError(RuntimeError):
    pass


@dataclass
class StoredReviewAsset:
    storage_alias: str
    storage_name: str
    original_name: str
    mime_type: str
    width: int
    height: int
    file_size: int
    sha256: str


def _env_or_setting(name, default=""):
    value = getattr(settings, name, None)
    if value not in (None, ""):
        return value
    value = os.environ.get(name)
    if value not in (None, ""):
        return value
    try:
        from decouple import config
        return config(name, default=default)
    except Exception:
        return default


def review_storage_alias():
    configured = str(_env_or_setting("CATALOG_IMPORT_REVIEW_STORAGE_ALIAS", "") or "").strip()
    if configured:
        return configured
    if getattr(settings, "DEBUG", False):
        return "default"
    raise ReviewStorageError(
        "CATALOG_IMPORT_REVIEW_STORAGE_ALIAS must be configured outside DEBUG so generated review assets are not silently stored in an unintended public backend."
    )


def _storage(alias):
    try:
        return storages[alias]
    except Exception as exc:
        raise ReviewStorageError(f"Unknown review storage alias: {alias}") from exc


def normalize_to_marketplace_webp(raw, *, target_size=800):
    try:
        from PIL import Image, ImageOps
        image = Image.open(io.BytesIO(raw))
        image = ImageOps.exif_transpose(image)
        if getattr(image, "is_animated", False):
            image.seek(0)
        image = image.convert("RGB")
        image = ImageOps.contain(image, (target_size, target_size), method=Image.Resampling.LANCZOS)
        if image.size != (target_size, target_size):
            canvas = Image.new("RGB", (target_size, target_size), "white")
            x = (target_size - image.width) // 2
            y = (target_size - image.height) // 2
            canvas.paste(image, (x, y))
            image = canvas
        buf = io.BytesIO()
        image.save(buf, format="WEBP", quality=90, method=6)
        payload = buf.getvalue()
        return payload, image.width, image.height
    except Exception as exc:
        raise ReviewStorageError("Generated image could not be normalized into a safe marketplace image.") from exc


def save_review_asset(candidate, raw):
    target_size = int(_env_or_setting("CATALOG_IMPORT_MEDIA_TARGET_SIZE", 800) or 800)
    target_size = max(256, min(target_size, 2048))
    normalized, width, height = normalize_to_marketplace_webp(raw, target_size=target_size)
    digest = hashlib.sha256(normalized).hexdigest()
    alias = review_storage_alias()
    storage = _storage(alias)
    name = f"catalog-imports/review/item-{candidate.item_id}/candidate-{candidate.pk}/{digest}.webp"
    try:
        saved_name = storage.save(name, ContentFile(normalized))
    except Exception as exc:
        raise ReviewStorageError("Could not save generated review image to configured storage.") from exc
    return StoredReviewAsset(
        storage_alias=alias,
        storage_name=saved_name,
        original_name=f"{candidate.view_role or 'image'}.webp",
        mime_type="image/webp",
        width=width,
        height=height,
        file_size=len(normalized),
        sha256=digest,
    )


def review_asset_exists(candidate):
    alias = str(getattr(candidate, "asset_storage_alias", "") or "").strip()
    name = str(getattr(candidate, "asset_storage_name", "") or "").strip()
    if not alias or not name:
        return False
    try:
        return bool(_storage(alias).exists(name))
    except Exception:
        return False


def delete_review_asset(candidate):
    alias = str(getattr(candidate, "asset_storage_alias", "") or "").strip()
    name = str(getattr(candidate, "asset_storage_name", "") or "").strip()
    if not alias or not name:
        return
    try:
        _storage(alias).delete(name)
    except Exception:
        # Review rejection/retry should not become impossible because cleanup
        # failed. Orphan cleanup can be handled independently.
        pass
