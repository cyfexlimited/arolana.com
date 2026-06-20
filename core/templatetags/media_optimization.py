from urllib.parse import quote, urljoin, urlsplit

from django import template
from django.conf import settings

from core.media_optimization import get_optimized_image_url


register = template.Library()


@register.simple_tag
def optimized_image_url(image, preset="product_card"):
    """
    Use this for visible website images only.
    Example: product card, gallery, homepage banners.

    Do not use this for SEO/social/schema images because your storage
    may return temporary signed URLs.
    """
    return get_optimized_image_url(image, preset)


@register.simple_tag(takes_context=True)
def seo_media_url(context, image, preset=None):
    """
    Use this for SEO images only:
    - og:image
    - twitter:image
    - JSON-LD Product image
    - Organization logo schema
    - favicon if you want it clean

    It avoids temporary signed S3/Tigris URLs by building a permanent
    public URL from the stored file name.
    """
    name = _clean_file_name(image)

    if not name:
        return ""

    if preset:
        name = _optimized_name(name, preset)

    request = context.get("request")
    return _build_public_media_url(name, request=request)


@register.simple_tag(takes_context=True)
def product_seo_image_url(context, product, merchant_data=None, gallery_images=None):
    """
    Strong product-image fallback for product SEO.

    Fallback order:
    1. Product main image fields
    2. Merchant metadata image_link/image fields
    3. Gallery images from context
    4. Related product image managers
    5. Variant images

    The Arolana logo should only be handled in the template as the final
    emergency fallback, never here.
    """
    request = context.get("request")

    for candidate in _product_image_candidates(product, merchant_data, gallery_images):
        if _looks_like_site_logo(candidate):
            continue

        name = _clean_file_name(candidate)
        if not name:
            continue

        url = _build_public_media_url(name, request=request)
        if url and not _looks_like_site_logo(url):
            return url

    return ""


def _product_image_candidates(product, merchant_data=None, gallery_images=None):
    if not product:
        return

    # Direct product image fields.
    for attr in (
        "main_image",
        "image",
        "product_image",
        "featured_image",
        "primary_image",
        "thumbnail",
        "photo",
        "picture",
    ):
        value = _get_attr(product, attr)
        if value:
            yield value

    # SEO / merchant metadata returned by your arolana_seo template tags.
    for key in (
        "image_link",
        "image",
        "image_url",
        "main_image",
        "thumbnail",
        "thumbnail_url",
    ):
        value = _get_value(merchant_data, key)
        if value:
            yield value

    # Gallery images already provided to the template context.
    for item in _safe_iter(gallery_images):
        for key in (
            "original",
            "src",
            "thumb",
            "image",
            "image_url",
            "url",
            "file",
            "photo",
            "picture",
        ):
            value = _get_value(item, key)
            if value:
                yield value

    # Common related managers for product image models.
    for manager_name in (
        "gallery_images",
        "images",
        "product_images",
        "media",
        "photos",
        "pictures",
    ):
        manager = _get_attr(product, manager_name)
        for item in _manager_items(manager):
            for key in (
                "image",
                "main_image",
                "file",
                "photo",
                "picture",
                "original",
                "src",
                "thumb",
                "url",
            ):
                value = _get_value(item, key)
                if value:
                    yield value

    # Variant images, in case the product image lives on the first/default variant.
    for manager_name in ("variants", "product_variants"):
        manager = _get_attr(product, manager_name)
        for variant in _manager_items(manager):
            for key in (
                "main_image",
                "image",
                "variant_image",
                "thumbnail",
                "photo",
                "picture",
            ):
                value = _get_value(variant, key)
                if value:
                    yield value

            for nested_manager_name in ("images", "gallery_images", "media"):
                nested_manager = _get_attr(variant, nested_manager_name)
                for item in _manager_items(nested_manager):
                    for key in (
                        "image",
                        "file",
                        "photo",
                        "picture",
                        "original",
                        "src",
                        "thumb",
                        "url",
                    ):
                        value = _get_value(item, key)
                        if value:
                            yield value


def _safe_iter(value):
    if not value:
        return []

    if isinstance(value, (str, bytes)):
        return [value]

    try:
        return list(value)
    except TypeError:
        return [value]
    except Exception:
        return []


def _manager_items(manager, limit=12):
    if not manager:
        return []

    try:
        if hasattr(manager, "all"):
            return list(manager.all()[:limit])
    except Exception:
        pass

    return _safe_iter(manager)[:limit]


def _get_attr(obj, attr):
    try:
        return getattr(obj, attr, None)
    except Exception:
        return None


def _get_value(obj, key):
    if not obj:
        return None

    if isinstance(obj, dict):
        return obj.get(key)

    value = _get_attr(obj, key)
    if value:
        return value

    # Some context gallery objects use dictionary-style access only.
    try:
        return obj[key]
    except Exception:
        return None


def _clean_file_name(image):
    if not image:
        return ""

    # Django FieldFile/ImageFieldFile gives the best permanent storage key here.
    name = getattr(image, "name", "") or ""

    if not name:
        raw = str(image or "").strip()
        raw = raw.split("?", 1)[0]

        if not raw:
            return ""

        if raw.startswith("http://") or raw.startswith("https://"):
            parsed = urlsplit(raw)
            path = parsed.path.lstrip("/")

            if "/media/" in parsed.path:
                path = parsed.path.split("/media/", 1)[1].lstrip("/")

            bucket_name = str(getattr(settings, "AWS_STORAGE_BUCKET_NAME", "") or "").strip()
            if bucket_name and path.startswith(f"{bucket_name}/"):
                path = path[len(bucket_name) + 1:]

            name = path
        else:
            if "/media/" in raw:
                raw = raw.split("/media/", 1)[1]
            name = raw

    name = str(name).strip().split("?", 1)[0].lstrip("/")

    if name.startswith("media/"):
        name = name[len("media/"):]

    bucket_name = str(getattr(settings, "AWS_STORAGE_BUCKET_NAME", "") or "").strip()
    if bucket_name and name.startswith(f"{bucket_name}/"):
        name = name[len(bucket_name) + 1:]

    return name


def _optimized_name(original_name, preset):
    from pathlib import PurePosixPath

    original_path = PurePosixPath(str(original_name))
    return str(PurePosixPath("optimized") / str(preset) / original_path.with_suffix(".webp"))


def _build_public_media_url(name, request=None):
    name = str(name or "").strip().split("?", 1)[0].lstrip("/")

    if not name:
        return ""

    encoded_name = quote(name, safe="/")

    public_base = str(getattr(settings, "AROLANA_PUBLIC_MEDIA_BASE_URL", "") or "").strip()

    if public_base:
        return urljoin(public_base.split("?", 1)[0].rstrip("/") + "/", encoded_name)

    media_url = str(getattr(settings, "MEDIA_URL", "/media/") or "/media/")
    media_url = media_url.split("?", 1)[0].rstrip("/") + "/"

    if media_url.startswith("http://") or media_url.startswith("https://"):
        return urljoin(media_url, encoded_name)

    path = urljoin(media_url, encoded_name)

    if request:
        return request.build_absolute_uri(path)

    site_url = str(getattr(settings, "SITE_URL", "https://arolana.com") or "https://arolana.com")
    return urljoin(site_url.rstrip("/") + "/", path.lstrip("/"))


def _looks_like_site_logo(value):
    text = str(value or "").lower()
    if not text:
        return False

    return any(
        marker in text
        for marker in (
            "arolana_logo",
            "arolana-logo",
            "arolana.com_logo",
            "/settings/logo",
            "/settings/arolana",
        )
    )
