from io import BytesIO
from pathlib import PurePosixPath
from urllib.parse import quote, urljoin, urlsplit
import time

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from PIL import Image, ImageOps, UnidentifiedImageError


PRESETS = {
    "nav_icon": (96, 96),
    "logo": (360, 160),
    "avatar": (160, 160),
    "accessory_thumb": (240, 240),
    "category_card": (560, 420),
    "product_thumb": (180, 180),
    "product_card": (640, 640),
    "product_detail": (1100, 1100),
    "ad_card": (720, 360),
    "hero": (1600, 900),
}

_LOCAL_URL_CACHE = {}
_MISSING_OPTIMIZED = object()


def get_optimized_image_url(image, preset="product_card", force_generate=False):
    """
    Use this for visible frontend images:
    - product cards
    - galleries
    - banners
    - category cards

    This may return signed storage URLs depending on your storage settings.
    Do not use this for SEO meta images or JSON-LD schema images.
    Use get_seo_media_url() for SEO.
    """
    preset = _plain_string(preset or "product_card")

    if not getattr(settings, "OPTIMIZED_MEDIA_ENABLED", True):
        return getattr(image, "url", image or "")

    if not image:
        return ""

    if isinstance(image, str):
        return image

    original_name = _plain_string(getattr(image, "name", ""))
    if not original_name:
        return getattr(image, "url", "")

    if original_name.lower().endswith((".svg", ".gif", ".ico")):
        return getattr(image, "url", "")

    size = PRESETS.get(preset, PRESETS["product_card"])
    optimized_name = _optimized_name(original_name, preset)
    cache_key = f"optimized-image-url:{preset}:{original_name}"

    if not force_generate and not getattr(
        settings,
        "OPTIMIZED_MEDIA_GENERATE_ON_REQUEST",
        False,
    ):
        url = default_storage.url(optimized_name)
        _local_cache_set(cache_key, url, 3600)
        return url

    cached_url = _local_cache_get(cache_key)
    if cached_url is _MISSING_OPTIMIZED:
        return getattr(image, "url", "")
    if cached_url:
        return cached_url

    try:
        if not default_storage.exists(optimized_name):
            if not force_generate and not getattr(
                settings,
                "OPTIMIZED_MEDIA_GENERATE_ON_REQUEST",
                False,
            ):
                _local_cache_set(cache_key, _MISSING_OPTIMIZED, 3600)
                return getattr(image, "url", "")

            _create_optimized_image(original_name, optimized_name, size)

        url = default_storage.url(optimized_name)
        _local_cache_set(cache_key, url, 3600)
        return url

    except Exception:
        return getattr(image, "url", "")


def get_seo_media_url(image, preset=None, request=None, use_optimized=False):
    """
    Use this for SEO only:
    - og:image
    - twitter:image
    - Product JSON-LD image
    - Organization logo schema
    - favicon when you want clean public URLs

    It returns clean permanent URLs like:
    https://arolana.com/media/products/2026/06/image.webp

    It removes:
    - X-Amz-Signature
    - X-Amz-Date
    - X-Amz-Expires
    - temporary signed query strings
    """
    name = _clean_storage_name(image)

    if not name:
        return ""

    if use_optimized and preset:
        name = _optimized_name(name, preset)

    return _build_public_media_url(name, request=request)


def get_public_media_url(image, request=None):
    """
    General public permanent media URL helper.
    """
    return get_seo_media_url(image, request=request)


def _optimized_name(original_name, preset):
    preset = _plain_string(preset or "product_card")
    original_name = _plain_string(original_name)
    original_path = PurePosixPath(original_name)
    return str(PurePosixPath("optimized") / preset / original_path.with_suffix(".webp"))


def _clean_storage_name(value):
    """
    Converts any of these:
    - FieldFile
    - ImageFieldFile
    - products/2026/06/image.png
    - /media/products/2026/06/image.png
    - https://bucket.example/products/2026/06/image.png?X-Amz-Signature=...
    - https://arolana.com/media/products/2026/06/image.png

    Into:
    products/2026/06/image.png
    """
    if not value:
        return ""

    name = _plain_string(getattr(value, "name", "") or "")

    if not name:
        raw = _plain_string(value).strip()
        raw = raw.split("?", 1)[0].strip()

        if raw.startswith("http://") or raw.startswith("https://"):
            parsed = urlsplit(raw)
            path = parsed.path.lstrip("/")

            bucket_name = _plain_string(getattr(settings, "AWS_STORAGE_BUCKET_NAME", "") or "")
            if bucket_name and path.startswith(f"{bucket_name}/"):
                path = path[len(bucket_name) + 1:]

            if "/media/" in parsed.path:
                path = parsed.path.split("/media/", 1)[1].lstrip("/")

            name = path
        else:
            name = raw

    name = name.split("?", 1)[0].strip().lstrip("/")

    if name.startswith("media/"):
        name = name[len("media/"):]

    bucket_name = _plain_string(getattr(settings, "AWS_STORAGE_BUCKET_NAME", "") or "")
    if bucket_name and name.startswith(f"{bucket_name}/"):
        name = name[len(bucket_name) + 1:]

    return name


def _build_public_media_url(name, request=None):
    name = _plain_string(name).split("?", 1)[0].strip().lstrip("/")

    if not name:
        return ""

    encoded_name = quote(name, safe="/")

    public_base = _plain_string(
        getattr(settings, "AROLANA_PUBLIC_MEDIA_BASE_URL", "") or ""
    ).strip()

    if public_base:
        public_base = public_base.split("?", 1)[0].rstrip("/") + "/"
        return urljoin(public_base, encoded_name)

    media_url = _plain_string(getattr(settings, "MEDIA_URL", "/media/") or "/media/")
    media_url = media_url.split("?", 1)[0].rstrip("/") + "/"

    if media_url.startswith("http://") or media_url.startswith("https://"):
        return urljoin(media_url, encoded_name)

    site_url = _plain_string(getattr(settings, "SITE_URL", "") or "").rstrip("/")

    if not site_url and request:
        site_url = f"{request.scheme}://{request.get_host()}".rstrip("/")

    if not site_url:
        site_url = "https://arolana.com"

    media_path = urljoin(media_url, encoded_name).lstrip("/")
    return urljoin(site_url + "/", media_path)


def _plain_string(value):
    return "".join([str(value)])


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

        for cached_key, (expires_at, _) in list(_LOCAL_URL_CACHE.items()):
            if expires_at <= now:
                _LOCAL_URL_CACHE.pop(cached_key, None)

    _LOCAL_URL_CACHE[key] = (time.monotonic() + timeout, value)


def _create_optimized_image(original_name, optimized_name, size):
    with default_storage.open(original_name, "rb") as source:
        try:
            image = Image.open(source)
            image = ImageOps.exif_transpose(image)
        except UnidentifiedImageError:
            raise

        if image.mode not in ("RGB", "RGBA"):
            image = image.convert("RGBA" if "A" in image.getbands() else "RGB")

        image.thumbnail(size, Image.Resampling.LANCZOS)

        output = BytesIO()
        image.save(output, format="WEBP", quality=82, method=6)

        default_storage.save(optimized_name, ContentFile(output.getvalue()))