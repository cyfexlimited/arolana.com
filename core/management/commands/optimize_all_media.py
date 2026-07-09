from io import BytesIO

from django.apps import apps
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand
from django.db.models import ImageField
from PIL import Image, ImageFilter, ImageOps, UnidentifiedImageError

from core.media_optimization import PRESETS, optimized_name_for


IMAGE_EXTENSIONS = (
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".avif",
    ".bmp",
    ".tif",
    ".tiff",
)

SKIP_EXTENSIONS = (
    ".svg",
    ".gif",
    ".ico",
)


class Command(BaseCommand):
    help = "Generate optimized WebP copies for every ImageField in Arolana."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
        )

        parser.add_argument(
            "--overwrite",
            action="store_true",
        )

        parser.add_argument(
            "--limit",
            type=int,
            default=0,
        )

        parser.add_argument(
            "--quality",
            type=int,
            default=95,
            help=(
                "Maximum quality cap. "
                "Preset quality remains authoritative."
            ),
        )

        parser.add_argument(
            "--model",
            action="append",
            default=[],
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        overwrite = options["overwrite"]
        limit = options["limit"]

        quality = max(
            1,
            min(
                int(options["quality"]),
                95,
            ),
        )

        model_filter = set(
            options["model"] or []
        )

        total_rows = 0
        total_images = 0
        total_created = 0
        total_skipped = 0
        total_errors = 0

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Arolana global media optimizer"
            )
        )

        self.stdout.write(
            f"Dry run: {dry_run}"
        )

        self.stdout.write(
            f"Overwrite: {overwrite}"
        )

        self.stdout.write(
            f"Quality: {quality}"
        )

        for model in apps.get_models():
            model_label = model._meta.label

            if (
                model_filter
                and model_label not in model_filter
            ):
                continue

            image_fields = [
                field
                for field in model._meta.fields
                if isinstance(field, ImageField)
            ]

            if not image_fields:
                continue

            for field in image_fields:
                field_name = field.name

                qs = model.objects.all().only(
                    "pk",
                    field_name,
                )

                if limit:
                    qs = qs[:limit]

                self.stdout.write("")

                self.stdout.write(
                    self.style.HTTP_INFO(
                        f"{model_label}.{field_name}"
                    )
                )

                for obj in qs.iterator(
                    chunk_size=100
                ):
                    total_rows += 1

                    image_file = getattr(
                        obj,
                        field_name,
                        None,
                    )

                    image_name = clean_name(
                        getattr(
                            image_file,
                            "name",
                            "",
                        )
                        or ""
                    )

                    if not image_name:
                        continue

                    total_images += 1

                    presets = choose_presets(
                        model_label,
                        field_name,
                        image_name,
                    )

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

        self.stdout.write(
            self.style.SUCCESS(
                "Done."
            )
        )

        self.stdout.write(
            f"Rows scanned: {total_rows}"
        )

        self.stdout.write(
            f"Image references found: {total_images}"
        )

        self.stdout.write(
            "Optimized files created/planned: "
            f"{total_created}"
        )

        self.stdout.write(
            f"Skipped: {total_skipped}"
        )

        self.stdout.write(
            f"Errors: {total_errors}"
        )


