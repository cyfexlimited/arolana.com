from io import BytesIO
from pathlib import PurePosixPath

from django.apps import apps
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand
from django.db.models import ImageField
from PIL import Image, ImageOps, UnidentifiedImageError


PRESETS = {
    "seo": (1200, 1200),
    "thumbnail": (300, 300),
    "avatar": (240, 240),
    "logo": (500, 220),

    "product_thumb": (180, 180),
    "product_card": (640, 640),
    "product_detail": (1200, 1200),

    "accessory_thumb": (300, 300),
    "category_card": (720, 540),

    "banner": (1200, 500),
    "ad_card": (720, 360),

    "homepage_hero": (1920, 1080),
    "landing_hero": (1600, 900),
    "background_desktop": (1920, 1080),
    "background_mobile": (1080, 1350),
    "mobile_hero": (1080, 1350),

    "blog_card": (720, 480),
    "video_thumb": (720, 405),
}

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".avif", ".bmp", ".tif", ".tiff")
SKIP_EXTENSIONS = (".svg", ".gif", ".ico")


class Command(BaseCommand):
    help = "Generate optimized WebP copies for every ImageField in Arolana."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--overwrite", action="store_true")
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--quality", type=int, default=82)
        parser.add_argument("--model", action="append", default=[])

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        overwrite = options["overwrite"]
        limit = options["limit"]
        quality = max(1, min(int(options["quality"]), 95))
        model_filter = set(options["model"] or [])

        total_rows = 0
        total_images = 0
        total_created = 0
        total_skipped = 0
        total_errors = 0

        self.stdout.write(self.style.MIGRATE_HEADING("Arolana global media optimizer"))
        self.stdout.write(f"Dry run: {dry_run}")
        self.stdout.write(f"Overwrite: {overwrite}")
        self.stdout.write(f"Quality: {quality}")

        for model in apps.get_models():
            model_label = model._meta.label

            if model_filter and model_label not in model_filter:
                continue

            image_fields = [
                field for field in model._meta.fields
                if isinstance(field, ImageField)
            ]

            if not image_fields:
                continue

            for field in image_fields:
                field_name = field.name
                qs = model.objects.all().only("pk", field_name)

                if limit:
                    qs = qs[:limit]

                self.stdout.write("")
                self.stdout.write(self.style.HTTP_INFO(f"{model_label}.{field_name}"))

                for obj in qs.iterator(chunk_size=100):
                    total_rows += 1

                    image_file = getattr(obj, field_name, None)
                    image_name = clean_name(getattr(image_file, "name", "") or "")

                    if not image_name:
                        continue

                    total_images += 1

                    presets = choose_presets(model_label, field_name, image_name)

                    created, skipped, errors = optimize_image(
                        image_name=image_name,
                        presets=presets,
                        dry_run=dry_run,
                        overwrite=overwrite,
                        quality=quality,
                        stdout=self.stdout,
                        style=self.style,
                    )

                    total_created += created
                    total_skipped += skipped
                    total_errors += errors

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Done."))
        self.stdout.write(f"Rows scanned: {total_rows}")
        self.stdout.write(f"Image references found: {total_images}")
        self.stdout.write(f"Optimized files created/planned: {total_created}")
        self.stdout.write(f"Skipped: {total_skipped}")
        self.stdout.write(f"Errors: {total_errors}")


