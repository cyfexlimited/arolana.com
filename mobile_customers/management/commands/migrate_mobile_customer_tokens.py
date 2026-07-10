from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from mobile_customers.models import (
    MobileCustomer,
    MobileCustomerAccessToken,
)
from mobile_customers.token_auth import (
    _legacy_token_ttl,
    mobile_token_digest,
)


class Command(BaseCommand):
    help = (
        "Hash existing plaintext MobileCustomer.api_token values into "
        "expiring MobileCustomerAccessToken rows and clear the plaintext field."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without writing anything.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        now = timezone.now()

        customers = list(
            MobileCustomer.objects
            .exclude(api_token="")
            .exclude(api_token__isnull=True)
            .only("id", "api_token")
            .order_by("id")
        )

        if not customers:
            self.stdout.write(
                self.style.SUCCESS(
                    "No plaintext mobile customer tokens remain."
                )
            )
            return

        digests = {}
        collisions = []

        for customer in customers:
            raw_token = str(customer.api_token or "")
            digest = mobile_token_digest(raw_token)

            prior_customer_id = digests.get(digest)
            if (
                prior_customer_id is not None
                and prior_customer_id != customer.pk
            ):
                collisions.append(
                    (digest[:16], prior_customer_id, customer.pk)
                )
            else:
                digests[digest] = customer.pk

        existing_rows = {
            row.token_hash: row.customer_id
            for row in MobileCustomerAccessToken.objects.filter(
                token_hash__in=list(digests.keys())
            )
        }

        for digest, customer_id in digests.items():
            existing_customer_id = existing_rows.get(digest)
            if (
                existing_customer_id is not None
                and existing_customer_id != customer_id
            ):
                collisions.append(
                    (
                        digest[:16],
                        existing_customer_id,
                        customer_id,
                    )
                )

        if collisions:
            for fingerprint, left_id, right_id in collisions:
                self.stderr.write(
                    f"COLLISION fingerprint={fingerprint} "
                    f"customers={left_id},{right_id}"
                )
            raise CommandError(
                "Token collisions found. Nothing was migrated."
            )

        self.stdout.write(
            f"Plaintext customer tokens found: {len(customers)}"
        )

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    "Dry run only. No database changes were made."
                )
            )
            return

        migrated = 0
        reused = 0

        with transaction.atomic():
            for customer_stub in customers:
                customer = (
                    MobileCustomer.objects
                    .select_for_update()
                    .get(pk=customer_stub.pk)
                )

                raw_token = str(customer.api_token or "")
                if not raw_token:
                    continue

                digest = mobile_token_digest(raw_token)

                token, created = (
                    MobileCustomerAccessToken.objects
                    .get_or_create(
                        token_hash=digest,
                        defaults={
                            "customer": customer,
                            "fingerprint": digest[:16],
                            "device_name": "Migrated legacy session",
                            "expires_at": now + _legacy_token_ttl(),
                            "last_used_at": now,
                        },
                    )
                )

                if token.customer_id != customer.pk:
                    raise CommandError(
                        "Token digest belongs to another customer. "
                        "Migration rolled back."
                    )

                if created:
                    migrated += 1
                else:
                    reused += 1

                customer.api_token = ""
                update_fields = ["api_token"]

                if hasattr(customer, "updated_at"):
                    update_fields.append("updated_at")

                customer.save(update_fields=update_fields)

        self.stdout.write(
            self.style.SUCCESS(
                f"Migration complete. Created={migrated}, "
                f"reused={reused}, plaintext_cleared={len(customers)}."
            )
        )