def optimize_image(
    image_name,
    presets,
    dry_run=False,
    overwrite=False,
    quality=82,
    stdout=None,
    style=None,
):
    created = 0
    skipped = 0
    errors = 0

    image_name = clean_name(
        image_name
    )

    lowered = image_name.lower()

    if (
        not image_name
        or image_name.startswith("optimized/")
    ):
        return 0, 1, 0

    if lowered.endswith(
        SKIP_EXTENSIONS
    ):
        return 0, 1, 0

    if not lowered.endswith(
        IMAGE_EXTENSIONS
    ):
        return 0, 1, 0

    try:
        source_exists = default_storage.exists(
            image_name
        )

    except Exception as exc:
        write(
            stdout,
            style,
            f"ERROR checking {image_name}: {exc}",
            error=True,
        )

        return 0, 0, 1

    if not source_exists:
        write(
            stdout,
            style,
            f"MISSING source: {image_name}",
            warning=True,
        )

        return 0, len(presets), 0

    try:
        with default_storage.open(
            image_name,
            "rb",
        ) as source:
            img = Image.open(
                source
            )

            img = ImageOps.exif_transpose(
                img
            )

            img.load()

    except UnidentifiedImageError as exc:
        write(
            stdout,
            style,
            f"ERROR not image {image_name}: {exc}",
            error=True,
        )

        return 0, 0, 1

    except Exception as exc:
        write(
            stdout,
            style,
            f"ERROR opening {image_name}: {exc}",
            error=True,
        )

        return 0, 0, 1

    for preset in presets:
        config = PRESETS.get(
            preset
        )

        if not config:
            skipped += 1

            write(
                stdout,
                style,
                (
                    f"SKIP unknown preset "
                    f"{preset}: {image_name}"
                ),
                warning=True,
            )

            continue

        dst = optimized_name_for(
            image_name,
            preset,
        )

        if not dst:
            skipped += 1
            continue

        try:
            dst_exists = default_storage.exists(
                dst
            )

        except Exception:
            dst_exists = False

        if (
            dst_exists
            and not overwrite
        ):
            skipped += 1
            continue

        if dry_run:
            created += 1

            write(
                stdout,
                style,
                (
                    f"PLAN {preset}: "
                    f"{image_name} -> {dst}"
                ),
            )

            continue

        try:
            out_img = img.copy()

            if out_img.mode not in (
                "RGB",
                "RGBA",
            ):
                out_img = out_img.convert(
                    (
                        "RGBA"
                        if "A" in out_img.getbands()
                        else "RGB"
                    )
                )

            out_img.thumbnail(
                config["max_size"],
                Image.Resampling.LANCZOS,
            )

            if config.get("sharpen"):
                out_img = out_img.filter(
                    ImageFilter.UnsharpMask(
                        radius=0.8,
                        percent=115,
                        threshold=3,
                    )
                )

            output = BytesIO()

            out_img.save(
                output,
                format="WEBP",
                quality=min(
                    quality,
                    config["quality"],
                ),
                method=6,
                optimize=True,
            )

            output_bytes = output.getvalue()

            if (
                dst_exists
                and overwrite
            ):
                try:
                    default_storage.delete(
                        dst
                    )
                except Exception:
                    pass

            saved_name = default_storage.save(
                dst,
                ContentFile(
                    output_bytes
                ),
            )

            if saved_name != dst:
                write(
                    stdout,
                    style,
                    (
                        "WARNING storage saved derivative "
                        f"under unexpected name: "
                        f"{saved_name}; expected: {dst}"
                    ),
                    warning=True,
                )

            created += 1

            write(
                stdout,
                style,
                (
                    f"OK {preset}: "
                    f"{saved_name} "
                    f"({len(output_bytes)} bytes)"
                ),
                success=True,
            )

        except Exception as exc:
            errors += 1

            write(
                stdout,
                style,
                (
                    f"ERROR optimizing "
                    f"{image_name} "
                    f"as {preset}: {exc}"
                ),
                error=True,
            )

    return created, skipped, errors


def clean_name(name):
    name = (
        str(name or "")
        .split("?", 1)[0]
        .strip()
        .lstrip("/")
    )

    if name.startswith("media/"):
        name = name[
            len("media/"):
        ]

    return name


