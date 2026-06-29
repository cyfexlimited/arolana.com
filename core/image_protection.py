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
from django.db.models import ImageField
from django.utils import timezone
from django.utils.deconstruct import deconstructible

from core.models import ProtectedImageAsset

try:
    from PIL import Image, ImageOps
except Exception:
    Image = None
    ImageOps = None


IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".avif")


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


def _object_vendor_key(obj):
    product = getattr(obj, "product", None)
    variant = getattr(obj, "variant", None)
    if variant is not None:
        product = getattr(variant, "product", None)

    if product is not None:
        vendor = getattr(product, "vendor", None)
        return f"user:{getattr(vendor, 'pk', '')}" if vendor else ""

    vendor = getattr(obj, "vendor", None)
    if vendor is not None:
        return f"user:{getattr(vendor, 'pk', '')}"

    user = getattr(obj, "user", None)
    if user is not None:
        return f"user:{getattr(user, 'pk', '')}"

    return ""


def _asset_vendor_key(asset):
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


def protect_uploaded_image(instance, field_name, block_cross_vendor_duplicates=True):
    image_file = getattr(instance, field_name, None)
    if not _is_new_upload(image_file):
        return None

    try:
        image_file.seek(0)
    except Exception:
        pass

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
    return ImageFingerprint(
        file_name=protected_name,
        sha256=sha256,
        perceptual_hash=perceptual_hash,
        width=width,
        height=height,
        size_bytes=len(webp_data),
    )


def record_protected_image(instance, field_name):
    image_file = getattr(instance, field_name, None)
    file_name = clean_storage_name(getattr(image_file, "name", ""))
    if not file_name:
        return None
    fingerprint = fingerprint_image(image_file, file_name)
    if not fingerprint:
        return None
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

    exact_duplicate = (
        ProtectedImageAsset.objects
        .filter(sha256=fingerprint.sha256)
        .exclude(content_type=content_type, object_id=obj.pk, field_name=field.name, file_name=fingerprint.file_name)
        .order_by("created_at")
        .first()
    )

    is_duplicate = exact_duplicate is not None

    asset, _created = ProtectedImageAsset.objects.update_or_create(
        content_type=content_type,
        object_id=obj.pk,
        field_name=field.name,
        file_name=fingerprint.file_name,
        defaults={
            "sha256": fingerprint.sha256,
            "perceptual_hash": fingerprint.perceptual_hash,
            "width": fingerprint.width,
            "height": fingerprint.height,
            "size_bytes": fingerprint.size_bytes,
            "is_duplicate": is_duplicate,
            "duplicate_of": exact_duplicate,
        },
    )
    return asset, is_duplicate, exact_duplicate


def group_exact_duplicates(assets: Iterable[ProtectedImageAsset]):
    groups = {}
    for asset in assets:
        groups.setdefault(asset.sha256, []).append(asset)
    return {key: value for key, value in groups.items() if len(value) > 1}
