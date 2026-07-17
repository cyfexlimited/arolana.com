from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from installers.models import ServiceProjectMedia
from installers.project_video_processing import (
    ensure_legacy_project_video_media,
    process_project_video,
)


class Command(BaseCommand):
    help = "Process pending provider project videos into streaming-safe MP4 files."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=20)
        parser.add_argument("--media-id", type=int)
        parser.add_argument("--retry-failed", action="store_true")
        parser.add_argument("--force", action="store_true")

    def handle(self, *args, **options):
        imported = ensure_legacy_project_video_media()
        if imported:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Imported {imported} legacy project video item"
                    f"{'s' if imported != 1 else ''}."
                )
            )

        stale_before = timezone.now() - timedelta(minutes=45)
        recovered = ServiceProjectMedia.objects.filter(
            media_type=ServiceProjectMedia.TYPE_VIDEO,
            processing_status=ServiceProjectMedia.PROCESSING_ACTIVE,
            updated_at__lt=stale_before,
        ).update(
            processing_status=ServiceProjectMedia.PROCESSING_PENDING,
            processing_error="Recovered after an interrupted conversion.",
            updated_at=timezone.now(),
        )
        if recovered:
            self.stdout.write(f"Recovered {recovered} interrupted project video job(s).")

        queryset = ServiceProjectMedia.objects.filter(
            media_type=ServiceProjectMedia.TYPE_VIDEO,
        ).exclude(video="")
        media_id = options.get("media_id")
        if media_id:
            queryset = queryset.filter(pk=media_id)
        else:
            statuses = [ServiceProjectMedia.PROCESSING_PENDING]
            if options.get("retry_failed"):
                statuses.append(ServiceProjectMedia.PROCESSING_FAILED)
            queryset = queryset.filter(
                processing_status__in=statuses
            ).order_by("created_at", "id")[: max(options["limit"], 1)]

        ids = list(queryset.values_list("id", flat=True))
        if not ids:
            self.stdout.write("No project videos are waiting for processing.")
            return

        completed = 0
        for item_id in ids:
            self.stdout.write(f"Processing project media {item_id}...")
            if process_project_video(
                item_id,
                force=bool(options.get("force")),
                retry_failed=bool(options.get("retry_failed")),
            ):
                completed += 1
                self.stdout.write(self.style.SUCCESS(f"Processed media {item_id}."))
            else:
                self.stdout.write(self.style.ERROR(f"Failed media {item_id}."))
        self.stdout.write(
            self.style.SUCCESS(f"Project video processing finished: {completed}/{len(ids)}.")
        )
