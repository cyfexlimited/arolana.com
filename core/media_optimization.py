import logging
import posixpath
import time
from io import BytesIO
from pathlib import PurePosixPath
from urllib.parse import urlparse

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import models

try:
    from PIL import Image, ImageOps
except Exception:
    Image = None
    ImageOps = None

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = (
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".bmp",
    ".tif",
    ".tiff",
)

SKIP_EXTENSIONS = (
    ".svg",
    ".gif",
    ".ico",
    ".pdf",
    ".mp4",
    ".mov",
    ".avi",
    ".mkv",
    ".webm",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".zip",
    ".rar",
)

SKIP_KEYWORDS = (
    "attachment",
    "bank",
    "brochure",
    "certificate",
    "contract",
    "cv",
    "document",
    "driver_license",
    "identity",
    "invoice",
    "kyc",
    "licence",
    "license",
    "manual",
    "passport",
    "payment_proof",
    "pdf",
    "proof",
    "receipt",
    "resume",
    "signature",
    "verification",
    "video",
    "withdrawal",
)

PRESETS = {
    "seo": {"max_size": (1600, 1600), "quality": 82},
    "thumbnail": {"max_size": (600, 600), "quality": 78},

    "nav_icon": {"max_size": (96, 96), "quality": 80},
    "logo": {"max_size": (700, 700), "quality": 82},
    "avatar": {"max_size": (500, 500), "quality": 80},

    "accessory_thumb": {"max_size": (600, 600), "quality": 78},
    "category_card": {"max_size": (1000, 700), "quality": 82},

    "product_thumb": {"max_size": (700, 700), "quality": 80},
    "product_card": {"max_size": (900, 900), "quality": 80},
    "product_detail": {"max_size": (1600, 1600), "quality": 84},

    "ad_card": {"max_size": (900, 500), "quality": 82},
    "banner": {"max_size": (1920, 1080), "quality": 84},
    "hero": {"max_size": (1920, 1080), "quality": 84},
    "landing_hero": {"max_size": (1920, 1080), "quality": 84},
    "mobile_hero": {"max_size": (1080, 1920), "quality": 84},

    "background_desktop": {"max_size": (1920, 1080), "quality": 84},
    "background_mobile": {"max_size": (1080, 1920), "quality": 84},

    "blog_card": {"max_size": (900, 600), "quality": 82},
}

_LOCAL_URL_CACHE = {}
_MISSING_OPTIMIZED = object()


def _plain_string(value):
    return "".join([str(value or "")])


def normalize_storage_name(name):
    name = _plain_string(name).strip().replace("\\", "/")
    name = name.split("?", 1)[0].split("#", 1)[0]
    name = posixpath.normpath(name).lstrip("/")
    if name in ("", "."):
        return ""
    return name


def _name_from_url(url):
    url = _plain_string(url).strip()
    if not url:
        return ""

    parsed = urlparse(url)
    path = parsed.path or url
    media_url = _plain_string(getattr(settings, "MEDIA_URL", "") or "")
    media_path = urlparse(media_url).path if media_url else ""

    if media_path and path.startswith(media_path):
        path = path[len(media_path):]

    return normalize_storage_name(path)


def _get_storage_and_name(image):
    if not image:
        return default_storage, ""

    name = getattr(image, "name", None)
    storage = getattr(image, "storage", None)

    if name:
        return storage or default_storage, normalize_storage_name(name)

    image_text = _plain_string(image).strip()

    if image_text.startswith("http://") or image_text.startswith("https://"):
        return default_storage, _name_from_url(image_text)

    return default_storage, normalize_storage_name(image_text)


def _original_url(image, storage, name):
    if image:
        try:
            url = getattr(image, "url", None)
            if url:
                return url
        except Exception:
            pass

    if name:
        try:
            return storage.url(name)
        except Exception:
            pass

    return ""


def optimized_name_for(original_name, preset):
    preset = normalize_storage_name(preset or "seo")
    original_name = normalize_storage_name(original_name)

    if not original_name or original_name.startswith("optimized/"):
        return ""

    original_path = PurePosixPath(original_name)
    without_suffix = str(original_path.with_suffix("")) if original_path.suffix else original_name

    return normalize_storage_name(f"optimized/{preset}/{without_suffix}.webp")


