from urllib.parse import urlencode

from django import template
from django.urls import reverse


register = template.Library()


@register.simple_tag(takes_context=True)
def login_url_with_next(context, fragment="", destination=None):
    """Return the site login URL with a safe local destination as ``next``."""

    request = context.get("request")
    if destination is None:
        destination = request.get_full_path() if request is not None else "/"
    else:
        destination = str(destination)

    # Request paths should always be local. Keep this guard here as well as in
    # the login view so a malformed protocol-relative path is never emitted by
    # a public-page sign-in link.
    if not destination.startswith("/") or destination.startswith("//"):
        destination = "/"

    fragment = str(fragment or "").lstrip("#")
    if fragment:
        destination = f"{destination}#{fragment}"

    return f"{reverse('accounts:login')}?{urlencode({'next': destination})}"
