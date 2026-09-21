from urllib.parse import urlparse

from catalog_imports.models import ImportSource


def normalize_host(value: str) -> str:
    host = (value or "").lower().strip().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host


def source_for_url(url: str):
    host = normalize_host(urlparse(url or "").hostname or "")
    if not host:
        return None
    for source in ImportSource.objects.filter(is_active=True).order_by("name"):
        domain = normalize_host(source.domain)
        if host == domain or host.endswith("." + domain):
            return source
    return None
