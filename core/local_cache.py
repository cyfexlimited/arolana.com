import time
from threading import RLock

from django.core.cache import cache


_CACHE = {}
_LOCK = RLock()
_CACHE_MISS = object()


def local_get(key):
    with _LOCK:
        cached = _CACHE.get(key)
        if cached:
            expires_at, value = cached
            if expires_at > time.monotonic():
                return value
            _CACHE.pop(key, None)

    try:
        value = cache.get(key, _CACHE_MISS)
    except Exception:
        return None

    if value is _CACHE_MISS:
        return None

    with _LOCK:
        _CACHE[key] = (time.monotonic() + 60, value)
    return value


def local_set(key, value, timeout):
    with _LOCK:
        if len(_CACHE) > 10000:
            _prune_expired()
        _CACHE[key] = (time.monotonic() + timeout, value)
    try:
        cache.set(key, value, timeout)
    except Exception:
        pass


def local_delete(key):
    with _LOCK:
        _CACHE.pop(key, None)
    try:
        cache.delete(key)
    except Exception:
        pass


def local_delete_prefix(prefix):
    with _LOCK:
        for key in [key for key in _CACHE if key.startswith(prefix)]:
            _CACHE.pop(key, None)
    try:
        delete_pattern = getattr(cache, "delete_pattern", None)
        if delete_pattern:
            delete_pattern(f"{prefix}*")
    except Exception:
        pass


def local_get_or_set(key, builder, timeout):
    cached = local_get(key)
    if cached is not None:
        return cached

    # Keep one request responsible for an expensive cold-cache build. Without
    # this lock, simultaneous homepage requests repeat the same database work.
    with _LOCK:
        cached = _CACHE.get(key)
        if cached:
            expires_at, value = cached
            if expires_at > time.monotonic():
                return value
            _CACHE.pop(key, None)

        value = builder()
        local_set(key, value, timeout)
        return value


def _prune_expired():
    now = time.monotonic()
    for key, (expires_at, _) in list(_CACHE.items()):
        if expires_at <= now:
            _CACHE.pop(key, None)
