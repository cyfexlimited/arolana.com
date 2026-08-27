from html import unescape
from urllib.parse import quote, urljoin, urlsplit

from django import template
from django.conf import settings

from core.media_optimization import (
    get_optimized_image_url,
    get_safe_background_image_url,
    get_verified_optimized_image_url,
    optimized_name_for,
)


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
    "installers",
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
    "picture",
    "display_image",
    "optimized_image",
]


PRODUCT_RELATED_NAMES = [
    "gallery_images",
    "images",
    "product_images",
    "productimage_set",
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


@register.simple_tag
def safe_background_image_url(image, preset="background_desktop"):
    """Optimized CSS background URL with guaranteed original-upload fallback."""
    return get_safe_background_image_url(image, preset)


@register.simple_tag(takes_context=True)
def deterministic_optimized_image_url(context, image, preset="nav_icon"):
    """Return a public derivative URL without checking remote storage.

    Navigation images use a browser-side original-image fallback, so rendering
    must not add an S3/Tigris existence request for every icon.
    """
    original_name = _clean_file_name(image)
    if not original_name:
        return ""
    if not getattr(settings, "OPTIMIZED_MEDIA_ENABLED", True):
        return _build_public_media_url(
            original_name,
            request=context.get("request"),
        )
    optimized_name = optimized_name_for(original_name, preset)
    return _build_public_media_url(
        optimized_name or original_name,
        request=context.get("request"),
    )


@register.simple_tag(takes_context=True)
def seo_media_url(context, image, preset=None):
    """
    Clean permanent public URL for SEO/media metadata.

    If preset is provided, prefer the optimized media version first.
    Example:
    {% seo_media_url site_settings.site_logo 'logo' as site_logo_seo_url %}
    """
    request = context.get("request")

    if preset:
        optimized_url = get_verified_optimized_image_url(image, preset)
        optimized_name = _clean_file_name(optimized_url)
        if optimized_name:
            return _build_public_media_url(optimized_name, request=request)

    name = _clean_file_name(image)

    if not name:
        return ""

    return _build_public_media_url(name, request=request)


@register.simple_tag(takes_context=True)
def product_seo_image_url(context, product=None, merchant_data=None, gallery_images=None):
    """
    FINAL product image fallback for SEO.

    Template use:
    {% product_seo_image_url product merchant_data gallery_images as product_final_seo_image_url %}

    It searches:
    1. Product image/file fields
    2. Product image helper methods
    3. Merchant/feed metadata
    4. gallery_images passed by the view
    5. Known related managers
    6. Every reverse related object on the Product model

    It skips Arolana/settings logo paths and returns a clean permanent /media/ URL.
    """
    request = context.get("request")
    seen_names = set()

    for candidate in _product_image_candidates(product, merchant_data, gallery_images):
        name = _clean_file_name(candidate)

        if not name:
            continue

        if name in seen_names:
            continue

        seen_names.add(name)

        if _looks_like_site_logo(name):
            continue

        if not _looks_like_public_image(name):
            continue

        optimized_url = get_verified_optimized_image_url(candidate, "seo")
        optimized_name = _clean_file_name(optimized_url) or name
        return _build_public_media_url(optimized_name, request=request)

    return ""


def _product_image_candidates(product=None, merchant_data=None, gallery_images=None):
    # 1. Direct product fields and FileField/ImageField fields.
    if product:
        yield from _yield_named_image_fields(product)
        yield from _yield_model_file_fields(product)

        for method_name in (
            "get_main_image",
            "get_primary_image",
            "get_default_image",
            "get_thumbnail",
            "primary_media",
            "main_media",
            "get_first_image",
            "get_image",
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
    yield from _yield_named_image_fields(merchant_data)

    # 3. View gallery context.
    yield from _yield_images_from_collection(gallery_images)

    # 4. Known related managers on product.
    if product:
        for related_name in PRODUCT_RELATED_NAMES:
            related = _safe_getattr(product, related_name)

            if not related:
                continue

            yield from _yield_manager_or_collection(related)

    # 5. Every reverse relation from the Product model.
    if product:
        yield from _yield_reverse_related_images(product)


def _yield_named_image_fields(obj):
    if not obj:
        return

    for key in IMAGE_FIELD_NAMES:
        value = _extract_from_mapping_or_object(obj, key)

        if value:
            yield value


def _yield_model_file_fields(obj):
    meta = _safe_getattr(obj, "_meta")

    if not meta:
        return

    try:
        fields = meta.get_fields()
    except Exception:
        return

    for field in fields:
        field_name = getattr(field, "name", "")

        if not field_name:
            continue

        # FileField/ImageField have upload_to.
        if not hasattr(field, "upload_to"):
            continue

        value = _safe_getattr(obj, field_name)

        if value:
            yield value


def _yield_reverse_related_images(product):
    meta = _safe_getattr(product, "_meta")

    if not meta:
        return

    try:
        related_objects = meta.related_objects
    except Exception:
        return

    for relation in related_objects:
        try:
            accessor_name = relation.get_accessor_name()
        except Exception:
            accessor_name = ""

        if not accessor_name:
            continue

        manager = _safe_getattr(product, accessor_name)

        if not manager:
            continue

        yield from _yield_manager_or_collection(manager)


def _yield_manager_or_collection(value):
    try:
        collection = value.all()
    except Exception:
        collection = value

    yield from _yield_images_from_collection(collection)


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

        yield from _yield_named_image_fields(item)
        yield from _yield_model_file_fields(item)

        # One nested level for variant/media objects.
        for related_name in ("images", "gallery_images", "variant_images", "media", "photos"):
            nested = _safe_getattr(item, related_name)

            if not nested:
                continue

            yield from _yield_manager_or_collection(nested)


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


def _looks_like_public_image(name):
    lowered = str(name or "").lower().split("?", 1)[0]

    return lowered.endswith((
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
        ".gif",
        ".avif",
        ".svg",
    ))
