from urllib.parse import quote, urljoin, urlsplit

from django import template
from django.conf import settings

from core.media_optimization import get_optimized_image_url


register = template.Library()


@register.simple_tag
def optimized_image_url(image, preset="product_card"):
    """
    Use this for visible website images only:
    product cards, gallery images, homepage banners, category images, ads.
    This can still return optimized/signed storage URLs depending on storage.
    Do not use it for SEO/meta/schema images.
    """
    return get_optimized_image_url(image, preset)


def _plain(value):
    if value is None:
        return ""
    return str(value).strip()


def _public_base_url():
    """
    Permanent public media base for SEO.
    Example:
        https://arolana.com/media/
    """
    public_base = _plain(getattr(settings, "AROLANA_PUBLIC_MEDIA_BASE_URL", ""))

    if public_base:
        return public_base.split("?", 1)[0].rstrip("/") + "/"

    site_url = _plain(getattr(settings, "SITE_URL", "https://arolana.com")).rstrip("/")
    return f"{site_url}/media/"


def _clean_file_name(image):
    """
    Convert a FileField, ImageField, storage path, normal media URL,
    or signed S3/Tigris URL into a clean media storage name.

    Examples:
        products/2026/06/image.webp
        /media/products/2026/06/image.webp
        https://arolana.com/media/products/2026/06/image.webp
        https://endpoint/bucket/products/2026/06/image.webp?X-Amz-Signature=...
    becomes:
        products/2026/06/image.webp
    """
    if not image:
        return ""

    name = _plain(getattr(image, "name", ""))

    if not name:
        raw = _plain(image).split("?", 1)[0]

        if not raw:
            return ""

        if raw.startswith("http://") or raw.startswith("https://"):
            parsed = urlsplit(raw)
            path = parsed.path.lstrip("/")

            if "/media/" in parsed.path:
                path = parsed.path.split("/media/", 1)[1].lstrip("/")

            bucket_name = _plain(getattr(settings, "AWS_STORAGE_BUCKET_NAME", ""))
            if bucket_name and path.startswith(f"{bucket_name}/"):
                path = path[len(bucket_name) + 1:]

            name = path
        else:
            name = raw

    name = _plain(name).split("?", 1)[0].lstrip("/")

    if name.startswith("media/"):
        name = name[len("media/"):]

    bucket_name = _plain(getattr(settings, "AWS_STORAGE_BUCKET_NAME", ""))
    if bucket_name and name.startswith(f"{bucket_name}/"):
        name = name[len(bucket_name) + 1:]

    # Prevent an already-full URL from being encoded into /media/https%3A...
    if name.startswith("http://") or name.startswith("https://"):
        parsed = urlsplit(name)
        name = parsed.path.lstrip("/")
        if "/media/" in parsed.path:
            name = parsed.path.split("/media/", 1)[1].lstrip("/")
        if bucket_name and name.startswith(f"{bucket_name}/"):
            name = name[len(bucket_name) + 1:]

    return name


def _build_public_media_url(name):
    name = _plain(name).split("?", 1)[0].lstrip("/")

    if not name:
        return ""

    encoded_name = quote(name, safe="/")
    return urljoin(_public_base_url(), encoded_name)


@register.simple_tag(takes_context=True)
def seo_media_url(context, image):
    """
    Clean permanent public image URL for SEO only:
    - og:image
    - twitter:image
    - JSON-LD Product image
    - Organization logo schema
    - favicon if required

    This avoids X-Amz-Signature, X-Amz-Date, X-Amz-Expires.
    """
    name = _clean_file_name(image)

    if not name:
        return ""

    return _build_public_media_url(name)


@register.simple_tag(takes_context=True)
def first_seo_media_url(context, *images):
    """
    Return the first clean SEO-safe image URL from multiple candidates.

    Use this on product pages so SEO image does not fall back to Arolana logo
    when product.main_image is empty.

    Recommended order:
    product.main_image,
    merchant_data.image_link,
    gallery_images.0.original,
    gallery_images.0.src,
    gallery_images.0.thumb
    """
    for image in images:
        name = _clean_file_name(image)
        if name:
            return _build_public_media_url(name)
    return ""
