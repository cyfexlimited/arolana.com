from django.db import transaction
from django.utils import timezone

from .models import PaymentMethod, PaymentStatus, PaymentTransaction


def _require_staff_reviewer(reviewer):
    if not (
        reviewer
        and getattr(reviewer, "is_authenticated", False)
        and getattr(reviewer, "is_active", False)
        and getattr(reviewer, "is_staff", False)
    ):
        raise PermissionError("Only active staff can review manual crypto payments.")


@transaction.atomic
def approve_manual_crypto_payment(payment_id, reviewer, note=""):
    _require_staff_reviewer(reviewer)

    payment = (
        PaymentTransaction.objects
        .select_for_update()
        .get(pk=payment_id)
    )

    if (
        payment.status == PaymentStatus.SUCCESS
        and payment.manual_review_decision == "approved"
    ):
        return payment

    if payment.gateway != PaymentMethod.MANUAL_CRYPTO:
        raise ValueError("Only manual crypto payments can use manual approval.")

    if payment.status != PaymentStatus.REVIEW:
        raise ValueError("Manual crypto payment must be in review before approval.")

    if not payment.manual_proof:
        raise ValueError("Payment proof is required before approval.")

    tx_hash = str(payment.manual_tx_hash or "").strip()
    if not tx_hash:
        raise ValueError("Transaction hash is required before approval.")

    if (
        PaymentTransaction.objects
        .exclude(pk=payment.pk)
        .filter(manual_tx_hash=tx_hash)
        .exists()
    ):
        raise ValueError("This transaction hash is already used by another payment.")

    reviewed_at = timezone.now()
    payment.manual_reviewed_by = reviewer
    payment.manual_reviewed_at = reviewed_at
    payment.manual_review_decision = "approved"
    payment.manual_review_note = str(note or "").strip()
    payment.save(
        update_fields=[
            "manual_reviewed_by",
            "manual_reviewed_at",
            "manual_review_decision",
            "manual_review_note",
            "updated_at",
        ]
    )

    payment.mark_success(
        tx_hash,
        {
            "manual_crypto_review": {
                "decision": "approved",
                "reviewer_id": reviewer.pk,
                "reviewed_at": reviewed_at.isoformat(),
                "transaction_hash": tx_hash,
            }
        },
    )

    return payment


@transaction.atomic
def reject_manual_crypto_payment(payment_id, reviewer, note=""):
    _require_staff_reviewer(reviewer)

    payment = (
        PaymentTransaction.objects
        .select_for_update()
        .get(pk=payment_id)
    )

    if (
        payment.status == PaymentStatus.FAILED
        and payment.manual_review_decision == "rejected"
    ):
        return payment

    if payment.gateway != PaymentMethod.MANUAL_CRYPTO:
        raise ValueError("Only manual crypto payments can use manual rejection.")

    if payment.status != PaymentStatus.REVIEW:
        raise ValueError("Manual crypto payment must be in review before rejection.")

    reviewed_at = timezone.now()
    payment.manual_reviewed_by = reviewer
    payment.manual_reviewed_at = reviewed_at
    payment.manual_review_decision = "rejected"
    payment.manual_review_note = str(note or "").strip()
    payment.save(
        update_fields=[
            "manual_reviewed_by",
            "manual_reviewed_at",
            "manual_review_decision",
            "manual_review_note",
            "updated_at",
        ]
    )

    payment.mark_failed(
        {
            "manual_crypto_review": {
                "decision": "rejected",
                "reviewer_id": reviewer.pk,
                "reviewed_at": reviewed_at.isoformat(),
            }
        }
    )

    return payment
