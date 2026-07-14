from django.core.management.base import BaseCommand

from subscriptions.notifications import retry_failed_subscription_notifications


class Command(BaseCommand):
    help = "Retry failed email and Expo push deliveries for subscription events."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        count = retry_failed_subscription_notifications(limit=max(options["limit"], 1))
        self.stdout.write(self.style.SUCCESS(f"Retried {count} subscription notification(s)."))
