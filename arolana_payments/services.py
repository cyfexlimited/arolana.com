import base64
import hashlib
import hmac
import json
from decimal import Decimal

import requests
import stripe
from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from .models import PaymentStatus, PaymentTransaction


def absolute_url(request, path):
    return request.build_absolute_uri(path)


def get_customer_data(request):
    user = getattr(request, "user", None)
    return {
        "email": request.POST.get("email") or (user.email if user and user.is_authenticated else ""),
        "name": request.POST.get("name") or (user.get_full_name() if user and user.is_authenticated else ""),
        "phone": request.POST.get("phone") or "",
    }


def create_transaction(request, gateway):
    amount = Decimal(str(request.POST.get("amount", "0"))).quantize(Decimal("0.01"))
    currency = (request.POST.get("currency") or getattr(settings, "AROLANA_DEFAULT_CURRENCY", "NGN")).upper()
    order_id = request.POST.get("order_id", "")
    customer = get_customer_data(request)

    payment = PaymentTransaction.objects.create(
        user=request.user if request.user.is_authenticated else None,
        order_id=order_id,
        gateway=gateway,
        amount=amount,
        currency=currency,
        customer_email=customer["email"],
        customer_name=customer["name"],
        customer_phone=customer["phone"],
    )
    return payment


def init_flutterwave_checkout(request, payment):
    secret_key = settings.FLUTTERWAVE_SECRET_KEY
    redirect_url = absolute_url(request, reverse("arolana_payments:callback", args=[payment.reference]))

    payload = {
        "tx_ref": payment.reference,
        "amount": str(payment.amount),
        "currency": payment.currency,
        "redirect_url": redirect_url,
        "customer": {
            "email": payment.customer_email,
            "name": payment.customer_name or payment.customer_email,
            "phonenumber": payment.customer_phone,
        },
        "customizations": {
            "title": "Arolana Payment",
            "description": f"Arolana order payment {payment.order_id or payment.reference}",
            "logo": getattr(settings, "AROLANA_PAYMENT_LOGO_URL", ""),
        },
        "meta": {
            "order_id": payment.order_id,
            "reference": payment.reference,
        },
    }

    response = requests.post(
        "https://api.flutterwave.com/v3/payments",
        json=payload,
        headers={
            "Authorization": f"Bearer {secret_key}",
            "Content-Type": "application/json",
        },
        timeout=30,
    )
    data = response.json()
    payment.gateway_response = data
    payment.status = PaymentStatus.PROCESSING

    checkout_url = data.get("data", {}).get("link", "")
    payment.gateway_checkout_url = checkout_url
    payment.save(update_fields=["gateway_response", "status", "gateway_checkout_url", "updated_at"])
    return checkout_url


def verify_flutterwave_transaction(transaction_id):
    secret_key = settings.FLUTTERWAVE_SECRET_KEY
    response = requests.get(
        f"https://api.flutterwave.com/v3/transactions/{transaction_id}/verify",
        headers={"Authorization": f"Bearer {secret_key}"},
        timeout=30,
    )
    return response.json()


