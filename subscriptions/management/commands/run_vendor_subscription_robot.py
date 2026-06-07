from django.core.management.base import BaseCommand

from subscriptions.services import run_subscription_robot


class Command(BaseCommand):
    help = "Notify vendors about expiring subscriptions, expire ended plans, and enforce Free plan product visibility."

    def handle(self, *args, **options):
        stats = run_subscription_robot()
        self.stdout.write(self.style.SUCCESS("Arolana vendor subscription robot completed."))
        self.stdout.write(f"Expiring reminders sent: {stats['expiring']}")
        self.stdout.write(f"Expired subscriptions processed: {stats['expired']}")
        self.stdout.write(f"Products hidden by Free tier enforcement: {stats['visibility_updated']}")
