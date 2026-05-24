import json

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
    init_paystack_checkout,
    gateway_is_available,
    get_gateway_options,
    update_order_after_payment,
    verify_coinbase_signature,
    verify_flutterwave_transaction,
    verify_flutterwave_transaction_by_reference,
    verify_flutterwave_webhook,
    verify_paystack_transaction,
)

from orders.models import Cart, DeliveryProvider, Order


def checkout(request):
    """
    Payment selection page.

    Expected query params or POST fields:
    amount, currency, order_id, email, name, phone
    """
    wallets = ManualCryptoWallet.objects.filter(is_active=True)
    order_id = request.GET.get("order_id", request.POST.get("order_id", ""))
    delivery_origin = {}
    package_weight_kg = "0.00"
    if request.user.is_authenticated and str(order_id).isdigit():
        cart = Cart.objects.filter(id=int(order_id), user=request.user, is_active=True).prefetch_related("items__product__vendor").first()
        if cart:
            try:
                from deliveries.services import cart_package_weight_kg, cart_pickup_context
                delivery_origin = cart_pickup_context(cart)
                package_weight_kg = str(cart_package_weight_kg(cart))
            except Exception:
                delivery_origin = {}
    delivery_options = [
        {
            "value": "standard",
            "label": "Standard Delivery",
            "description": "Reliable delivery calculated by your location.",
            "icon": "fa-truck",
            "provider_type": "manual_dispatch",
        },
        {
            "value": "express",
            "label": "Express Delivery",
            "description": "Faster dispatch where available.",
            "icon": "fa-bolt",
            "provider_type": "arolana_driver",
        },
        {
            "value": "arolana_dispatch",
            "label": "Arolana Dispatch",
            "description": "Arolana riders or approved local dispatch riders.",
            "icon": "fa-motorcycle",
            "provider_type": "arolana_driver",
        },
        {
            "value": "pickup_from_vendor",
            "label": "Pickup from Vendor",
            "description": "Collect from the vendor after confirmation.",
            "icon": "fa-store",
            "provider_type": "vendor_pickup",
        },
    ]

    context = {
        "wallets": wallets,
        "payment_options": get_gateway_options(),
        "delivery_options": delivery_options,
        "delivery_providers": DeliveryProvider.objects.filter(is_active=True).exclude(provider_type="uber_direct"),
        "amount": request.GET.get("amount", request.POST.get("amount", "")),
        "currency": request.GET.get("currency", request.POST.get("currency", getattr(settings, "AROLANA_DEFAULT_CURRENCY", "NGN"))),
        "order_id": order_id,
        "email": request.GET.get("email", request.POST.get("email", "")),
        "name": request.GET.get("name", request.POST.get("name", "")),
        "phone": request.GET.get("phone", request.POST.get("phone", "")),
        "address": request.GET.get("address", request.POST.get("address", "")),
        "city": request.GET.get("city", request.POST.get("city", "")),
        "state": request.GET.get("state", request.POST.get("state", "")),
        "postal_code": request.GET.get("postal_code", request.POST.get("postal_code", "")),
        "country": request.GET.get("country", request.POST.get("country", "")),
        "delivery_service_level": request.GET.get("delivery_service_level", request.POST.get("delivery_service_level", "standard")),
        "delivery_provider": request.GET.get("delivery_provider", request.POST.get("delivery_provider", "")),
        "delivery_origin": delivery_origin,
        "package_weight_kg": package_weight_kg,
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
        elif gateway == PaymentMethod.PAYSTACK:
            url = init_paystack_checkout(request, payment)
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

    elif payment.gateway == PaymentMethod.PAYSTACK:
        reference_to_verify = request.GET.get("reference") or payment.gateway_reference or payment.reference
        if reference_to_verify:
            data = verify_paystack_transaction(reference_to_verify)
            if data.get("status") and data.get("data", {}).get("status") == "success":
                payment.mark_success(str(data.get("data", {}).get("reference", reference_to_verify)), data)
                update_order_after_payment(payment)
            else:
                payment.mark_failed(data)

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
    order = None
    delivery = None
    if payment.order_id:
        order = (
            Order.objects
            .filter(order_number=payment.order_id)
            .prefetch_related('delivery_requests__provider')
            .first()
        )
        if order:
            delivery = order.delivery_requests.order_by('-created_at').first()
    return render(request, "arolana_payments/status.html", {
        "payment": payment,
        "order": order,
        "delivery": delivery,
    })


@require_POST
def verify_payment(request, reference):
    payment = get_object_or_404(PaymentTransaction, reference=reference)

    if payment.status == PaymentStatus.SUCCESS:
        messages.info(request, "This payment is already confirmed.")
        return redirect("arolana_payments:status", reference=payment.reference)

    if payment.gateway == PaymentMethod.FLUTTERWAVE:
        data = verify_flutterwave_transaction_by_reference(payment.reference)
        transaction = data.get("data", {}) if isinstance(data, dict) else {}
        transaction_status = transaction.get("status")
        transaction_id = transaction.get("id") or transaction.get("tx_ref") or payment.reference

        if data.get("status") == "success" and transaction_status == "successful":
            payment.mark_success(str(transaction_id), data)
            update_order_after_payment(payment)
            messages.success(request, "Flutterwave payment confirmed. Your order and tracking are ready.")
        elif transaction_status in ["failed", "cancelled"]:
            payment.mark_failed(data)
            messages.error(request, "Flutterwave reported this payment as failed or cancelled.")
        else:
            payment.gateway_response = data
            payment.save(update_fields=["gateway_response", "updated_at"])
            messages.info(request, "Flutterwave has not confirmed this payment yet. Please wait a moment and try again.")
        return redirect("arolana_payments:status", reference=payment.reference)

    messages.info(request, "Manual verification is only available for Flutterwave on this page.")
    return redirect("arolana_payments:status", reference=payment.reference)


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