def _local_cache_get(key):
    cached = _LOCAL_URL_CACHE.get(key)
    if not cached:
        return None

    expires_at, value = cached

    if expires_at <= time.monotonic():
        _LOCAL_URL_CACHE.pop(key, None)
        return None

    return value


def _local_cache_set(key, value, timeout):
    if len(_LOCAL_URL_CACHE) > 5000:
        now = time.monotonic()
        for cached_key, cached_value in list(_LOCAL_URL_CACHE.items()):
            expires_at, _value = cached_value
            if expires_at <= now:
                _LOCAL_URL_CACHE.pop(cached_key, None)

    _LOCAL_URL_CACHE[key] = (time.monotonic() + timeout, value)


def _storage_exists(storage, name):
    try:
        return storage.exists(name)
    except Exception:
        return False


def get_optimized_image_url(image, preset="product_card", force_generate=False):
    preset = normalize_storage_name(preset or "product_card")

    if not getattr(settings, "OPTIMIZED_MEDIA_ENABLED", True):
        return getattr(image, "url", image or "")

    storage, original_name = _get_storage_and_name(image)
    original_url = _original_url(image, storage, original_name)

    if not original_name:
        return original_url

    lower_name = original_name.lower()

    if lower_name.endswith(SKIP_EXTENSIONS):
        return original_url

    if not lower_name.endswith(IMAGE_EXTENSIONS):
        return original_url

    if original_name.startswith("optimized/"):
        return original_url

    optimized_name = optimized_name_for(original_name, preset)

    if not optimized_name:
        return original_url

    cache_key = f"optimized-image-url:{storage.__class__.__name__}:{preset}:{original_name}"
    cached_url = _local_cache_get(cache_key)

    if cached_url is _MISSING_OPTIMIZED:
        return original_url

    if cached_url:
        return cached_url

    if _storage_exists(storage, optimized_name):
        try:
            url = storage.url(optimized_name)
            _local_cache_set(cache_key, url, 3600)
            return url
        except Exception:
            return original_url

    should_generate = force_generate or getattr(
        settings,
        "OPTIMIZED_MEDIA_GENERATE_ON_REQUEST",
        False,
    )

    if not should_generate:
        _local_cache_set(cache_key, _MISSING_OPTIMIZED, 300)
        return original_url

    created = create_optimized_image(
        storage=storage,
        original_name=original_name,
        optimized_name=optimized_name,
        preset=preset,
    )

    if created and _storage_exists(storage, optimized_name):
        try:
            url = storage.url(optimized_name)
            _local_cache_set(cache_key, url, 3600)
            return url
        except Exception:
            return original_url

    _local_cache_set(cache_key, _MISSING_OPTIMIZED, 300)
    return original_url


def create_optimized_image(storage, original_name, optimized_name, preset):
    if Image is None or ImageOps is None:
        return False

    preset = normalize_storage_name(preset or "seo")
    config = PRESETS.get(preset, PRESETS["seo"])

    try:
        if not storage.exists(original_name):
            return False
    except Exception:
        logger.exception("Could not check source image: %s", original_name)
        return False

    try:
        with storage.open(original_name, "rb") as source:
            source_bytes = source.read()

        with Image.open(BytesIO(source_bytes)) as img:
            if getattr(img, "is_animated", False) or getattr(img, "n_frames", 1) > 1:
                return False

            img = ImageOps.exif_transpose(img)
            img.thumbnail(config["max_size"], Image.Resampling.LANCZOS)

            has_alpha = img.mode in ("RGBA", "LA") or "transparency" in img.info
            img = img.convert("RGBA" if has_alpha else "RGB")

            output = BytesIO()
            img.save(
                output,
                format="WEBP",
                quality=config["quality"],
                method=6,
                optimize=True,
            )

        storage.save(optimized_name, ContentFile(output.getvalue()))
        return True

    except Exception:
        logger.exception("Could not optimize image %s as %s", original_name, preset)
        return False


