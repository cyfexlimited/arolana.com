
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from .models import (
    CoinbaseWebhookLog,
    PaymentMethod,
    PaymentStatus,
    PaymentTransaction,
)


TERMINAL_PAYMENT_STATUSES = {
    PaymentStatus.SUCCESS,
    PaymentStatus.REFUNDED,
    PaymentStatus.FAILED,
    PaymentStatus.CANCELLED,
}


def _clean(value):
    return str(value or "").strip()


def _charge_data(event):
    data = event.get("data") if isinstance(event, dict) else {}
    return data if isinstance(data, dict) else {}


def _charge_metadata(data):
    metadata = data.get("metadata") or {}
    return metadata if isinstance(metadata, dict) else {}


def _charge_identifiers(from_payment):
    payment = from_payment
    identifiers = {_clean(payment.gateway_reference)}
    response = payment.gateway_response or {}
    if isinstance(response, dict):
        data = response.get("data") or {}
        if isinstance(data, dict):
            identifiers.add(_clean(data.get("id")))
            identifiers.add(_clean(data.get("code")))
    identifiers.discard("")
    return identifiers


def validate_coinbase_charge_binding(payment, event, require_amount=True):
    if payment.gateway != PaymentMethod.COINBASE:
        return False, "Payment gateway is not Coinbase."
    data = _charge_data(event)
    metadata = _charge_metadata(data)
    if _clean(metadata.get("reference")) != _clean(payment.reference):
        return False, "Coinbase payment reference mismatch."
    expected_ids = _charge_identifiers(payment)
    event_ids = {_clean(data.get("id")), _clean(data.get("code"))}
    event_ids.discard("")
    if not expected_ids or not event_ids or expected_ids.isdisjoint(event_ids):
        return False, "Coinbase charge identity mismatch."
    if require_amount:
        pricing = data.get("pricing") or {}
        local_price = (pricing.get("local") if isinstance(pricing, dict) else {}) or data.get("local_price") or {}
        try:
            event_amount = Decimal(str(local_price.get("amount"))).quantize(Decimal("0.01"))
            expected_amount = payment.amount_as_decimal.quantize(Decimal("0.01"))
        except (InvalidOperation, TypeError, ValueError):
            return False, "Invalid Coinbase payment amount."
        if event_amount != expected_amount:
            return False, "Coinbase payment amount mismatch."
        if _clean(local_price.get("currency")).upper() != _clean(payment.currency).upper():
            return False, "Coinbase payment currency mismatch."
    return True, ""


@transaction.atomic
def process_coinbase_webhook_event(event, payload):
    event_id = _clean(event.get("id")) if isinstance(event, dict) else ""
    event_type = _clean(event.get("type")) if isinstance(event, dict) else ""
    if not event_id or not event_type:
        raise ValueError("Coinbase event ID and type are required.")
    data = _charge_data(event)
    metadata = _charge_metadata(data)
    reference = _clean(metadata.get("reference"))
    if not reference:
        raise ValueError("Coinbase payment reference is required.")
    log, _ = CoinbaseWebhookLog.objects.get_or_create(event_id=event_id, defaults={"event_type": event_type, "payload": payload})
    log = CoinbaseWebhookLog.objects.select_for_update().get(pk=log.pk)
    if log.processed_at:
        return log, True
    payment = PaymentTransaction.objects.select_for_update().filter(reference=reference, gateway=PaymentMethod.COINBASE).first()
    if not payment:
        raise ValueError("Coinbase payment transaction was not found.")
    log.event_type = event_type
    log.payment = payment
    log.payload = payload
    log.save(update_fields=["event_type", "payment", "payload", "updated_at"])
    if event_type == "charge:confirmed":
        valid, error = validate_coinbase_charge_binding(payment, event, True)
        if not valid: raise ValueError(error)
        if payment.status != PaymentStatus.SUCCESS:
            payment.mark_success(_clean(data.get("id") or data.get("code")), payload)
    elif event_type == "charge:failed":
        valid, error = validate_coinbase_charge_binding(payment, event, False)
        if not valid: raise ValueError(error)
        if payment.status not in TERMINAL_PAYMENT_STATUSES: payment.mark_failed(payload)
    else:
        valid, error = validate_coinbase_charge_binding(payment, event, False)
        if not valid: raise ValueError(error)
        if payment.status not in TERMINAL_PAYMENT_STATUSE:
            payment.status = PaymentStatus.PROCESSING
            payment.webhook_payload = payload
            payment.save(update_fields=["status", "webhook_payload", "updated_at"])
    log.processed_at = timezone.now()
    log.save(update_fields=["processed_at", "updated_at"])
    return log, False
