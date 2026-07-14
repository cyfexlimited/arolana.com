from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from arolana_payments.models import PaymentStatus, PaymentTransaction
from subscriptions.lifecycle import (
    OFFICIAL_TIER_ORDER,
    activate_subscription_from_payment,
    sync_account_role_subscription,
    tier_rank,
)
from subscriptions.models import SubscriptionPayment, SubscriptionPlan, VendorSubscription


SUBSCRIPTION_PURPOSES = {
    "account_subscription",
    "vendor_subscription",
    "provider_subscription",
}


class Command(BaseCommand):
    help = (
        "Audit the shared account subscription system. Dry-run is the default; "
        "pass --apply to repair safe state/mirror issues."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Apply safe duplicate/status/role-mirror repairs.",
        )
        parser.add_argument(
            "--activate-verified-payments",
            action="store_true",
            help=(
                "With --apply, activate successful server-priced subscription payments "
                "that have no activated receipt."
            ),
        )

    def handle(self, *args, **options):
        apply_changes = options["apply"]
        activate_payments = options["activate_verified_payments"]
        if activate_payments and not apply_changes:
            raise CommandError("--activate-verified-payments requires --apply.")

        now = timezone.now()
        stats = defaultdict(int)
        affected_user_ids = set()

        official_catalog = defaultdict(list)
        for plan in SubscriptionPlan.objects.filter(is_active=True).order_by("id"):
            official_catalog[plan.tier_key].append(plan.id)
            if plan.tier_key not in OFFICIAL_TIER_ORDER:
                stats["unknown_active_plans"] += 1
                self.stdout.write(
                    self.style.WARNING(
                        f"Unknown active plan: id={plan.id} name={plan.name!r}"
                    )
                )
        for tier in OFFICIAL_TIER_ORDER:
            ids = official_catalog.get(tier, [])
            if not ids:
                stats["missing_official_plans"] += 1
                self.stdout.write(self.style.WARNING(f"Missing official plan: {tier}"))
            elif len(ids) > 1:
                stats["duplicate_official_plans"] += len(ids) - 1
                self.stdout.write(
                    self.style.WARNING(f"Duplicate official plan {tier}: ids={ids}")
                )

        subscriptions = VendorSubscription.objects.select_related("plan", "vendor").order_by(
            "vendor_id", "-end_date", "-created_at"
        )
        current_by_user = defaultdict(list)
        for subscription in subscriptions:
            stats["subscriptions_checked"] += 1
            affected_user_ids.add(subscription.vendor_id)
            if subscription.start_date >= subscription.end_date:
                stats["invalid_date_ranges"] += 1
                self.stdout.write(
                    self.style.WARNING(
                        f"Invalid date range: subscription={subscription.id} user={subscription.vendor_id}"
                    )
                )
            if subscription.is_active and subscription.end_date <= now:
                stats["expired_still_active"] += 1
                if apply_changes:
                    subscription.is_active = False
                    subscription.auto_renew = False
                    subscription.status = VendorSubscription.STATUS_EXPIRED
                    subscription.save(
                        update_fields=["is_active", "auto_renew", "status", "updated_at"]
                    )
                    stats["expired_repaired"] += 1
                continue
            if subscription.is_current:
                current_by_user[subscription.vendor_id].append(subscription)

        for user_id, current_records in current_by_user.items():
            if len(current_records) <= 1:
                continue
            stats["accounts_with_duplicate_current"] += 1
            stats["duplicate_current_records"] += len(current_records) - 1
            current_records.sort(
                key=lambda item: (
                    item.payment_state == "paid",
                    tier_rank(item.plan),
                    item.end_date,
                    item.created_at,
                ),
                reverse=True,
            )
            keeper = current_records[0]
            self.stdout.write(
                self.style.WARNING(
                    f"Duplicate current subscriptions: user={user_id} keep={keeper.id} "
                    f"deactivate={[item.id for item in current_records[1:]]}"
                )
            )
            if apply_changes:
                for duplicate in current_records[1:]:
                    duplicate.is_active = False
                    duplicate.auto_renew = False
                    duplicate.status = VendorSubscription.STATUS_INACTIVE
                    duplicate.save(
                        update_fields=["is_active", "auto_renew", "status", "updated_at"]
                    )
                    stats["duplicate_records_repaired"] += 1

        successful_payments = PaymentTransaction.objects.filter(
            status=PaymentStatus.SUCCESS,
            checkout_data__purpose__in=SUBSCRIPTION_PURPOSES,
        ).select_related("user")
        for payment in successful_payments:
            stats["successful_payments_checked"] += 1
            receipt = SubscriptionPayment.objects.filter(payment_transaction=payment).first()
            if receipt and receipt.activated_at and receipt.subscription_id:
                continue
            stats["successful_payments_without_activation"] += 1
            if apply_changes and activate_payments:
                try:
                    activate_subscription_from_payment(
                        payment,
                        source_platform="reconciliation_command",
                    )
                except Exception as error:
                    stats["payment_activation_failures"] += 1
                    self.stderr.write(
                        self.style.ERROR(
                            f"Could not activate payment {payment.reference}: {error}"
                        )
                    )
                else:
                    stats["payments_activated"] += 1
                    if payment.user_id:
                        affected_user_ids.add(payment.user_id)

        for subscription in VendorSubscription.objects.filter(
            is_active=True,
            status__in=[VendorSubscription.STATUS_ACTIVE, VendorSubscription.STATUS_TRIAL],
            plan__price_monthly__gt=0,
        ).select_related("plan"):
            has_receipt = SubscriptionPayment.objects.filter(
                subscription=subscription,
                status=SubscriptionPayment.STATUS_SUCCESS,
            ).exists()
            legacy_paid = subscription.payment_state in {"legacy_migrated", "admin_grant"}
            if not has_receipt and not legacy_paid:
                stats["active_paid_without_receipt"] += 1

        if apply_changes:
            from django.contrib.auth import get_user_model

            User = get_user_model()
            for user in User.objects.filter(pk__in=affected_user_ids).iterator():
                sync_account_role_subscription(user)
                stats["role_mirrors_synced"] += 1

        mode = "APPLIED" if apply_changes else "DRY RUN"
        self.stdout.write(self.style.SUCCESS(f"Subscription reconciliation {mode}"))
        for key in sorted(stats):
            self.stdout.write(f"  {key}: {stats[key]}")
        if not apply_changes:
            self.stdout.write("No data was changed. Re-run with --apply after reviewing this report.")
