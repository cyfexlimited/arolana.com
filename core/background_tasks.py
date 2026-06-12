import logging
from concurrent.futures import ThreadPoolExecutor

from django.db import close_old_connections


logger = logging.getLogger(__name__)
_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="arolana-bg")


def submit_background(func, *args, **kwargs):
    """Run short external-I/O work without blocking the request thread."""

    def runner():
        close_old_connections()
        try:
            return func(*args, **kwargs)
        except Exception:
            logger.exception("Background task failed: %s", getattr(func, "__name__", func))
            return None
        finally:
            close_old_connections()

    return _EXECUTOR.submit(runner)
