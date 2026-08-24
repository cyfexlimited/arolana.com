"""Backward-compatible import for Provider large-upload CSRF protection."""

from core.csrf import HeaderFirstCsrfViewMiddleware, header_first_csrf_protect

__all__ = ("HeaderFirstCsrfViewMiddleware", "header_first_csrf_protect")
