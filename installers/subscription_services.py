from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from arolana_payments.models import (
    PaymentMethod,
    PaymentStatus,
    PaymentTransaction,
)
from notifications.models import Notification

from .models import (
    ProviderSubscriptionPlan,
    ServiceProviderProfile,
)


PROVIDER_SUBSCRIPTION_PURPOSE = "provider_subscription"

BILLING_MONTHLY = "monthly"
BILLING_YEARLY = "yearly"
BILLING_FREE = "free"

VALID_BILLING_CYCLES = {
    BILLING_MONTHLY,
    BILLING_YEARLY,
    BILLING_FREE,
}


def provider_plan_amount(plan, billing_cycle):
    billing_cycle = str(
        billing_cycle or ""
    ).strip().lower()

    if billing_cycle == BILLING_MONTHLY:
        return Decimal(str(plan.price_monthly))

    if billing_cycle == BILLING_YEARLY:
        return Decimal(str(plan.price_yearly))

    if billing_cycle == BILLING_FREE:
        if (
            Decimal(str(plan.price_monthly)) != Decimal("0.00")
            or Decimal(str(plan.price_yearly)) != Decimal("0.00")
        ):
            raise ValueError(
                "Only a free provider plan can use the free billing cycle."
            )

        return Decimal("0.00")

    raise ValueError(
        "Choose monthly or yearly billing."
    )


def create_provider_subscription_payment(
    provider,
    plan,
    billing_cycle,
    gateway=PaymentMethod.PAYSTACK,
):
    if not provider or not provider.pk:
        raise ValueError(
            "A valid provider profile is required."
        )

    if not plan or not plan.pk or not plan.is_active:
        raise ValueError(
            "Choose an active provider subscription plan."
        )

    billing_cycle = str(
        billing_cycle or ""
    ).strip().lower()

    amount = provider_plan_amount(
        plan,
        billing_cycle,
    )

    payment = PaymentTransaction.objects.create(
        user=provider.user,
        order_id=(
            f"provider_subscription:"
            f"{provider.id}:"
            f"{plan.id}:"
            f"{billing_cycle}"
        ),
        gateway=gateway,
        status=PaymentStatus.PENDING,
        amount=amount,
        currency="NGN",
        customer_email=(
            provider.email
            or provider.user.email
            or ""
        ),
        customer_name=(
            provider.business_name
            or provider.contact_person
            or provider.user.get_full_name()
            or provider.user.email
        ),
        customer_phone=(
            provider.phone_number
            or ""
        ),
        checkout_data={
            "purpose": PROVIDER_SUBSCRIPTION_PURPOSE,
            "provider_id": provider.id,
            "provider_plan_id": plan.id,
            "plan_id": plan.id,
            "plan_name": plan.name,
            "billing_cycle": billing_cycle,
            "expected_amount": str(amount),
            "currency": "NGN",
        },
    )

    return payment


def _provider_subscription_expiry(
    provider,
    plan,
    billing_cycle,
    now,
):
    if billing_cycle == BILLING_FREE:
        return None

    same_active_plan = (
        provider.subscription_plan == plan.name
        and provider.subscription_status in {
            "active",
            "trial",
        }
        and provider.subscription_expires_at
        and provider.subscription_expires_at > now
    )

    start_from = (
        provider.subscription_expires_at
        if same_active_plan
        else now
    )

    if billing_cycle == BILLING_MONTHLY:
        return start_from + timedelta(days=30)

    if billing_cycle == BILLING_YEARLY:
        return start_from + timedelta(days=365)

    raise ValueError(
        "Invalid provider subscription billing cycle."
    )