def choose_presets(
    model_label,
    field_name,
    image_name,
):
    """
    Choose all frontend image presets required for a model ImageField.

    Important:
    Specific model/field rules must remain above generic checks such as
    'thumbnail', 'banner', 'profile', and 'hero'. Otherwise the generic
    rule can intercept the image before its marketplace-specific presets
    are selected.
    """

    text = (
        f"{model_label}.{field_name} "
        f"{image_name}"
    ).lower()

    presets = []

    def add(*items):
        for item in items:
            if item not in presets:
                presets.append(
                    item
                )

    # ---------------------------------------------------------
    # Mobile hero/background media
    # ---------------------------------------------------------

    if (
        "mobile" in text
        and any(
            word in text
            for word in (
                "hero",
                "background",
                "banner",
                "image",
            )
        )
    ):
        add(
            "mobile_hero",
            "background_mobile",
            "seo",
        )

    elif (
        "background" in text
        and "mobile" in text
    ):
        add(
            "background_mobile",
            "mobile_hero",
            "seo",
        )

    # ---------------------------------------------------------
    # Products
    # ---------------------------------------------------------

    elif "products.product.main_image" in text:
        add(
            "seo",
            "product_detail",
            "product_gallery",
            "product_card_large",
            "product_card",
            "product_thumb",
        )

    elif (
        "productimage" in text
        or "products/gallery" in text
    ):
        add(
            "product_detail",
            "product_gallery",
            "product_card_large",
            "product_card",
            "product_thumb",
            "seo",
        )

    elif (
        "variant" in text
        and "image" in text
    ):
        add(
            "product_detail",
            "product_gallery",
            "product_card_large",
            "product_card",
            "product_thumb",
        )

    elif "accessory" in text:
        add(
            "accessory_thumb",
            "product_card",
            "thumbnail",
        )

    # ---------------------------------------------------------
    # Categories
    # ---------------------------------------------------------

    elif (
        "category" in text
        and any(
            word in text
            for word in (
                "banner",
                "background",
                "hero",
            )
        )
    ):
        add(
            "category_banner",
            "category_card",
            "seo",
            "thumbnail",
        )

    elif "category" in text:
        add(
            "category_card",
            "category_banner",
            "seo",
            "thumbnail",
        )

    # ---------------------------------------------------------
    # Vendors
    # ---------------------------------------------------------

    elif (
        "vendors.vendorprofile.store_banner" in text
        or "store_banner" in text
    ):
        add(
            "vendor_banner",
            "hero_banner",
            "seo",
        )

    # ---------------------------------------------------------
    # Service providers
    # ---------------------------------------------------------

    elif (
        "installers.serviceproviderprofile.business_banner"
        in text
    ):
        add(
            "provider_banner",
            "hero_banner",
            "seo",
        )

    elif (
        "installers.serviceproviderprofile.business_logo"
        in text
    ):
        add(
            "provider_logo",
            "logo",
            "seo",
        )

    elif (
        "installers.serviceproviderprofile.profile_image"
        in text
    ):
        add(
            "provider_profile",
            "avatar",
            "seo",
        )

    # ---------------------------------------------------------
    # Main service project media
    # ---------------------------------------------------------

    elif (
        "installers.serviceportfolio.image"
        in text
    ):
        add(
            "project_card",
            "project_hero",
            "seo",
            "thumbnail",
        )

    elif (
        "installers.serviceportfolio.video_thumbnail"
        in text
    ):
        add(
            "project_hero",
            "project_card",
            "thumbnail",
            "seo",
        )

    # ---------------------------------------------------------
    # ServiceProjectMedia
    # Critical for:
    # - project cards
    # - homepage project rail
    # - project directory
    # - project details
    # - before / during / after project media
    # ---------------------------------------------------------

    elif (
        "installers.serviceprojectmedia.image"
        in text
    ):
        add(
            "project_card",
            "project_hero",
            "seo",
            "thumbnail",
        )

    elif (
        "installers.serviceprojectmedia.thumbnail"
        in text
    ):
        add(
            "project_card",
            "project_hero",
            "thumbnail",
            "seo",
        )

    # ---------------------------------------------------------
    # Generic media types
    # ---------------------------------------------------------

    elif "logo" in text:
        add(
            "logo",
            "thumbnail",
            "seo",
        )

    elif "banner" in text:
        add(
            "hero_banner",
            "ad",
            "banner",
            "seo",
        )

    elif "background" in text:
        add(
            "background_desktop",
            "seo",
        )

    elif (
        "hero_mobile" in text
        or "image_mobile" in text
    ):
        add(
            "mobile_hero",
            "seo",
        )

    elif "hero" in text:
        add(
            "hero_banner",
            "landing_hero",
            "hero",
            "seo",
        )

    elif "homepage" in text:
        add(
            "hero_banner",
            "hero",
            "banner",
            "seo",
        )

    elif "landing_pages" in text:
        add(
            "landing_hero",
            "banner",
            "seo",
            "thumbnail",
        )

    elif (
        "ads." in text
        or "advertisement" in text
        or "promo" in text
    ):
        add(
            "ad",
            "ad_card",
            "banner",
            "seo",
        )

    elif "blog" in text:
        add(
            "blog_card",
            "blog_detail",
            "seo",
            "thumbnail",
        )

    elif (
        "thumbnail" in text
        or "thumb" in text
        or "poster" in text
    ):
        add(
            "thumbnail",
            "seo",
        )

    elif (
        "avatar" in text
        or "profile" in text
        or "photo" in text
    ):
        add(
            "avatar",
            "thumbnail",
        )

    else:
        add(
            "seo",
            "thumbnail",
        )

    return presets


def write(
    stdout,
    style,
    message,
    success=False,
    warning=False,
    error=False,
):
    if not stdout:
        return

    if error and style:
        stdout.write(
            style.ERROR(
                message
            )
        )

    elif warning and style:
        stdout.write(
            style.WARNING(
                message
            )
        )

    elif success and style:
        stdout.write(
            style.SUCCESS(
                message
            )
        )

    else:
        stdout.write(
            message
        )