def field_should_be_skipped(model, field, source_name=""):
    haystack = " ".join(
        [
            model._meta.label_lower,
            str(model._meta.verbose_name).lower(),
            field.name.lower(),
            normalize_storage_name(source_name).lower(),
        ]
    )

    return any(keyword in haystack for keyword in SKIP_KEYWORDS)


def presets_for_field(model, field):
    text = f"{model._meta.label_lower} {model._meta.verbose_name} {field.name}".lower()

    if "mobile" in text and any(word in text for word in ("hero", "background", "banner", "image")):
        return ["mobile_hero", "background_mobile", "seo"]

    if "background" in text and "mobile" in text:
        return ["background_mobile", "seo"]

    if "background" in text or "desktop_background" in text or "page_background" in text:
        return ["background_desktop", "seo"]

    if any(word in text for word in ("hero", "landing")):
        return ["landing_hero", "banner", "seo", "thumbnail"]

    if any(word in text for word in ("banner", "adcreative", "advertisement", "promo")):
        return ["banner", "seo"]

    if any(word in text for word in ("product", "variant", "gallery")):
        return ["seo", "product_detail", "product_thumb"]

    if "accessory" in text:
        return ["accessory_thumb", "product_card", "thumbnail"]

    if "category" in text:
        return ["category_card", "seo", "thumbnail"]

    if "blog" in text:
        return ["blog_card", "seo", "thumbnail"]

    if any(word in text for word in ("avatar", "profile", "photo")):
        return ["avatar", "thumbnail"]

    if "logo" in text:
        return ["logo", "thumbnail", "seo"]

    if any(word in text for word in ("thumb", "thumbnail", "icon")):
        return ["thumbnail", "seo"]

    return ["seo", "thumbnail"]


def optimize_image_file(file_value, presets=None, overwrite=False):
    storage, source_name = _get_storage_and_name(file_value)

    stats = {"created": 0, "existing": 0, "skipped": 0, "errors": 0}

    if not source_name:
        stats["skipped"] += 1
        return stats

    lower_name = source_name.lower()

    if source_name.startswith("optimized/"):
        stats["skipped"] += 1
        return stats

    if lower_name.endswith(SKIP_EXTENSIONS):
        stats["skipped"] += 1
        return stats

    if not lower_name.endswith(IMAGE_EXTENSIONS):
        stats["skipped"] += 1
        return stats

    try:
        if not storage.exists(source_name):
            stats["skipped"] += 1
            return stats
    except Exception:
        logger.exception("Could not check source image existence: %s", source_name)
        stats["errors"] += 1
        return stats

    for preset in presets or ["seo", "thumbnail"]:
        if preset not in PRESETS:
            stats["skipped"] += 1
            continue

        output_name = optimized_name_for(source_name, preset)

        if not output_name:
            stats["skipped"] += 1
            continue

        try:
            if not overwrite and storage.exists(output_name):
                stats["existing"] += 1
                continue
        except Exception:
            logger.exception("Could not check optimized image existence: %s", output_name)
            stats["errors"] += 1
            continue

        created = create_optimized_image(
            storage=storage,
            original_name=source_name,
            optimized_name=output_name,
            preset=preset,
        )

        if created:
            stats["created"] += 1
        else:
            stats["errors"] += 1

    return stats


def auto_optimize_instance_images(instance):
    if not getattr(settings, "AROLANA_AUTO_OPTIMIZE_IMAGES", True):
        return {"created": 0, "existing": 0, "skipped": 0, "errors": 0}

    model = instance.__class__
    totals = {"created": 0, "existing": 0, "skipped": 0, "errors": 0}

    for field in model._meta.fields:
        if not isinstance(field, models.ImageField):
            continue

        try:
            file_value = getattr(instance, field.name, None)
            source_name = normalize_storage_name(getattr(file_value, "name", ""))
        except Exception:
            totals["errors"] += 1
            continue

        if field_should_be_skipped(model, field, source_name):
            totals["skipped"] += 1
            continue

        result = optimize_image_file(
            file_value,
            presets=presets_for_field(model, field),
            overwrite=False,
        )

        for key, value in result.items():
            totals[key] += value

    return totals