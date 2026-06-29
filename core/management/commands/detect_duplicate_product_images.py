from django.core.management.base import BaseCommand

from core.image_protection import (
    fingerprint_image,
    hamming_distance,
    iter_image_objects,
    upsert_protected_asset,
)


PRODUCT_MODELS = {
    "products.Product",
    "products.ProductImage",
    "products.ProductVariant",
    "products.ProductVariantImage",
}


class Command(BaseCommand):
    help = "Detect exact and visually similar duplicate product images."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--near-threshold", type=int, default=6)

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        limit = options["limit"]
        near_threshold = max(0, int(options["near_threshold"]))

        exact_seen = {}
        phash_seen = []
        scanned = exact_duplicates = near_duplicates = errors = 0

        self.stdout.write(self.style.MIGRATE_HEADING("Arolana product duplicate image detector"))
        self.stdout.write(f"Dry run: {dry_run}")
        self.stdout.write(f"Near duplicate threshold: {near_threshold}")

        for obj, field, image_file, file_name in iter_image_objects(model_filter=PRODUCT_MODELS, limit=limit):
            scanned += 1
            fingerprint = fingerprint_image(image_file, file_name)
            if not fingerprint:
                errors += 1
                continue

            _asset, is_duplicate, duplicate_of = upsert_protected_asset(obj, field, fingerprint, dry_run=dry_run)

            label = f"{obj._meta.label} #{obj.pk} {field.name}"
            if fingerprint.sha256 in exact_seen:
                exact_duplicates += 1
                self.stdout.write(self.style.WARNING(f"EXACT duplicate: {file_name} ({label}) matches {exact_seen[fingerprint.sha256]}"))
            else:
                exact_seen[fingerprint.sha256] = label

            if is_duplicate and duplicate_of:
                self.stdout.write(self.style.WARNING(f"RECORDED duplicate: {file_name} -> protected asset #{duplicate_of.pk}"))

            if fingerprint.perceptual_hash:
                for previous_hash, previous_label, previous_file in phash_seen:
                    distance = hamming_distance(fingerprint.perceptual_hash, previous_hash)
                    if distance is not None and distance <= near_threshold:
                        near_duplicates += 1
                        self.stdout.write(
                            self.style.WARNING(
                                f"NEAR duplicate ({distance}): {file_name} ({label}) looks like {previous_file} ({previous_label})"
                            )
                        )
                        break
                phash_seen.append((fingerprint.perceptual_hash, label, file_name))

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Done."))
        self.stdout.write(f"Product images scanned: {scanned}")
        self.stdout.write(f"Exact duplicates: {exact_duplicates}")
        self.stdout.write(f"Near duplicates: {near_duplicates}")
        self.stdout.write(f"Errors: {errors}")