def activate_provider_subscription_payment(
    payment_id,
    now=None,
):
    now = now or timezone.now()

    try:
        with transaction.atomic():
            payment = (
                PaymentTransaction.objects
                .select_for_update()
                .select_related("user")
                .get(pk=payment_id)
            )

            if payment.status != PaymentStatus.SUCCESS:
                raise ValueError(
                    "Provider subscription payment is not successful."
                )

            checkout_data = payment.checkout_data or {}

            purpose = str(
                checkout_data.get("purpose") or ""
            ).strip().lower()

            if purpose != PROVIDER_SUBSCRIPTION_PURPOSE:
                raise ValueError(
                    "Payment is not a provider subscription payment."
                )

            provider_id = checkout_data.get(
                "provider_id"
            )

            plan_id = (
                checkout_data.get("provider_plan_id")
                or checkout_data.get("plan_id")
            )

            billing_cycle = str(
                checkout_data.get("billing_cycle") or ""
            ).strip().lower()

            if billing_cycle not in VALID_BILLING_CYCLES:
                raise ValueError(
                    "Invalid provider subscription billing cycle."
                )

            provider = (
                ServiceProviderProfile.objects
                .select_for_update()
                .select_related("user")
                .filter(pk=provider_id)
                .first()
            )

            if not provider:
                raise ValueError(
                    "Provider profile for this payment was not found."
                )

            plan = (
                ProviderSubscriptionPlan.objects
                .filter(
                    pk=plan_id,
                    is_active=True,
                )
                .first()
            )

            if not plan:
                raise ValueError(
                    "Provider subscription plan was not found."
                )

            if payment.user_id != provider.user_id:
                raise ValueError(
                    "Provider subscription payment owner mismatch."
                )

            expected_amount = provider_plan_amount(
                plan,
                billing_cycle,
            )

            if payment.amount != expected_amount:
                raise ValueError(
                    "Provider subscription payment amount mismatch."
                )

            expected_metadata_amount = Decimal(
                str(
                    checkout_data.get("expected_amount")
                    or expected_amount
                )
            )

            if expected_metadata_amount != expected_amount:
                raise ValueError(
                    "Provider subscription metadata amount mismatch."
                )

            if (
                str(payment.currency or "").strip().upper()
                != "NGN"
            ):
                raise ValueError(
                    "Provider subscription currency mismatch."
                )

            expected_order_id = (
                f"provider_subscription:"
                f"{provider.id}:"
                f"{plan.id}:"
                f"{billing_cycle}"
            )

            if (
                payment.order_id
                and payment.order_id != expected_order_id
            ):
                raise ValueError(
                    "Provider subscription payment target mismatch."
                )

            if payment.fulfilled_at:
                return provider

            payment.fulfillment_attempts += 1
            payment.fulfillment_error = ""

            payment.save(
                update_fields=[
                    "fulfillment_attempts",
                    "fulfillment_error",
                    "updated_at",
                ]
            )

            expiry = _provider_subscription_expiry(
                provider,
                plan,
                billing_cycle,
                now,
            )

            provider.subscription_plan = plan.name
            provider.subscription_status = "active"
            provider.subscription_expires_at = expiry

            provider.save(
                update_fields=[
                    "subscription_plan",
                    "subscription_status",
                    "subscription_expires_at",
                    "updated_at",
                ]
            )

            payment.fulfilled_at = now
            payment.fulfillment_error = ""

            payment.save(
                update_fields=[
                    "fulfilled_at",
                    "fulfillment_error",
                    "updated_at",
                ]
            )

            provider_id_for_notification = provider.id
            user_id = provider.user_id
            plan_name = plan.name
            payment_reference = payment.reference

            expiry_text = (
                expiry.strftime("%d %b %Y")
                if expiry
                else "No fixed expiry"
            )

            def send_activation_notification():
                Notification.send(
                    provider.user,
                    "payment",
                    "Provider subscription activated",
                    (
                        f"Your Arolana provider plan is now "
                        f"{plan_name}. Access expires: {expiry_text}. "
                        f"Payment reference: {payment_reference}."
                    ),
                    link="/dashboard/provider/subscription/",
                    metadata={
                        "service_provider_id": (
                            provider_id_for_notification
                        ),
                        "provider_subscription_plan_id": (
                            plan.id
                        ),
                        "payment_reference": (
                            payment_reference
                        ),
                        "billing_cycle": billing_cycle,
                    },
                    priority=3,
                )

            transaction.on_commit(
                send_activation_notification,
                robust=True,
            )

            return provider

    except Exception as exc:
        with transaction.atomic():
            failed_payment = (
                PaymentTransaction.objects
                .select_for_update()
                .filter(pk=payment_id)
                .first()
            )

            if (
                failed_payment
                and not failed_payment.fulfilled_at
            ):
                failed_payment.fulfillment_attempts += 1

                failed_payment.fulfillment_error = str(
                    exc
                )[:4000]

                failed_payment.save(
                    update_fields=[
                        "fulfillment_attempts",
                        "fulfillment_error",
                        "updated_at",
                    ]
                )

        raise