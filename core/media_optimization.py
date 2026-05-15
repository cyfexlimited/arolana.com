from io import BytesIO
from pathlib import PurePosixPath
import time

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from PIL import Image, ImageOps, UnidentifiedImageError


PRESETS = {
    'nav_icon': (96, 96),
    'logo': (360, 160),
    'avatar': (160, 160),
    'category_card': (560, 420),
    'product_card': (640, 640),
    'ad_card': (720, 360),
    'hero': (1600, 900),
}

_LOCAL_URL_CACHE = {}


def get_optimized_image_url(image, preset='product_card'):
    preset = _plain_string(preset or 'product_card')

    if not getattr(settings, 'OPTIMIZED_MEDIA_ENABLED', True):
        return getattr(image, 'url', image or '')

    if not image:
        return ''

    if isinstance(image, str):
        return image

    original_name = _plain_string(getattr(image, 'name', ''))
    if not original_name:
        return getattr(image, 'url', '')

    if original_name.lower().endswith(('.svg', '.gif', '.ico')):
        return image.url

    size = PRESETS.get(preset, PRESETS['product_card'])
    optimized_name = _optimized_name(original_name, preset)
    cache_key = f'optimized-image-url:{preset}:{original_name}'

    cached_url = _local_cache_get(cache_key)
    if cached_url:
        return cached_url

    try:
        if not default_storage.exists(optimized_name):
            _create_optimized_image(original_name, optimized_name, size)
        url = default_storage.url(optimized_name)
        _local_cache_set(cache_key, url, 3600)
        return url
    except Exception:
        return image.url


def _optimized_name(original_name, preset):
    preset = _plain_string(preset or 'product_card')
    original_name = _plain_string(original_name)
    original_path = PurePosixPath(original_name)
    return str(PurePosixPath('optimized') / preset / original_path.with_suffix('.webp'))


def _plain_string(value):
    return ''.join([str(value)])


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
    with default_storage.open(original_name, 'rb') as source:
        try:
            image = Image.open(source)
            image = ImageOps.exif_transpose(image)
        except UnidentifiedImageError:
            raise

        if image.mode not in ('RGB', 'RGBA'):
            image = image.convert('RGBA' if 'A' in image.getbands() else 'RGB')

        image.thumbnail(size, Image.Resampling.LANCZOS)
        output = BytesIO()
        image.save(output, format='WEBP', quality=82, method=6)
        default_storage.save(optimized_name, ContentFile(output.getvalue()))
