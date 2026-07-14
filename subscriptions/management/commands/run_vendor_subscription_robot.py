from django.core.management.base import BaseCommand

from subscriptions.services import run_subscription_robot


class Command(BaseCommand):
    help = "Notify accounts about expiring subscriptions and safely process ended plans."

    def handle(self, *args, **options):
        stats = run_subscription_robot()
        self.stdout.write(self.style.SUCCESS("Arolana vendor subscription robot completed."))
        self.stdout.write(f"Expiring reminders sent: {stats['expiring']}")
        self.stdout.write(f"Expired subscriptions processed: {stats['expired']}")
        self.stdout.write("Existing approved products preserved: yes")
