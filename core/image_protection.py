import hashlib
import uuid
from dataclasses import dataclass
from io import BytesIO
from typing import Iterable

from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db.models import ImageField, Q
from django.utils import timezone
from django.utils.deconstruct import deconstructible

from core.models import ProtectedImageAsset

try:
    from PIL import Image, ImageOps
except Exception:
    Image = None
    ImageOps = None


IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".avif")
EXACT_CROSS_VENDOR_MESSAGE = (
    "This image is already used by another vendor on Arolana. Upload a different "
    "image or contact Arolana support if you have permission to use it."
)
NEAR_CROSS_VENDOR_MESSAGE = (
    "This image looks similar to an image already used by another vendor. "
    "It has been submitted for review."
)


@deconstructible
class ProtectedImageUploadPath:
    """UUID WebP upload path that does not expose customer/vendor filenames."""

    def __init__(self, prefix):
        self.prefix = str(prefix or "uploads").strip("/")

    def __call__(self, instance, filename):
        today = timezone.now()
        return f"{self.prefix}/{today:%Y/%m}/{uuid.uuid4().hex}.webp"


@dataclass
class ImageFingerprint:
    file_name: str
    sha256: str
    original_filename: str = ""
    perceptual_hash: str = ""
    width: int | None = None
    height: int | None = None
    size_bytes: int | None = None


def clean_storage_name(name):
    name = str(name or "").split("?", 1)[0].strip().lstrip("/")
    if name.startswith("media/"):
        name = name[len("media/"):]
    return name


def _is_new_upload(image_file):
    return bool(image_file and not getattr(image_file, "_committed", True))


def _object_ownership(obj):
    product = getattr(obj, "product", None)
    variant = getattr(obj, "variant", None)
    if variant is not None:
        product = getattr(variant, "product", None)
    if obj._meta.label_lower == "products.product":
        product = obj

    if product is not None:
        vendor = getattr(product, "vendor", None)
        return vendor, getattr(product, "pk", None)

    vendor = getattr(obj, "vendor", None)
    if vendor is not None:
        return vendor, None

    user = getattr(obj, "user", None)
    if user is not None:
        return user, None

    return None, None


def _object_vendor_key(obj):
    vendor, _product_id = _object_ownership(obj)
    return f"user:{getattr(vendor, 'pk', '')}" if vendor else ""


def _asset_vendor_key(asset):
    if getattr(asset, "vendor_id", None):
        return f"user:{asset.vendor_id}"
    try:
        obj = asset.content_type.get_object_for_this_type(pk=asset.object_id)
    except Exception:
        return ""
    return _object_vendor_key(obj)


def _sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def _webp_bytes_and_metadata(data):
    if Image is None or ImageOps is None:
        raise ValidationError("Image protection requires Pillow to process uploads.")

    with Image.open(BytesIO(data)) as img:
        if getattr(img, "is_animated", False) or getattr(img, "n_frames", 1) > 1:
            raise ValidationError("Animated images are not supported for protected product uploads.")

        img = ImageOps.exif_transpose(img)
        width, height = img.size
        perceptual_hash = average_hash(img)
        has_alpha = img.mode in ("RGBA", "LA") or "transparency" in img.info
        img = img.convert("RGBA" if has_alpha else "RGB")

        output = BytesIO()
        img.save(output, format="WEBP", quality=88, method=6, optimize=True)

    return output.getvalue(), width, height, perceptual_hash


def _matched_asset_payload(asset, match_type, perceptual_distance=None):
    product_name = ""
    if getattr(asset, "source_product_id", None):
        try:
            Product = apps.get_model("products", "Product")
            product_name = (
                Product.objects.filter(pk=asset.source_product_id)
                .values_list("name", flat=True)
                .first()
                or ""
            )
        except Exception:
            product_name = ""
    vendor = getattr(asset, "vendor", None)
    vendor_name = ""
    if vendor:
        profile = getattr(vendor, "vendor_profile", None)
        vendor_name = (
            getattr(profile, "business_name", "")
            or getattr(profile, "store_name", "")
            or vendor.get_full_name()
            or vendor.email
            or vendor.username
        )
    return {
        "matched_asset_id": asset.pk,
        "match_type": match_type,
        "first_vendor_id": getattr(asset, "vendor_id", None),
        "first_vendor_name": vendor_name,
        "first_product_id": getattr(asset, "source_product_id", None),
        "first_product_name": product_name,
        "first_uploaded_at": asset.created_at.isoformat() if asset.created_at else "",
        "perceptual_distance": perceptual_distance,
    }


