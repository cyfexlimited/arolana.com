from __future__ import annotations

from django.core.management.base import BaseCommand

from core.models import HomePageAppearance, SiteSettings


class Command(BaseCommand):
    help = (
        "Create missing required singleton configuration records "
        "without overwriting existing settings."
    )

    def handle(self, *args, **options):
        site_settings, site_settings_created = SiteSettings.objects.get_or_create(
            pk=1
        )

        homepage_appearance, homepage_appearance_created = (
            HomePageAppearance.objects.get_or_create(pk=1)
        )

        self.stdout.write(
            self.style.SUCCESS(
                "Required configuration is ready.\n"
                f"SiteSettings: id={site_settings.pk}, "
                f"created={site_settings_created}\n"
                f"HomePageAppearance: id={homepage_appearance.pk}, "
                f"created={homepage_appearance_created}"
            )
        )
