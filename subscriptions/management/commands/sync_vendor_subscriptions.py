from django.core.management.base import BaseCommand

from subscriptions.services import sync_all_vendor_subscription_profiles


class Command(BaseCommand):
    help = "Sync vendor profile subscription fields from current subscription records."

    def add_arguments(self, parser):
        parser.add_argument(
            "--enforce-legacy-visibility",
            action="store_true",
            help="Deprecated emergency option. Hide products using old tier limits.",
        )

    def handle(self, *args, **options):
        stats = sync_all_vendor_subscription_profiles(
            enforce_visibility=options["enforce_legacy_visibility"],
        )
        self.stdout.write(
            self.style.SUCCESS(
                "Synced {synced} vendor profile(s): {active} active, {free} free/default, "
                "{expired} expired subscription record(s), {visibility_hidden} product(s) hidden by limits.".format(**stats)
            )
        )
