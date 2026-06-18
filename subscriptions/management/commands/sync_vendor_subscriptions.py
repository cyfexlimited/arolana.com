from django.core.management.base import BaseCommand

from subscriptions.services import sync_all_vendor_subscription_profiles


class Command(BaseCommand):
    help = "Sync vendor profile subscription fields from current subscription records."

    def add_arguments(self, parser):
        parser.add_argument(
            "--skip-visibility",
            action="store_true",
            help="Only sync subscription fields and benefits; do not enforce product visibility limits.",
        )

    def handle(self, *args, **options):
        stats = sync_all_vendor_subscription_profiles(
            enforce_visibility=not options["skip_visibility"],
        )
        self.stdout.write(
            self.style.SUCCESS(
                "Synced {synced} vendor profile(s): {active} active, {free} free/default, "
                "{expired} expired subscription record(s), {visibility_hidden} product(s) hidden by limits.".format(**stats)
            )
        )
