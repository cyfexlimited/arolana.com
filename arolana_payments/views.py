import json

import stripe
from django.conf import settings
from django.contrib import messages
from django.core.mail import send_mail
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import ManualCryptoWallet, PaymentMethod, PaymentStatus, PaymentTransaction
from .services import (
    capture_paypal_order,
    create_transaction,
    init_coinbase_checkout,
    init_flutterwave_checkout,
    init_paypal_checkout,
    init_stripe_checkout,
    gateway_is_available,
    get_gateway_options,
    update_order_after_payment,
    verify_coinbase_signature,
    verify_flutterwave_transaction,
    verify_flutterwave_webhook,
)


def checkout(request):
    """
    Payment selection page.

    Expected query params or POST fields:
    amount, currency, order_id, email, name, phone
    """
    wallets = ManualCryptoWallet.objects.filter(is_active=True)

    context = {
        "wallets": wallets,
        "payment_options": get_gateway_options(),
        "amount": request.GET.get("amount", request.POST.get("amount", "")),
        "currency": request.GET.get("currency", request.POST.get("currency", getattr(settings, "AROLANA_DEFAULT_CURRENCY", "NGN"))),
        "order_id": request.GET.get("order_id", request.POST.get("order_id", "")),
        "email": request.GET.get("email", request.POST.get("email", "")),
        "name": request.GET.get("name", request.POST.get("name", "")),
        "phone": request.GET.get("phone", request.POST.get("phone", "")),
    }
    return render(request, "arolana_payments/checkout.html", context)


@require_POST
def start_payment(request, gateway):
    if gateway not in PaymentMethod.values:
        return HttpResponseBadRequest("Unsupported payment gateway.")

    try:
        is_available, disabled_reason = gateway_is_available(gateway)
        if not is_available:
            messages.error(request, disabled_reason or "This payment gateway is not available yet.")
            return redirect("arolana_payments:checkout")

        payment = create_transaction(request, gateway)

        if gateway == PaymentMethod.FLUTTERWAVE:
            url = init_flutterwave_checkout(request, payment)
        elif gateway == PaymentMethod.PAYPAL:
            url = init_paypal_checkout(request, payment)
        elif gateway == PaymentMethod.STRIPE:
            url = init_stripe_checkout(request, payment)
        elif gateway == PaymentMethod.COINBASE:
            url = init_coinbase_checkout(request, payment)
        elif gateway == PaymentMethod.MANUAL_CRYPTO:
            return redirect("arolana_payments:manual_crypto", reference=payment.reference)
        else:
            return HttpResponseBadRequest("Unsupported payment gateway.")

        if not url:
            payment.mark_failed({"error": "Gateway did not return checkout URL."})
            messages.error(request, "Payment gateway did not return a checkout link. Please try another method.")
            return redirect("arolana_payments:checkout")

        return redirect(url)

    except Exception as exc:
        if 'payment' in locals():
            payment.mark_failed({"error": str(exc)})
        messages.error(request, f"Payment initialization failed: {exc}")
        return redirect("arolana_payments:checkout")


def manual_crypto(request, reference):
    payment = get_object_or_404(PaymentTransaction, reference=reference, gateway=PaymentMethod.MANUAL_CRYPTO)
    wallets = ManualCryptoWallet.objects.filter(is_active=True)

    if request.method == "POST":
        wallet_id = request.POST.get("wallet_id")
        wallet = get_object_or_404(ManualCryptoWallet, id=wallet_id, is_active=True)

        payment.manual_wallet_network = wallet.network
        payment.manual_wallet_address = wallet.address
        payment.manual_sender_wallet = request.POST.get("sender_wallet", "")
        payment.manual_tx_hash = request.POST.get("tx_hash", "")
        payment.manual_note = request.POST.get("note", "")
        payment.status = PaymentStatus.REVIEW

        if request.FILES.get("proof"):
            payment.manual_proof = request.FILES["proof"]

        payment.save()

        subject = f"Arolana manual crypto payment submitted - {payment.reference}"
        message = (
            f"Manual crypto payment submitted.\\n\\n"
            f"Reference: {payment.reference}\\n"
            f"Order ID: {payment.order_id}\\n"
            f"Amount: {payment.amount} {payment.currency}\\n"
            f"Wallet Network: {payment.manual_wallet_network}\\n"
            f"Wallet Address: {payment.manual_wallet_address}\\n"
            f"Sender Wallet: {payment.manual_sender_wallet}\\n"
            f"Transaction Hash: {payment.manual_tx_hash}\\n"
            f"Customer: {payment.customer_name} <{payment.customer_email}>\\n"
        )

        recipients = [email for email in [
            getattr(settings, "PAYMENT_ADMIN_EMAIL", ""),
            getattr(settings, "DEFAULT_FROM_EMAIL", ""),
        ] if email]

        if recipients:
            send_mail(subject, message, getattr(settings, "DEFAULT_FROM_EMAIL", None), recipients, fail_silently=True)

        if payment.customer_email:
            send_mail(
                f"Payment proof received - {payment.reference}",
                "We received your crypto payment proof. Your payment is under review and you will be notified after confirmation.",
                getattr(settings, "DEFAULT_FROM_EMAIL", None),
                [payment.customer_email],
                fail_silently=True,
            )

        messages.success(request, "Crypto payment proof submitted. We will review and confirm your payment.")
        return redirect("arolana_payments:status", reference=payment.reference)

    return render(request, "arolana_payments/manual_crypto.html", {
        "payment": payment,
        "wallets": wallets,
    })


