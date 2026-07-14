from django.core.management.base import BaseCommand

from subscriptions.lifecycle import process_subscription_lifecycle


class Command(BaseCommand):
    help = (
        "Process account-level subscription reminders, grace periods, expiry, "
        "scheduled cancellations, and scheduled downgrades. Safe to run repeatedly."
    )

    def handle(self, *args, **options):
        result = process_subscription_lifecycle()
        summary = ", ".join(f"{key}={value}" for key, value in sorted(result.items()))
        self.stdout.write(self.style.SUCCESS(f"Account subscription lifecycle complete: {summary}"))
