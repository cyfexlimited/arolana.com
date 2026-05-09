from django.core.management.base import BaseCommand
from allauth.socialaccount.models import SocialApp

class Command(BaseCommand):
    help = 'Remove duplicate Google social apps'

    def handle(self, *args, **options):
        deleted_count, _ = SocialApp.objects.filter(provider='google').delete()
        self.stdout.write(
            self.style.SUCCESS(
                f'✓ Successfully deleted {deleted_count} Google SocialApp(s). '
                'Now using settings-based config.'
            )
        )
