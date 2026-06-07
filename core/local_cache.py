import time
from threading import RLock


_CACHE = {}
_LOCK = RLock()


def local_get(key):
    with _LOCK:
        cached = _CACHE.get(key)
        if not cached:
            return None

        expires_at, value = cached
        if expires_at <= time.monotonic():
            _CACHE.pop(key, None)
            return None

        return value


def local_set(key, value, timeout):
    with _LOCK:
        if len(_CACHE) > 10000:
            _prune_expired()
        _CACHE[key] = (time.monotonic() + timeout, value)


def local_delete(key):
    with _LOCK:
        _CACHE.pop(key, None)


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
        if len(_CACHE) > 10000:
            _prune_expired()
        _CACHE[key] = (time.monotonic() + timeout, value)
        return value


def _prune_expired():
    now = time.monotonic()
    for key, (expires_at, _) in list(_CACHE.items()):
        if expires_at <= now:
            _CACHE.pop(key, None)