def inspect_vendor_image_upload(image_file, vendor):
    """
    Inspect a vendor upload before its model is saved.

    Exact cross-vendor matches are blocked before storage. Near matches may be
    stored only on an inactive product awaiting admin review. Same-vendor reuse
    remains allowed.
    """
    if not image_file:
        return {"status": "original", "allowed": True}
    try:
        image_file.seek(0)
        raw = image_file.read()
    finally:
        try:
            image_file.seek(0)
        except Exception:
            pass
    if not raw:
        return {"status": "original", "allowed": True}

    webp_data, width, height, perceptual_hash = _webp_bytes_and_metadata(raw)
    sha256 = _sha256_bytes(webp_data)
    vendor_id = getattr(vendor, "pk", None)
    exact = ProtectedImageAsset.objects.filter(sha256=sha256).order_by("created_at").first()
    if exact:
        payload = _matched_asset_payload(exact, "exact", 0)
        if vendor_id and exact.vendor_id == vendor_id:
            return {
                **payload,
                "status": "same_vendor_reuse",
                "allowed": True,
                "message": "Image already used by this same vendor. Reuse allowed.",
            }
        if exact.allow_duplicate:
            return {
                **payload,
                "status": "admin_override",
                "allowed": True,
                "message": "This image is approved by Arolana for authorized shared use.",
            }
        return {
            **payload,
            "status": "exact_duplicate_cross_vendor",
            "allowed": False,
            "message": EXACT_CROSS_VENDOR_MESSAGE,
        }

    if perceptual_hash:
        minimum_width = max(1, int((width or 1) * 0.45))
        maximum_width = max(1, int((width or 1) * 2.2))
        minimum_height = max(1, int((height or 1) * 0.45))
        maximum_height = max(1, int((height or 1) * 2.2))
        candidates = (
            ProtectedImageAsset.objects.exclude(perceptual_hash="")
            .filter(
                Q(width__isnull=True)
                | Q(height__isnull=True)
                | Q(
                    width__gte=minimum_width,
                    width__lte=maximum_width,
                    height__gte=minimum_height,
                    height__lte=maximum_height,
                )
            )
            .order_by("created_at")[:500]
        )
        for candidate in candidates:
            distance = hamming_distance(perceptual_hash, candidate.perceptual_hash)
            if distance is None or distance > 6:
                continue
            payload = _matched_asset_payload(candidate, "near", distance)
            if vendor_id and candidate.vendor_id == vendor_id:
                return {
                    **payload,
                    "status": "same_vendor_reuse",
                    "allowed": True,
                    "message": "Image already used by this same vendor. Reuse allowed.",
                }
            if candidate.allow_duplicate:
                return {
                    **payload,
                    "status": "admin_override",
                    "allowed": True,
                    "message": "This image is approved by Arolana for authorized shared use.",
                }
            return {
                **payload,
                "status": "near_duplicate_cross_vendor",
                "allowed": True,
                "pending_review": True,
                "message": NEAR_CROSS_VENDOR_MESSAGE,
            }

    return {"status": "original", "allowed": True}


def protect_uploaded_image(instance, field_name, block_cross_vendor_duplicates=False):
    image_file = getattr(instance, field_name, None)
    if not _is_new_upload(image_file):
        return None

    try:
        image_file.seek(0)
    except Exception:
        pass

    original_filename = str(getattr(image_file, "name", "") or "")
    raw = image_file.read()
    if not raw:
        return None

    webp_data, width, height, perceptual_hash = _webp_bytes_and_metadata(raw)
    sha256 = _sha256_bytes(webp_data)

    duplicate = ProtectedImageAsset.objects.filter(sha256=sha256).order_by("created_at").first()
    if duplicate and block_cross_vendor_duplicates and not duplicate.allow_duplicate:
        current_vendor = _object_vendor_key(instance)
        duplicate_vendor = _asset_vendor_key(duplicate)
        if current_vendor and duplicate_vendor and current_vendor != duplicate_vendor:
            raise ValidationError(
                {
                    field_name: (
                        "This image appears to already belong to another vendor. "
                        "Ask admin to approve a legitimate duplicate before using it."
                    )
                }
            )

    protected_name = f"{uuid.uuid4().hex}.webp"
    setattr(instance, field_name, ContentFile(webp_data, name=protected_name))
    fingerprint = ImageFingerprint(
        file_name=protected_name,
        sha256=sha256,
        original_filename=original_filename,
        perceptual_hash=perceptual_hash,
        width=width,
        height=height,
        size_bytes=len(webp_data),
    )
    upload_context = getattr(instance, "_protected_image_upload_context", {})
    upload_context[field_name] = fingerprint
    instance._protected_image_upload_context = upload_context
    return fingerprint


