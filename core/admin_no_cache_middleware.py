class AdminNoCacheMiddleware:
    """
    Prevent browser/CDN caching of Django admin pages.

    Why this exists:
    - If an admin user clears browser cache/history/cookies, old admin forms
      may still be opened from browser history.
    - Those old forms can contain stale CSRF tokens.
    - Django correctly blocks stale submissions with CSRF 403.
    - This middleware tells browsers/proxies/CDNs not to cache admin pages.

    Important:
    - This does NOT disable CSRF.
    - This does NOT weaken admin security.
    - It only prevents stale admin pages/forms from being reused.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        path = request.path or ""

        if path.startswith("/admin/"):
            response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response["Pragma"] = "no-cache"
            response["Expires"] = "0"
            response["Surrogate-Control"] = "no-store"

        return response