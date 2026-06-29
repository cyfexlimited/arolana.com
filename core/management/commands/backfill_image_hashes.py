from django.core.management.base import BaseCommand

from core.image_protection import fingerprint_image, iter_image_objects, upsert_protected_asset


class Command(BaseCommand):
    help = "Backfill protected image fingerprints for uploaded ImageField assets."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--model", action="append", default=[], help="Django model label, e.g. products.Product")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        limit = options["limit"]
        model_filter = set(options["model"] or [])

        scanned = hashed = duplicates = errors = 0

        self.stdout.write(self.style.MIGRATE_HEADING("Arolana image hash backfill"))
        self.stdout.write(f"Dry run: {dry_run}")

        for obj, field, image_file, file_name in iter_image_objects(model_filter=model_filter, limit=limit):
            scanned += 1
            fingerprint = fingerprint_image(image_file, file_name)
            if not fingerprint:
                errors += 1
                self.stdout.write(self.style.WARNING(f"Could not read {obj._meta.label} #{obj.pk} {field.name}: {file_name}"))
                continue

            hashed += 1
            _asset, is_duplicate, duplicate_of = upsert_protected_asset(obj, field, fingerprint, dry_run=dry_run)
            if is_duplicate:
                duplicates += 1
                duplicate_label = f"duplicate of asset #{duplicate_of.pk}" if duplicate_of else "duplicate"
                self.stdout.write(self.style.WARNING(f"DUPLICATE {file_name} on {obj._meta.label} #{obj.pk} ({duplicate_label})"))

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Done."))
        self.stdout.write(f"Images scanned: {scanned}")
        self.stdout.write(f"Images hashed: {hashed}")
        self.stdout.write(f"Duplicates detected: {duplicates}")
        self.stdout.write(f"Errors: {errors}")