def record_protected_image(instance, field_name):
    image_file = getattr(instance, field_name, None)
    file_name = clean_storage_name(getattr(image_file, "name", ""))
    if not file_name:
        return None
    upload_context = getattr(instance, "_protected_image_upload_context", {})
    fingerprint = upload_context.get(field_name) or fingerprint_image(image_file, file_name)
    if not fingerprint:
        return None
    fingerprint.file_name = file_name
    asset, _is_duplicate, _duplicate_of = upsert_protected_asset(instance, instance._meta.get_field(field_name), fingerprint)
    return asset


def iter_model_image_fields(model_filter: set[str] | None = None):
    for model in apps.get_models():
        if model_filter and model._meta.label not in model_filter:
            continue
        for field in model._meta.fields:
            if isinstance(field, ImageField):
                yield model, field


def iter_image_objects(model_filter: set[str] | None = None, limit=0):
    for model, field in iter_model_image_fields(model_filter):
        qs = model.objects.all().only("pk", field.name)
        if limit:
            qs = qs[:limit]
        for obj in qs.iterator(chunk_size=100):
            image_file = getattr(obj, field.name, None)
            file_name = clean_storage_name(getattr(image_file, "name", ""))
            if not file_name or not file_name.lower().endswith(IMAGE_EXTENSIONS):
                continue
            yield obj, field, image_file, file_name


def fingerprint_image(image_file, file_name=None):
    file_name = clean_storage_name(file_name or getattr(image_file, "name", ""))
    if not file_name:
        return None

    storage = getattr(image_file, "storage", None) or default_storage

    try:
        with storage.open(file_name, "rb") as source:
            data = source.read()
    except Exception:
        return None

    sha256 = hashlib.sha256(data).hexdigest()
    width = height = None
    perceptual_hash = ""

    if Image is not None and ImageOps is not None:
        try:
            from io import BytesIO

            with Image.open(BytesIO(data)) as img:
                img = ImageOps.exif_transpose(img)
                width, height = img.size
                perceptual_hash = average_hash(img)
        except Exception:
            perceptual_hash = ""

    return ImageFingerprint(
        file_name=file_name,
        sha256=sha256,
        original_filename=file_name.rsplit("/", 1)[-1],
        perceptual_hash=perceptual_hash,
        width=width,
        height=height,
        size_bytes=len(data),
    )


def average_hash(img, hash_size=8):
    img = img.convert("L").resize((hash_size, hash_size))
    pixels = list(img.getdata())
    avg = sum(pixels) / len(pixels)
    bits = ["1" if pixel >= avg else "0" for pixel in pixels]
    return f"{int(''.join(bits), 2):0{hash_size * hash_size // 4}x}"


def hamming_distance(left, right):
    if not left or not right:
        return None
    try:
        return bin(int(left, 16) ^ int(right, 16)).count("1")
    except Exception:
        return None


