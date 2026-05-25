import base64
import hashlib
import hmac
import json
from decimal import Decimal
from decimal import InvalidOperation

import requests
from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from .models import ManualCryptoWallet, PaymentGatewayConfig, PaymentMethod, PaymentStatus, PaymentTransaction


GATEWAY_DEFAULTS = {
    PaymentMethod.FLUTTERWAVE: {
        "display_name": "Flutterwave",
        "description": "Cards, bank transfer, USSD, and local methods",
        "icon_class": "fas fa-bolt text-orange-500",
        "display_order": 10,
    },
    PaymentMethod.PAYSTACK: {
        "display_name": "Paystack",
        "description": "Cards, bank transfer, USSD, and Nigerian payment methods",
        "icon_class": "fas fa-credit-card text-emerald-600",
        "display_order": 20,
    },
    PaymentMethod.PAYPAL: {
        "display_name": "PayPal",
        "description": "PayPal wallet and supported cards",
        "icon_class": "fab fa-paypal text-blue-600",
        "display_order": 30,
    },
    PaymentMethod.COINBASE: {
        "display_name": "Coinbase Commerce",
        "description": "Hosted crypto checkout",
        "icon_class": "fab fa-bitcoin text-yellow-500",
        "display_order": 40,
    },
    PaymentMethod.MANUAL_CRYPTO: {
        "display_name": "Manual Crypto Transfer",
        "description": "Transfer to a wallet and upload proof",
        "icon_class": "fas fa-wallet text-green-600",
        "display_order": 50,
    },
}


def _configured_secret(value):
    value = str(value or "").strip()
    if not value:
        return False
    lowered = value.lower()
    return not any(marker in lowered for marker in ("your_key", "xxxx", "placeholder", "change-me"))


def gateway_credentials_status(gateway):
    if gateway == PaymentMethod.FLUTTERWAVE:
        ok = _configured_secret(getattr(settings, "FLUTTERWAVE_SECRET_KEY", ""))
        return ok, "" if ok else "Add FLUTTERWAVE_SECRET_KEY to enable Flutterwave."
    if gateway == PaymentMethod.PAYSTACK:
        ok = _configured_secret(getattr(settings, "PAYSTACK_SECRET_KEY", ""))
        return ok, "" if ok else "Add PAYSTACK_SECRET_KEY to enable Paystack."
    if gateway == PaymentMethod.PAYPAL:
        ok = (
            _configured_secret(getattr(settings, "PAYPAL_CLIENT_ID", ""))
            and _configured_secret(getattr(settings, "PAYPAL_CLIENT_SECRET", ""))
        )
        return ok, "" if ok else "Add PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET to enable PayPal."
    if gateway == PaymentMethod.COINBASE:
        ok = _configured_secret(getattr(settings, "COINBASE_COMMERCE_API_KEY", ""))
        return ok, "" if ok else "Add COINBASE_COMMERCE_API_KEY to enable Coinbase Commerce."
    if gateway == PaymentMethod.MANUAL_CRYPTO:
        ok = ManualCryptoWallet.objects.filter(is_active=True).exists()
        return ok, "" if ok else "Add at least one active Manual Crypto Wallet."
    return False, "Unsupported payment gateway."


def get_gateway_options(include_inactive=False):
    configs = {config.gateway: config for config in PaymentGatewayConfig.objects.all()}
    options = []

    for gateway, defaults in GATEWAY_DEFAULTS.items():
        config = configs.get(gateway)
        is_active = config.is_active if config else True
        credentials_ok, disabled_reason = gateway_credentials_status(gateway)
        available = bool(is_active and credentials_ok)

        if not include_inactive and not is_active:
            continue

        options.append({
            "gateway": gateway,
            "display_name": config.display_name if config else defaults["display_name"],
            "description": config.description if config else defaults["description"],
            "icon_class": config.icon_class if config else defaults["icon_class"],
            "display_order": config.display_order if config else defaults["display_order"],
            "is_active": is_active,
            "available": available,
            "disabled_reason": "" if available else (disabled_reason or "This gateway is disabled."),
        })

    return sorted(options, key=lambda option: option["display_order"])