def optimize_image(image_name, presets, dry_run=False, overwrite=False, quality=82, stdout=None, style=None):
    created = 0
    skipped = 0
    errors = 0

    image_name = clean_name(image_name)
    lowered = image_name.lower()

    if not image_name or image_name.startswith("optimized/"):
        return 0, 1, 0

    if lowered.endswith(SKIP_EXTENSIONS):
        return 0, 1, 0

    if not lowered.endswith(IMAGE_EXTENSIONS):
        return 0, 1, 0

    try:
        source_exists = default_storage.exists(image_name)
    except Exception as exc:
        write(stdout, style, f"ERROR checking {image_name}: {exc}", error=True)
        return 0, 0, 1

    if not source_exists:
        write(stdout, style, f"MISSING source: {image_name}", warning=True)
        return 0, len(presets), 0

    try:
        with default_storage.open(image_name, "rb") as source:
            img = Image.open(source)
            img = ImageOps.exif_transpose(img)
            img.load()
    except UnidentifiedImageError as exc:
        write(stdout, style, f"ERROR not image {image_name}: {exc}", error=True)
        return 0, 0, 1
    except Exception as exc:
        write(stdout, style, f"ERROR opening {image_name}: {exc}", error=True)
        return 0, 0, 1

    for preset in presets:
        size = PRESETS.get(preset)

        if not size:
            skipped += 1
            continue

        dst = optimized_name(image_name, preset)

        try:
            dst_exists = default_storage.exists(dst)
        except Exception:
            dst_exists = False

        if dst_exists and not overwrite:
            skipped += 1
            continue

        if dry_run:
            created += 1
            write(stdout, style, f"PLAN {preset}: {image_name} -> {dst}")
            continue

        try:
            out_img = img.copy()

            if out_img.mode not in ("RGB", "RGBA"):
                out_img = out_img.convert("RGBA" if "A" in out_img.getbands() else "RGB")

            out_img.thumbnail(size, Image.Resampling.LANCZOS)

            output = BytesIO()
            out_img.save(output, format="WEBP", quality=quality, method=6)

            if dst_exists and overwrite:
                try:
                    default_storage.delete(dst)
                except Exception:
                    pass

            default_storage.save(dst, ContentFile(output.getvalue()))
            created += 1
            write(stdout, style, f"OK {preset}: {dst} ({len(output.getvalue())} bytes)", success=True)

        except Exception as exc:
            errors += 1
            write(stdout, style, f"ERROR optimizing {image_name} as {preset}: {exc}", error=True)

    return created, skipped, errors


def clean_name(name):
    name = str(name or "").split("?", 1)[0].strip().lstrip("/")

    if name.startswith("media/"):
        name = name[len("media/"):]

    return name


def optimized_name(original_name, preset):
    original_name = clean_name(original_name)
    path = PurePosixPath(original_name)
    return str(PurePosixPath("optimized") / preset / path.with_suffix(".webp"))


def choose_presets(model_label, field_name, image_name):
    text = f"{model_label}.{field_name} {image_name}".lower()
    presets = []

    def add(*items):
        for item in items:
            if item not in presets:
                presets.append(item)

    if "products.product.main_image" in text:
        add("seo", "product_detail", "product_card", "product_thumb")
    elif "productimage" in text or "products/gallery" in text:
        add("product_detail", "product_card", "product_thumb", "seo")
    elif "variant" in text and "image" in text:
        add("product_detail", "product_card", "product_thumb")
    elif "accessory" in text:
        add("accessory_thumb", "product_card", "thumbnail")
    elif "category" in text:
        add("category_card", "seo", "thumbnail")
    elif "logo" in text:
        add("logo", "thumbnail", "seo")
    elif "banner" in text:
        add("banner", "seo")
    elif "background" in text and "mobile" in text:
        add("background_mobile", "seo")
    elif "background" in text:
        add("background_desktop", "seo")
    elif "hero_mobile" in text or "image_mobile" in text:
        add("mobile_hero", "seo")
    elif "hero" in text:
        add("landing_hero", "homepage_hero", "seo")
    elif "homepage" in text:
        add("homepage_hero", "banner", "seo")
    elif "landing_pages" in text:
        add("landing_hero", "banner", "seo", "thumbnail")
    elif "ads." in text or "advertisement" in text or "promo" in text:
        add("ad_card", "banner", "seo")
    elif "blog" in text:
        add("blog_card", "seo", "thumbnail")
    elif "thumbnail" in text or "thumb" in text or "poster" in text:
        add("video_thumb", "thumbnail", "seo")
    elif "avatar" in text or "profile" in text or "photo" in text:
        add("avatar", "thumbnail")
    else:
        add("seo", "thumbnail")

    return presets


def write(stdout, style, message, success=False, warning=False, error=False):
    if not stdout:
        return

    if error and style:
        stdout.write(style.ERROR(message))
    elif warning and style:
        stdout.write(style.WARNING(message))
    elif success and style:
        stdout.write(style.SUCCESS(message))
    else:
        stdout.write(message)