def upsert_protected_asset(obj, field, fingerprint: ImageFingerprint, dry_run=False):
    if dry_run:
        return None, False, None

    content_type = ContentType.objects.get_for_model(obj.__class__)

    duplicate_of = (
        ProtectedImageAsset.objects
        .filter(sha256=fingerprint.sha256)
        .exclude(content_type=content_type, object_id=obj.pk, field_name=field.name, file_name=fingerprint.file_name)
        .order_by("created_at")
        .first()
    )
    duplicate_type = "exact" if duplicate_of else ""
    perceptual_distance = 0 if duplicate_of else None

    if duplicate_of is None and fingerprint.perceptual_hash:
        minimum_width = max(1, int((fingerprint.width or 1) * 0.45))
        maximum_width = max(1, int((fingerprint.width or 1) * 2.2))
        minimum_height = max(1, int((fingerprint.height or 1) * 0.45))
        maximum_height = max(1, int((fingerprint.height or 1) * 2.2))
        candidates = (
            ProtectedImageAsset.objects
            .exclude(perceptual_hash="")
            .exclude(
                content_type=content_type,
                object_id=obj.pk,
                field_name=field.name,
                file_name=fingerprint.file_name,
            )
            .filter(
                Q(width__isnull=True)
                | Q(height__isnull=True)
                | Q(
                    width__gte=minimum_width,
                    width__lte=maximum_width,
                    height__gte=minimum_height,
                    height__lte=maximum_height,
                )
            )
            .order_by("created_at")[:500]
        )
        for candidate in candidates:
            distance = hamming_distance(
                fingerprint.perceptual_hash,
                candidate.perceptual_hash,
            )
            if distance is not None and distance <= 6:
                duplicate_of = candidate
                duplicate_type = "near"
                perceptual_distance = distance
                break

    is_duplicate = duplicate_of is not None
    vendor, source_product_id = _object_ownership(obj)
    current_vendor_key = f"user:{getattr(vendor, 'pk', '')}" if vendor else ""
    duplicate_vendor_key = _asset_vendor_key(duplicate_of) if duplicate_of else ""
    same_vendor = bool(
        is_duplicate
        and current_vendor_key
        and duplicate_vendor_key
        and current_vendor_key == duplicate_vendor_key
    )

    if not is_duplicate:
        duplicate_status = "original"
        duplicate_reason = ""
    elif same_vendor:
        duplicate_status = "same_vendor_reuse"
        duplicate_reason = "Image reused by the same vendor."
    elif getattr(duplicate_of, "allow_duplicate", False):
        duplicate_status = "admin_override"
        duplicate_reason = "Matched an image already approved for legitimate shared use."
    elif duplicate_type == "exact":
        duplicate_status = "exact_duplicate_cross_vendor"
        duplicate_reason = EXACT_CROSS_VENDOR_MESSAGE
    elif duplicate_type == "near":
        duplicate_status = "near_duplicate_cross_vendor"
        duplicate_reason = NEAR_CROSS_VENDOR_MESSAGE
    else:
        duplicate_status = "needs_review"
        duplicate_reason = (
            "This image appears to already be used by another vendor on Arolana. "
            "Please confirm that you have the right to use it or upload your own original product image."
        )

    asset, _created = ProtectedImageAsset.objects.update_or_create(
        content_type=content_type,
        object_id=obj.pk,
        field_name=field.name,
        file_name=fingerprint.file_name,
        defaults={
            "sha256": fingerprint.sha256,
            "original_filename": fingerprint.original_filename,
            "perceptual_hash": fingerprint.perceptual_hash,
            "width": fingerprint.width,
            "height": fingerprint.height,
            "size_bytes": fingerprint.size_bytes,
            "is_duplicate": is_duplicate,
            "duplicate_type": duplicate_type,
            "duplicate_status": duplicate_status,
            "perceptual_distance": perceptual_distance,
            "duplicate_of": duplicate_of,
            "duplicate_reason": duplicate_reason,
            "uploader": vendor,
            "vendor": vendor,
            "source_product_id": source_product_id,
        },
    )
    return asset, is_duplicate, duplicate_of


def protected_asset_for(instance, field_name):
    if not instance or not getattr(instance, "pk", None):
        return None
    image_file = getattr(instance, field_name, None)
    file_name = clean_storage_name(getattr(image_file, "name", ""))
    if not file_name:
        return None
    content_type = ContentType.objects.get_for_model(instance.__class__)
    return ProtectedImageAsset.objects.filter(
        content_type=content_type,
        object_id=instance.pk,
        field_name=field_name,
        file_name=file_name,
    ).first()


def set_protected_image_uploader(instance, field_name, uploader):
    if not uploader:
        return protected_asset_for(instance, field_name)
    asset = protected_asset_for(instance, field_name)
    if asset and asset.uploader_id != getattr(uploader, "pk", None):
        asset.uploader = uploader
        asset.save(update_fields=["uploader", "updated_at"])
    return asset


def duplicate_warning_payload(instance, field_name):
    asset = protected_asset_for(instance, field_name)
    if not asset:
        return None
    matched = (
        _matched_asset_payload(
            asset.duplicate_of,
            asset.duplicate_type,
            asset.perceptual_distance,
        )
        if asset.duplicate_of_id
        else {}
    )
    return {
        **matched,
        "asset_id": asset.id,
        "is_duplicate": asset.is_duplicate,
        "duplicate_type": asset.duplicate_type,
        "duplicate_status": asset.duplicate_status,
        "needs_review": asset.duplicate_status in {
            "needs_review",
            "exact_duplicate_cross_vendor",
            "near_duplicate_cross_vendor",
        },
        "same_vendor_reuse": asset.duplicate_status == "same_vendor_reuse",
        "message": asset.duplicate_reason,
        "matched_asset_id": asset.duplicate_of_id,
        "perceptual_distance": asset.perceptual_distance,
    }


def group_exact_duplicates(assets: Iterable[ProtectedImageAsset]):
    groups = {}
    for asset in assets:
        groups.setdefault(asset.sha256, []).append(asset)
    return {key: value for key, value in groups.items() if len(value) > 1}
