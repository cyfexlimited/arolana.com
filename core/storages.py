import time
from urllib.parse import quote

from django.conf import settings
from storages.backends.s3boto3 import S3Boto3Storage


_LOCAL_MEDIA_URL_CACHE = {}


class CachedS3MediaStorage(S3Boto3Storage):
    """Store media in private Tigris and serve fast signed URLs directly."""

    location = ""
    default_acl = None
    querystring_auth = True
    file_overwrite = False

    def url(self, name, parameters=None, expire=None, http_method=None):
        if getattr(settings, "MEDIA_PROXY_ENABLED", False) and not (
            parameters or expire or http_method
        ):
            media_url = getattr(settings, "MEDIA_URL", "/media/")
            return f"{media_url.rstrip('/')}/{quote(str(name).lstrip('/'), safe='/')}"

        if parameters or expire or http_method:
            return super().url(
                name,
                parameters=parameters,
                expire=expire,
                http_method=http_method,
            )

        timeout = max(
            60,
            min(getattr(settings, "AWS_QUERYSTRING_EXPIRE", 86400) - 60, 86400),
        )

        cache_key = f"s3-media-url:{self.bucket_name}:{name}"
        cached_url = _local_cache_get(cache_key)

        if cached_url:
            return cached_url

        url = super().url(
            name,
            parameters=parameters,
            expire=expire,
            http_method=http_method,
        )

        _local_cache_set(cache_key, url, timeout)
        return url


def _local_cache_get(key):
    cached = _LOCAL_MEDIA_URL_CACHE.get(key)
    if not cached:
        return None

    expires_at, value = cached

    if expires_at <= time.monotonic():
        _LOCAL_MEDIA_URL_CACHE.pop(key, None)
        return None

    return value


def _local_cache_set(key, value, timeout):
    if len(_LOCAL_MEDIA_URL_CACHE) > 5000:
        now = time.monotonic()

        for cached_key, (expires_at, _) in list(_LOCAL_MEDIA_URL_CACHE.items()):
            if expires_at <= now:
                _LOCAL_MEDIA_URL_CACHE.pop(cached_key, None)

    _LOCAL_MEDIA_URL_CACHE[key] = (time.monotonic() + timeout, value)
