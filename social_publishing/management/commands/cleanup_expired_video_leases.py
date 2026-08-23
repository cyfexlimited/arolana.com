from django.core.management.base import BaseCommand
from django.utils import timezone

from social_publishing.models import TemporaryVideoLease
from social_publishing.publisher import cleanup_orphaned_pending_instagram_publications
from social_publishing.video_staging import cleanup_video_lease


class Command(BaseCommand):
    help = "Delete expired temporary social-publishing video sources."

    def handle(self, *args, **options):
        orphaned = cleanup_orphaned_pending_instagram_publications()
        leases = TemporaryVideoLease.objects.filter(
            cleanup_completed_at__isnull=True,
            expires_at__lte=timezone.now(),
        ).iterator()
        cleaned = failed = 0
        for lease in leases:
            if cleanup_video_lease(lease):
                cleaned += 1
            else:
                failed += 1
        self.stdout.write(
            f"Orphaned publications cleaned={orphaned}; "
            f"expired video leases cleaned={cleaned} failed={failed}"
        )
