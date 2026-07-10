from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count
from django.utils import timezone

from mobile_customers.models import (
    MobileCustomer,
    MobileCustomerAccessToken,
)


class Command(BaseCommand):
    help = (
        "Audit mobile customer token storage for plaintext legacy tokens, "
        "expiry state, revocation state, and token-hash uniqueness."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--fail-on-plaintext",
            action="store_true",
            help="Exit non-zero if any legacy plaintext api_token values remain.",
        )
        parser.add_argument(
            "--fail-on-error",
            action="store_true",
            help="Exit non-zero on any structural token audit error.",
        )

    def handle(self, *args, **options):
        now = timezone.now()

        plaintext_count = (
            MobileCustomer.objects
            .exclude(api_token="")
            .exclude(api_token__isnull=True)
            .count()
        )

        total = MobileCustomerAccessToken.objects.count()
        active = MobileCustomerAccessToken.objects.filter(
            revoked_at__isnull=True,
            expires_at__gt=now,
        ).count()
        expired = MobileCustomerAccessToken.objects.filter(
            expires_at__lte=now,
        ).count()
        revoked = MobileCustomerAccessToken.objects.filter(
            revoked_at__isnull=False,
        ).count()

        duplicate_hash_groups = (
            MobileCustomerAccessToken.objects
            .values("token_hash")
            .annotate(total=Count("id"))
            .filter(total__gt=1)
            .count()
        )

        errors = []

        if duplicate_hash_groups:
            errors.append(
                f"{duplicate_hash_groups} duplicate token hash group(s)"
            )

        self.stdout.write("")
        self.stdout.write("Arolana Mobile Customer Token Audit")
        self.stdout.write("=" * 72)
        self.stdout.write(f"Plaintext legacy tokens: {plaintext_count}")
        self.stdout.write(f"Token rows: {total}")
        self.stdout.write(f"Active: {active}")
        self.stdout.write(f"Expired: {expired}")
        self.stdout.write(f"Revoked: {revoked}")
        self.stdout.write(
            f"Duplicate hash groups: {duplicate_hash_groups}"
        )

        if errors:
            for error in errors:
                self.stderr.write(self.style.ERROR(f"ERROR: {error}"))

        if options["fail_on_plaintext"] and plaintext_count:
            raise CommandError(
                f"{plaintext_count} plaintext legacy token(s) remain."
            )

        if options["fail_on_error"] and errors:
            raise CommandError(
                f"Mobile token audit found {len(errors)} error(s)."
            )

        if not errors:
            self.stdout.write(
                self.style.SUCCESS(
                    "Mobile customer token audit passed."
                )
            )