def gateway_is_available(gateway):
    for option in get_gateway_options(include_inactive=True):
        if option["gateway"] == gateway:
            return option["available"], option["disabled_reason"]
    return False, "Unsupported payment gateway."


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
    try:
        amount = Decimal(str(request.POST.get("amount", "0")).replace(",", "")).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        raise ValueError("Enter a valid payment amount.")

    if amount <= 0:
        raise ValueError("Payment amount must be greater than zero.")

    currency = (request.POST.get("currency") or getattr(settings, "AROLANA_DEFAULT_CURRENCY", "NGN")).upper()
    order_id = request.POST.get("order_id", "")
    customer = get_customer_data(request)

    if not customer["email"]:
        raise ValueError("Customer email is required before payment.")

    from orders.services import normalize_checkout_service_level

    checkout_data = {
        "address": request.POST.get("address", ""),
        "city": request.POST.get("city", ""),
        "state": request.POST.get("state", ""),
        "postal_code": request.POST.get("postal_code", ""),
        "country": request.POST.get("country", ""),
        "pickup_name": request.POST.get("pickup_name", ""),
        "pickup_phone": request.POST.get("pickup_phone", ""),
        "pickup_address": request.POST.get("pickup_address", ""),
        "pickup_latitude": request.POST.get("pickup_latitude", ""),
        "pickup_longitude": request.POST.get("pickup_longitude", ""),
        "pickup_vendor_id": request.POST.get("pickup_vendor_id", ""),
        "pickup_vendor_name": request.POST.get("pickup_vendor_name", ""),
        "dropoff_latitude": request.POST.get("dropoff_latitude", ""),
        "dropoff_longitude": request.POST.get("dropoff_longitude", ""),
        "package_weight_kg": request.POST.get("package_weight_kg", "0.00"),
        "delivery_service_level": normalize_checkout_service_level(request.POST.get("delivery_service_level", "standard")),
        "delivery_provider": "",
        "delivery_fee": request.POST.get("delivery_fee", "0.00"),
    }

    payment = PaymentTransaction.objects.create(
        user=request.user if request.user.is_authenticated else None,
        order_id=order_id,
        gateway=gateway,
        amount=amount,
        currency=currency,
        customer_email=customer["email"],
        customer_name=customer["name"],
        customer_phone=customer["phone"],
        checkout_data=checkout_data,
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


def verify_flutterwave_transaction_by_reference(tx_ref):
    secret_key = settings.FLUTTERWAVE_SECRET_KEY
    response = requests.get(
        "https://api.flutterwave.com/v3/transactions/verify_by_reference",
        params={"tx_ref": tx_ref},
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


def init_paystack_checkout(request, payment):
    secret_key = settings.PAYSTACK_SECRET_KEY
    callback_url = absolute_url(request, reverse("arolana_payments:callback", args=[payment.reference]))

    payload = {
        "email": payment.customer_email,
        "amount": int(payment.amount * 100),
        "currency": payment.currency,
        "reference": payment.reference,
        "callback_url": callback_url,
        "metadata": {
            "order_id": payment.order_id,
            "reference": payment.reference,
            "customer_name": payment.customer_name,
            "customer_phone": payment.customer_phone,
            "delivery": payment.checkout_data or {},
        },
    }

    response = requests.post(
        "https://api.paystack.co/transaction/initialize",
        json=payload,
        headers={
            "Authorization": f"Bearer {secret_key}",
            "Content-Type": "application/json",
        },
        timeout=30,
    )
    data = response.json()
    paystack_data = data.get("data", {})

    payment.gateway_reference = paystack_data.get("reference", payment.reference)
    payment.gateway_checkout_url = paystack_data.get("authorization_url", "")
    payment.gateway_response = data
    payment.status = PaymentStatus.PROCESSING
    payment.save(update_fields=["gateway_reference", "gateway_checkout_url", "gateway_response", "status", "updated_at"])
    return payment.gateway_checkout_url


def verify_paystack_transaction(reference):
    secret_key = settings.PAYSTACK_SECRET_KEY
    response = requests.get(
        f"https://api.paystack.co/transaction/verify/{reference}",
        headers={"Authorization": f"Bearer {secret_key}"},
        timeout=30,
    )
    return response.json()


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
