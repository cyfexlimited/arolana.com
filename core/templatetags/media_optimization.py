from urllib.parse import quote, urljoin

from django import template
from django.conf import settings

from core.media_optimization import get_optimized_image_url


register = template.Library()


@register.simple_tag
def optimized_image_url(image, preset="product_card"):
    """
    Use this for visible website images only.
    Example: product card, gallery, homepage banners.
    """
    return get_optimized_image_url(image, preset)


def _clean_file_name(image):
    if not image:
        return ""

    name = getattr(image, "name", "") or ""

    if not name:
        raw = str(image)
        raw = raw.split("?", 1)[0]

        if "/media/" in raw:
            raw = raw.split("/media/", 1)[1]

        name = raw

    name = str(name).strip().lstrip("/")

    if name.startswith("media/"):
        name = name[len("media/"):]

    return name


@register.simple_tag(takes_context=True)
def seo_media_url(context, image):
    """
    Use this for SEO images only:
    - og:image
    - twitter:image
    - JSON-LD Product image
    - Organization logo schema
    - favicon if you want it clean

    It avoids temporary signed S3/Tigris URLs.
    """
    name = _clean_file_name(image)

    if not name:
        return ""

    encoded_name = quote(name, safe="/")

    public_base = getattr(settings, "AROLANA_PUBLIC_MEDIA_BASE_URL", "").strip()

    if public_base:
        return urljoin(public_base.rstrip("/") + "/", encoded_name)

    media_url = getattr(settings, "MEDIA_URL", "/media/")

    if media_url.startswith("http://") or media_url.startswith("https://"):
        clean_media_url = media_url.split("?", 1)[0]
        return urljoin(clean_media_url.rstrip("/") + "/", encoded_name)

    clean_path = urljoin(media_url.rstrip("/") + "/", encoded_name)

    request = context.get("request")
    if request:
        return request.build_absolute_uri(clean_path)

    site_url = getattr(settings, "SITE_URL", "https://arolana.com")
    return urljoin(site_url.rstrip("/") + "/", clean_path.lstrip("/"))