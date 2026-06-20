from html import unescape
from urllib.parse import quote, urljoin, urlsplit

from django import template
from django.conf import settings

from core.media_optimization import get_optimized_image_url


register = template.Library()


PUBLIC_MEDIA_PREFIXES = {
    "settings",
    "categories",
    "vendors",
    "hero_banners",
    "products",
    "ads",
    "optimized",
    "manufacturers",
    "homepage",
    "videos",
    "brands",
    "advertisements",
    "promo",
    "avatars",
    "blog",
    "landing_pages",
    "uploads",
}


IMAGE_FIELD_NAMES = [
    "main_image",
    "image",
    "image_url",
    "file",
    "file_url",
    "photo",
    "src",
    "url",
    "thumbnail",
    "thumb",
    "original",
    "featured_image",
    "primary_image",
    "default_image",
    "cover_image",
]


PRODUCT_RELATED_NAMES = [
    "gallery_images",
    "images",
    "product_images",
    "media",
    "media_images",
    "additional_images",
    "photos",
    "variant_images",
    "variants",
]


@register.simple_tag
def optimized_image_url(image, preset="product_card"):
    """
    Use this only for visible frontend images.
    It may return signed storage URLs depending on storage backend settings.
    """
    return get_optimized_image_url(image, preset)


@register.simple_tag(takes_context=True)
def seo_media_url(context, image):
    """
    Clean permanent public URL for SEO/media metadata.
    """
    request = context.get("request")
    name = _clean_file_name(image)

    if not name:
        return ""

    return _build_public_media_url(name, request=request)


@register.simple_tag(takes_context=True)
def product_seo_image_url(context, product=None, merchant_data=None, gallery_images=None):
    """
    Final product image fallback for SEO.

    Template use:
    {% product_seo_image_url product merchant_data gallery_images as product_final_seo_image_url %}

    It returns a clean public product image URL and skips Arolana/settings logo paths.
    """
    request = context.get("request")

    for candidate in _product_image_candidates(product, merchant_data, gallery_images):
        name = _clean_file_name(candidate)

        if name and not _looks_like_site_logo(name):
            return _build_public_media_url(name, request=request)

    return ""


def _product_image_candidates(product=None, merchant_data=None, gallery_images=None):
    # 1. Direct product fields.
    if product:
        for field_name in IMAGE_FIELD_NAMES:
            value = _safe_getattr(product, field_name)
            if value:
                yield value

        for method_name in (
            "get_main_image",
            "get_primary_image",
            "get_default_image",
            "get_thumbnail",
            "primary_media",
            "main_media",
        ):
            method = _safe_getattr(product, method_name)

            if callable(method):
                try:
                    value = method()
                except Exception:
                    value = None

                if value:
                    yield value

    # 2. Merchant/feed metadata.
    for key in IMAGE_FIELD_NAMES:
        value = _extract_from_mapping_or_object(merchant_data, key)

        if value:
            yield value

    # 3. Gallery images passed by the product detail view.
    yield from _yield_images_from_collection(gallery_images)

    # 4. Related managers on product.
    if product:
        for related_name in PRODUCT_RELATED_NAMES:
            related = _safe_getattr(product, related_name)

            if not related:
                continue

            try:
                items = related.all()
            except Exception:
                items = related

            yield from _yield_images_from_collection(items)


def _yield_images_from_collection(collection):
    if not collection:
        return

    if isinstance(collection, (str, bytes)):
        yield collection
        return

    try:
        items = collection[:40]
    except Exception:
        items = collection

    try:
        iterator = iter(items)
    except TypeError:
        iterator = iter([items])

    for item in iterator:
        if not item:
            continue

        if isinstance(item, (str, bytes)):
            yield item
            continue

        if _looks_like_file_object(item):
            yield item

        for key in IMAGE_FIELD_NAMES:
            value = _extract_from_mapping_or_object(item, key)

            if value:
                yield value

        for related_name in ("images", "gallery_images", "variant_images", "media"):
            nested = _safe_getattr(item, related_name)

            if not nested:
                continue

            try:
                nested_items = nested.all()
            except Exception:
                nested_items = nested

            yield from _yield_images_from_collection(nested_items)


def _looks_like_file_object(value):
    return bool(getattr(value, "name", "") or getattr(value, "url", ""))


def _extract_from_mapping_or_object(obj, key):
    if not obj:
        return None

    if isinstance(obj, dict):
        return obj.get(key)

    try:
        return getattr(obj, key, None)
    except Exception:
        return None


def _safe_getattr(obj, name):
    try:
        return getattr(obj, name, None)
    except Exception:
        return None


def _clean_file_name(image):
    if not image:
        return ""

    if isinstance(image, dict):
        for key in (
            "original",
            "image",
            "main_image",
            "src",
            "url",
            "image_url",
            "thumbnail",
            "thumb",
            "file",
            "photo",
        ):
            value = image.get(key)

            if value:
                return _clean_file_name(value)

        return ""

    name = getattr(image, "name", "") or ""

    if not name:
        try:
            raw_url = getattr(image, "url", "") or ""
        except Exception:
            raw_url = ""

        raw = raw_url or str(image)
        name = _extract_path_from_any_url(raw)

    name = str(name or "").strip()
    name = unescape(name)
    name = name.split("?", 1)[0].strip().lstrip("/")

    if name.startswith("media/"):
        name = name[len("media/"):]

    bucket_name = str(getattr(settings, "AWS_STORAGE_BUCKET_NAME", "") or "").strip()

    if bucket_name and name.startswith(f"{bucket_name}/"):
        name = name[len(bucket_name) + 1:]

    parts = name.split("/", 1)

    if len(parts) == 2:
        first = parts[0]
        second_first = parts[1].split("/", 1)[0]

        if first not in PUBLIC_MEDIA_PREFIXES and second_first in PUBLIC_MEDIA_PREFIXES:
            name = parts[1]

    return name


def _extract_path_from_any_url(raw):
    raw = str(raw or "").strip()
    raw = unescape(raw)
    raw = raw.split("?", 1)[0].strip()

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

        parts = path.split("/", 1)

        if len(parts) == 2:
            first = parts[0]
            second_first = parts[1].split("/", 1)[0]

            if first not in PUBLIC_MEDIA_PREFIXES and second_first in PUBLIC_MEDIA_PREFIXES:
                path = parts[1]

        return path

    return raw


def _build_public_media_url(name, request=None):
    name = str(name or "").split("?", 1)[0].strip().lstrip("/")

    if not name:
        return ""

    encoded_name = quote(name, safe="/")

    public_base = str(getattr(settings, "AROLANA_PUBLIC_MEDIA_BASE_URL", "") or "").strip()

    if public_base:
        return urljoin(public_base.rstrip("/") + "/", encoded_name)

    media_url = str(getattr(settings, "MEDIA_URL", "/media/") or "/media/")
    media_url = media_url.split("?", 1)[0]

    if media_url.startswith("http://") or media_url.startswith("https://"):
        return urljoin(media_url.rstrip("/") + "/", encoded_name)

    clean_path = urljoin(media_url.rstrip("/") + "/", encoded_name)

    if request:
        return request.build_absolute_uri(clean_path)

    site_url = str(getattr(settings, "SITE_URL", "https://arolana.com") or "https://arolana.com")

    return urljoin(site_url.rstrip("/") + "/", clean_path.lstrip("/"))


def _looks_like_site_logo(name):
    lowered = str(name or "").lower()

    return (
        lowered.startswith("settings/")
        or "arolana_logo" in lowered
        or "arolana-logo" in lowered
        or ("arolana.com" in lowered and "settings" in lowered)
    )