def paypal_access_token():
    base = settings.PAYPAL_BASE_URL.rstrip("/")
    auth = (settings.PAYPAL_CLIENT_ID, settings.PAYPAL_CLIENT_SECRET)
    response = requests.post(
        f"{base}/v1/oauth2/token",
        data={"grant_type": "client_credentials"},
        auth=auth,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def init_paypal_checkout(request, payment):
    base = settings.PAYPAL_BASE_URL.rstrip("/")
    token = paypal_access_token()

    return_url = absolute_url(request, reverse("arolana_payments:callback", args=[payment.reference]))
    cancel_url = absolute_url(request, reverse("arolana_payments:cancel", args=[payment.reference]))

    payload = {
        "intent": "CAPTURE",
        "purchase_units": [{
            "reference_id": payment.reference,
            "description": f"Arolana order {payment.order_id or payment.reference}",
            "amount": {
                "currency_code": payment.currency,
                "value": str(payment.amount),
            },
        }],
        "application_context": {
            "brand_name": "Arolana",
            "landing_page": "LOGIN",
            "user_action": "PAY_NOW",
            "return_url": return_url,
            "cancel_url": cancel_url,
        },
    }

    response = requests.post(
        f"{base}/v2/checkout/orders",
        json=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        timeout=30,
    )
    data = response.json()

    payment.gateway_reference = data.get("id", "")
    payment.gateway_response = data
    payment.status = PaymentStatus.PROCESSING

    checkout_url = ""
    for link in data.get("links", []):
        if link.get("rel") == "approve":
            checkout_url = link.get("href")
            break

    payment.gateway_checkout_url = checkout_url
    payment.save(update_fields=["gateway_reference", "gateway_response", "status", "gateway_checkout_url", "updated_at"])
    return checkout_url


def capture_paypal_order(payment):
    base = settings.PAYPAL_BASE_URL.rstrip("/")
    token = paypal_access_token()
    response = requests.post(
        f"{base}/v2/checkout/orders/{payment.gateway_reference}/capture",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        timeout=30,
    )
    return response.json()


def init_stripe_checkout(request, payment):
    stripe.api_key = settings.STRIPE_SECRET_KEY

    success_url = absolute_url(request, reverse("arolana_payments:callback", args=[payment.reference])) + "?session_id={CHECKOUT_SESSION_ID}"
    cancel_url = absolute_url(request, reverse("arolana_payments:cancel", args=[payment.reference]))

    session = stripe.checkout.Session.create(
        mode="payment",
        payment_method_types=["card"],
        line_items=[{
            "price_data": {
                "currency": payment.currency.lower(),
                "product_data": {
                    "name": f"Arolana order {payment.order_id or payment.reference}",
                },
                "unit_amount": int(payment.amount * 100),
            },
            "quantity": 1,
        }],
        customer_email=payment.customer_email or None,
        metadata={
            "reference": payment.reference,
            "order_id": payment.order_id,
        },
        success_url=success_url,
        cancel_url=cancel_url,
    )

    payment.gateway_reference = session.id
    payment.gateway_checkout_url = session.url
    payment.gateway_response = dict(session)
    payment.status = PaymentStatus.PROCESSING
    payment.save(update_fields=["gateway_reference", "gateway_checkout_url", "gateway_response", "status", "updated_at"])
    return session.url


def init_coinbase_checkout(request, payment):
    api_key = settings.COINBASE_COMMERCE_API_KEY
    payload = {
        "name": "Arolana Payment",
        "description": f"Arolana order {payment.order_id or payment.reference}",
        "pricing_type": "fixed_price",
        "local_price": {
            "amount": str(payment.amount),
            "currency": payment.currency,
        },
        "metadata": {
            "reference": payment.reference,
            "order_id": payment.order_id,
        },
        "redirect_url": absolute_url(request, reverse("arolana_payments:callback", args=[payment.reference])),
        "cancel_url": absolute_url(request, reverse("arolana_payments:cancel", args=[payment.reference])),
    }

    response = requests.post(
        "https://api.commerce.coinbase.com/charges",
        json=payload,
        headers={
            "X-CC-Api-Key": api_key,
            "X-CC-Version": getattr(settings, "COINBASE_COMMERCE_API_VERSION", "2018-03-22"),
            "Content-Type": "application/json",
        },
        timeout=30,
    )
    data = response.json()
    charge = data.get("data", {})

    payment.gateway_reference = charge.get("id", "") or charge.get("code", "")
    payment.gateway_checkout_url = charge.get("hosted_url", "")
    payment.gateway_response = data
    payment.status = PaymentStatus.PROCESSING
    payment.save(update_fields=["gateway_reference", "gateway_checkout_url", "gateway_response", "status", "updated_at"])
    return payment.gateway_checkout_url


def verify_coinbase_signature(request_body, signature):
    webhook_secret = getattr(settings, "COINBASE_COMMERCE_WEBHOOK_SECRET", "")
    if not webhook_secret:
        return False
    digest = hmac.new(webhook_secret.encode(), request_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, signature or "")


def verify_flutterwave_webhook(request):
    secret_hash = getattr(settings, "FLUTTERWAVE_SECRET_HASH", "")
    if not secret_hash:
        return False
    return hmac.compare_digest(request.headers.get("verif-hash", ""), secret_hash)


def update_order_after_payment(payment):
    """
    Optional hook.

    In settings.py, you can define:
    AROLANA_PAYMENT_SUCCESS_HANDLER = "orders.services.mark_order_paid"

    The function will receive one argument: payment.
    """
    dotted_path = getattr(settings, "AROLANA_PAYMENT_SUCCESS_HANDLER", "")
    if not dotted_path:
        return

    module_path, function_name = dotted_path.rsplit(".", 1)
    module = __import__(module_path, fromlist=[function_name])
    handler = getattr(module, function_name)
    handler(payment)