def callback(request, reference):
    payment = get_object_or_404(PaymentTransaction, reference=reference)

    if payment.gateway == PaymentMethod.FLUTTERWAVE:
        transaction_id = request.GET.get("transaction_id")
        status = request.GET.get("status")

        if transaction_id and status == "successful":
            data = verify_flutterwave_transaction(transaction_id)
            if data.get("status") == "success" and data.get("data", {}).get("status") == "successful":
                payment.mark_success(str(transaction_id), data)
                update_order_after_payment(payment)
            else:
                payment.mark_failed(data)

    elif payment.gateway == PaymentMethod.PAYPAL:
        data = capture_paypal_order(payment)
        if data.get("status") == "COMPLETED":
            payment.mark_success(data.get("id", ""), data)
            update_order_after_payment(payment)
        else:
            payment.mark_failed(data)

    elif payment.gateway == PaymentMethod.STRIPE:
        session_id = request.GET.get("session_id")
        if session_id:
            stripe.api_key = settings.STRIPE_SECRET_KEY
            session = stripe.checkout.Session.retrieve(session_id)
            if session.payment_status == "paid":
                payment.mark_success(session_id, dict(session))
                update_order_after_payment(payment)

    elif payment.gateway == PaymentMethod.COINBASE:
        # Coinbase final confirmation should happen through webhook.
        if payment.status not in [PaymentStatus.SUCCESS, PaymentStatus.FAILED]:
            payment.status = PaymentStatus.PROCESSING
            payment.save(update_fields=["status", "updated_at"])

    return redirect("arolana_payments:status", reference=payment.reference)


def cancel(request, reference):
    payment = get_object_or_404(PaymentTransaction, reference=reference)
    payment.status = PaymentStatus.CANCELLED
    payment.save(update_fields=["status", "updated_at"])
    messages.warning(request, "Payment cancelled.")
    return redirect("arolana_payments:status", reference=payment.reference)


def status(request, reference):
    payment = get_object_or_404(PaymentTransaction, reference=reference)
    return render(request, "arolana_payments/status.html", {"payment": payment})


@csrf_exempt
def stripe_webhook(request):
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE")
    endpoint_secret = getattr(settings, "STRIPE_WEBHOOK_SECRET", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except Exception:
        return HttpResponseBadRequest("Invalid Stripe webhook.")

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        reference = session.get("metadata", {}).get("reference")
        if reference:
            payment = PaymentTransaction.objects.filter(reference=reference).first()
            if payment:
                payment.mark_success(session.get("id", ""), event)
                update_order_after_payment(payment)

    return JsonResponse({"received": True})


@csrf_exempt
def flutterwave_webhook(request):
    if not verify_flutterwave_webhook(request):
        return HttpResponseBadRequest("Invalid Flutterwave webhook.")

    payload = json.loads(request.body.decode("utf-8") or "{}")
    tx_ref = payload.get("data", {}).get("tx_ref") or payload.get("tx_ref")
    status = payload.get("data", {}).get("status") or payload.get("status")

    payment = PaymentTransaction.objects.filter(reference=tx_ref).first()
    if payment:
        if status == "successful":
            payment.mark_success(payload.get("data", {}).get("id", ""), payload)
            update_order_after_payment(payment)
        else:
            payment.mark_failed(payload)

    return JsonResponse({"received": True})


@csrf_exempt
def coinbase_webhook(request):
    signature = request.headers.get("X-CC-Webhook-Signature", "")
    if not verify_coinbase_signature(request.body, signature):
        return HttpResponseBadRequest("Invalid Coinbase webhook.")

    payload = json.loads(request.body.decode("utf-8") or "{}")
    event = payload.get("event", {})
    event_type = event.get("type", "")
    data = event.get("data", {})
    reference = data.get("metadata", {}).get("reference")

    payment = PaymentTransaction.objects.filter(reference=reference).first()
    if payment:
        if event_type == "charge:confirmed":
            payment.mark_success(data.get("id", ""), payload)
            update_order_after_payment(payment)
        elif event_type == "charge:failed":
            payment.mark_failed(payload)
        else:
            payment.status = PaymentStatus.PROCESSING
            payment.webhook_payload = payload
            payment.save(update_fields=["status", "webhook_payload", "updated_at"])

    return JsonResponse({"received": True})
