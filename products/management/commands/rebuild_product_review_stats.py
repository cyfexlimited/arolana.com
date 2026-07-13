from decimal import Decimal, ROUND_HALF_UP

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Avg, Count

from products.models import Product, ProductReview


class Command(BaseCommand):
    help = (
        "Rebuild Product.rating_avg and Product.rating_count from the "
        "authoritative ProductReview table."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--product-id",
            type=int,
            help="Repair one product by numeric database ID.",
        )
        parser.add_argument(
            "--slug",
            help="Repair one product by slug.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would change without writing to the database.",
        )

    def handle(self, *args, **options):
        product_id = options.get("product_id")
        slug = str(options.get("slug") or "").strip()
        dry_run = bool(options.get("dry_run"))

        if product_id and slug:
            raise CommandError("Use either --product-id or --slug, not both.")

        products = Product.objects.all().only(
            "id",
            "slug",
            "name",
            "rating_avg",
            "rating_count",
        )

        if product_id:
            products = products.filter(pk=product_id)
        elif slug:
            products = products.filter(slug=slug)

        product_rows = list(products.order_by("id"))

        if not product_rows:
            raise CommandError("No matching product was found.")

        selected_ids = [product.pk for product in product_rows]

        aggregate_rows = (
            ProductReview.objects
            .filter(product_id__in=selected_ids)
            .values("product_id")
            .annotate(
                review_count=Count("id"),
                review_average=Avg("rating"),
            )
        )

        aggregate_map = {
            row["product_id"]: row
            for row in aggregate_rows
        }

        changed = []

        for product in product_rows:
            row = aggregate_map.get(product.pk, {})
            real_count = int(row.get("review_count") or 0)
            real_average = Decimal(
                str(row.get("review_average") or 0)
            ).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )

            cached_count = int(product.rating_count or 0)
            cached_average = Decimal(
                str(product.rating_avg or 0)
            ).quantize(Decimal("0.01"))

            if (
                cached_count == real_count
                and cached_average == real_average
            ):
                continue

            self.stdout.write(
                f"{product.pk} {product.slug}: "
                f"count {cached_count} -> {real_count}, "
                f"average {cached_average} -> {real_average}"
            )

            product.rating_count = real_count
            product.rating_avg = real_average
            changed.append(product)

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"Dry run: {len(changed)} of {len(product_rows)} "
                    "product(s) would be repaired."
                )
            )
            return

        if changed:
            with transaction.atomic():
                Product.objects.bulk_update(
                    changed,
                    ["rating_count", "rating_avg"],
                    batch_size=500,
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Review statistics repaired for {len(changed)} of "
                f"{len(product_rows)} product(s)."
            )
        )
