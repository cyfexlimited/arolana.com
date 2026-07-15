import time

from django.core.management.base import BaseCommand

from products.models import ProductReview
from products.video_conversion import convert_review_video


class Command(BaseCommand):
    help = (
        "Process pending customer review-video conversions."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--once",
            action="store_true",
            help="Process pending jobs once and exit.",
        )

        parser.add_argument(
            "--sleep",
            type=int,
            default=10,
            help="Seconds to wait when no jobs are available.",
        )

    def handle(self, *args, **options):
        run_once = bool(
            options["once"]
        )

        sleep_seconds = max(
            int(options["sleep"]),
            2,
        )

        self.stdout.write(
            self.style.SUCCESS(
                "Review-video conversion worker started."
            )
        )

        while True:
            review = (
                ProductReview.objects
                .filter(
                    review_video_conversion_status="pending",
                )
                .exclude(
                    video_review="",
                )
                .order_by(
                    "created_at",
                    "id",
                )
                .first()
            )

            if not review:
                if run_once:
                    break

                time.sleep(
                    sleep_seconds
                )
                continue

            self.stdout.write(
                f"Converting review {review.pk}..."
            )

            success = convert_review_video(
                review.pk
            )

            if success:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Converted review {review.pk}."
                    )
                )
                
            else:
                self.stdout.write(
                    self.style.ERROR(
                        f"Failed review {review.pk}."
                    )
                )

        self.stdout.write(
            self.style.SUCCESS(
                "Review-video conversion worker finished."
            )
        )