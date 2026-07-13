import base64
import hashlib
import hmac
import json
import os
from decimal import Decimal
from decimal import InvalidOperation
from decimal import ROUND_HALF_UP

import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from .models import (
    ManualCryptoWallet,
    PayPalWebhookLog,
    PaymentGatewayConfig,
    PaymentMethod,
    PaymentRefund,
    PaymentStatus,
    PaymentTransaction,
)


PAYPAL_SUPPORTED_CURRENCIES = {
    "AUD",
    "BRL",
    "CAD",
    "CHF",
    "CNY",
    "CZK",
    "DKK",
    "EUR",
    "GBP",
    "HKD",
    "HUF",
    "ILS",
    "JPY",
    "MXN",
    "MYR",
    "NOK",
    "NZD",
    "PHP",
    "PLN",
    "SEK",
    "SGD",
    "THB",
    "TWD",
    "USD",
}

PAYPAL_WEBHOOK_EVENT_TYPES = {
    "CHECKOUT.ORDER.APPROVED",
    "PAYMENT.CAPTURE.COMPLETED",
    "PAYMENT.CAPTURE.DENIED",
    "PAYMENT.CAPTURE.PENDING",
    "PAYMENT.CAPTURE.REFUNDED",
    "CUSTOMER.DISPUTE.CREATED",
    "CUSTOMER.DISPUTE.UPDATED",
}


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


def _paypal_setting(name, default=""):
    value = getattr(settings, name, None)
    if value in (None, ""):
        value = os.environ.get(name, default)
    return value if value not in (None, "") else default


def gateway_credentials_status(gateway):
    if gateway == PaymentMethod.FLUTTERWAVE:
        ok = _configured_secret(getattr(settings, "FLUTTERWAVE_SECRET_KEY", ""))
        return ok, "" if ok else "Add FLUTTERWAVE_SECRET_KEY to enable Flutterwave."
    if gateway == PaymentMethod.PAYSTACK:
        ok = _configured_secret(getattr(settings, "PAYSTACK_SECRET_KEY", ""))
        return ok, "" if ok else "Add PAYSTACK_SECRET_KEY to enable Paystack."
    if gateway == PaymentMethod.PAYPAL:
        client_ok = _configured_secret(_paypal_setting("PAYPAL_CLIENT_ID"))
        secret_ok = _configured_secret(_paypal_setting("PAYPAL_CLIENT_SECRET"))
        webhook_ok = _configured_secret(_paypal_setting("PAYPAL_WEBHOOK_ID"))
        ok = client_ok and secret_ok and webhook_ok
        if ok:
            return True, ""
        missing = []
        if not client_ok:
            missing.append("PAYPAL_CLIENT_ID")
        if not secret_ok:
            missing.append("PAYPAL_CLIENT_SECRET")
        if not webhook_ok:
            missing.append("PAYPAL_WEBHOOK_ID")
        return False, f"Add {', '.join(missing)} to enable verified PayPal payments."
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
    """
    Create a server-priced cart payment.

    The browser may submit contact and delivery destination fields, but it
    cannot define the payable amount, currency, cart ownership, or delivery
    fee.
    """
    if not request.user.is_authenticated:
        raise ValueError("Sign in before starting payment.")

    order_id = str(request.POST.get("order_id", "") or "").strip()
    if not order_id.isdigit():
        raise ValueError("A valid active cart is required before payment.")

    from orders import services as order_services

    cart = (
        order_services.Cart.objects
        .filter(
            id=int(order_id),
            user=request.user,
            is_active=True,
        )
        .prefetch_related("items")
        .first()
    )

    if not cart or not cart.items.exists():
        raise ValueError("Your active cart was not found or is empty.")

    customer = get_customer_data(request)
    customer["email"] = request.user.email or customer["email"]
    customer["name"] = (
        request.user.get_full_name()
        or getattr(request.user, "username", "")
        or customer["name"]
    )

    if not customer["email"]:
        raise ValueError("Customer email is required before payment.")

    service_level = order_services.normalize_checkout_service_level(
        request.POST.get("delivery_service_level", "standard")
    )

    checkout_data = {
        "purpose": "order",
        "source": "web_checkout",
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
        "delivery_service_level": service_level,
    }

    provider = order_services.select_delivery_provider(
        service_level,
        provider_id=None,
    )
    quote = order_services.calculate_delivery_quote(
        service_level=service_level,
        provider=provider,
        address=checkout_data["address"],
        city=checkout_data["city"],
        state=checkout_data["state"],
        postal_code=checkout_data["postal_code"],
        country=checkout_data["country"],
        subtotal=cart.subtotal,
    )

    requires_admin_quote = (
        order_services.requires_delivery_admin_quote(provider)
        or bool(quote.get("requires_admin_quote"))
    )

    if requires_admin_quote:
        delivery_fee = Decimal("0.00")
    else:
        try:
            delivery_fee = Decimal(
                str(quote.get("fee") or "0.00")
            ).quantize(Decimal("0.01"))
        except (InvalidOperation, TypeError, ValueError):
            raise ValueError("The server could not calculate a valid delivery fee.")

    amount = (
        Decimal(str(cart.subtotal))
        + delivery_fee
    ).quantize(Decimal("0.01"))

    if amount <= 0:
        raise ValueError("Payment amount must be greater than zero.")

    currency = str(
        getattr(cart, "currency", "")
        or getattr(settings, "AROLANA_DEFAULT_CURRENCY", "NGN")
    ).strip().upper()

    checkout_data.update({
        "delivery_provider": str(getattr(provider, "id", "") or ""),
        "delivery_fee": str(delivery_fee),
        "requires_admin_quote": requires_admin_quote,
        "server_cart_subtotal": str(
            Decimal(str(cart.subtotal)).quantize(Decimal("0.01"))
        ),
        "server_payment_total": str(amount),
    })

    payment = PaymentTransaction.objects.create(
        user=request.user,
        order_id=str(cart.id),
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


# =============================================================================
# STRICT FLUTTERWAVE PAYMENT VALIDATION
# =============================================================================


def validate_flutterwave_payment_response(payment, data):
    """
    Validate a Flutterwave verification response against the local payment.
    """

    if payment.gateway != PaymentMethod.FLUTTERWAVE:
        return False, "Payment gateway is not Flutterwave."

    if not isinstance(data, dict):
        return False, "Invalid Flutterwave verification response."

    transaction_data = data.get("data") or {}
    if not isinstance(transaction_data, dict):
        return False, "Invalid Flutterwave transaction data."

    if data.get("status") != "success":
        return False, "Flutterwave verification was not successful."

    if transaction_data.get("status") != "successful":
        return False, "Flutterwave transaction is not successful."

    verified_reference = str(
        transaction_data.get("tx_ref")
        or transaction_data.get("reference")
        or ""
    ).strip()

    if verified_reference != str(payment.reference or "").strip():
        return False, "Flutterwave transaction reference mismatch."

    try:
        verified_amount = Decimal(
            str(transaction_data.get("amount"))
        ).quantize(Decimal("0.01"))
        expected_amount = payment.amount_as_decimal.quantize(
            Decimal("0.01")
        )
    except (InvalidOperation, TypeError, ValueError):
        return False, "Invalid Flutterwave transaction amount."

    if verified_amount != expected_amount:
        return False, "Flutterwave transaction amount mismatch."

    verified_currency = str(
        transaction_data.get("currency") or ""
    ).strip().upper()

    expected_currency = str(
        payment.currency or ""
    ).strip().upper()

    if verified_currency != expected_currency:
        return False, "Flutterwave transaction currency mismatch."

    return True, ""


def verify_flutterwave_payment(payment, transaction_id=None):
    """
    Re-query Flutterwave and strictly bind the response to a local payment.
    """

    if transaction_id:
        data = verify_flutterwave_transaction(transaction_id)
    else:
        data = verify_flutterwave_transaction_by_reference(
            payment.reference
        )

    valid, error = validate_flutterwave_payment_response(
        payment,
        data,
    )

    if valid:
        return data

    if isinstance(data, dict):
        data = dict(data)
        data["validation_error"] = error
        return data

    return {
        "status": "error",
        "validation_error": error,
        "data": {},
    }

def paypal_access_token():
    base = settings.PAYPAL_BASE_URL.rstrip("/")
    auth = (settings.PAYPAL_CLIENT_ID, settings.PAYPAL_CLIENT_SECRET)
    response = requests.post(
        f"{base}/v1/oauth2/token",
        data={"grant_type": "client_credentials"},
        auth=auth,
        timeout=30,
    )
    try:
        data = response.json()
    except ValueError:
        data = {}
    if not response.ok or not data.get("access_token"):
        detail = data.get("error_description") or data.get("error") or "PayPal authentication failed."
        raise ValueError(detail)
    return data["access_token"]


def _paypal_header(headers, name):
    expected = name.lower().replace("_", "-")
    for key, value in (headers or {}).items():
        if str(key).lower().replace("_", "-") == expected:
            return str(value or "").strip()
    return ""


def verify_paypal_webhook_signature(headers, event):
    """
    Ask PayPal to verify the signed webhook transmission.

    PAYPAL_WEBHOOK_ID is the ID shown for the webhook in the PayPal developer
    dashboard. Client credentials alone cannot verify webhook signatures.
    """
    webhook_id = str(_paypal_setting("PAYPAL_WEBHOOK_ID") or "").strip()
    if not webhook_id:
        raise ValueError("PAYPAL_WEBHOOK_ID is not configured.")

    verification_payload = {
        "auth_algo": _paypal_header(headers, "PAYPAL-AUTH-ALGO"),
        "cert_url": _paypal_header(headers, "PAYPAL-CERT-URL"),
        "transmission_id": _paypal_header(headers, "PAYPAL-TRANSMISSION-ID"),
        "transmission_sig": _paypal_header(headers, "PAYPAL-TRANSMISSION-SIG"),
        "transmission_time": _paypal_header(headers, "PAYPAL-TRANSMISSION-TIME"),
        "webhook_id": webhook_id,
        "webhook_event": event,
    }
    missing = [
        key for key in (
            "auth_algo",
            "cert_url",
            "transmission_id",
            "transmission_sig",
            "transmission_time",
        )
        if not verification_payload[key]
    ]
    if missing:
        raise ValueError(f"Missing PayPal signature header(s): {', '.join(missing)}.")

    base = settings.PAYPAL_BASE_URL.rstrip("/")
    response = requests.post(
        f"{base}/v1/notifications/verify-webhook-signature",
        json=verification_payload,
        headers={
            "Authorization": f"Bearer {paypal_access_token()}",
            "Content-Type": "application/json",
        },
        timeout=30,
    )
    try:
        data = response.json()
    except ValueError:
        data = {}
    if not response.ok:
        raise ValueError(data.get("message") or "PayPal webhook verification request failed.")
    return data.get("verification_status") == "SUCCESS", data


def _paypal_resource(event):
    resource = (event or {}).get("resource")
    return resource if isinstance(resource, dict) else {}


def _paypal_related_ids(resource):
    related = ((resource.get("supplementary_data") or {}).get("related_ids") or {})
    return related if isinstance(related, dict) else {}


def _paypal_payment_candidates(event):
    resource = _paypal_resource(event)
    related = _paypal_related_ids(resource)
    references = {
        str(resource.get("invoice_id") or "").strip(),
        str(resource.get("custom_id") or "").strip(),
    }
    paypal_order_ids = {
        str(related.get("order_id") or "").strip(),
    }
    capture_ids = {
        str(related.get("capture_id") or "").strip(),
    }

    for purchase_unit in resource.get("purchase_units") or []:
        if not isinstance(purchase_unit, dict):
            continue
        references.update({
            str(purchase_unit.get("reference_id") or "").strip(),
            str(purchase_unit.get("invoice_id") or "").strip(),
            str(purchase_unit.get("custom_id") or "").strip(),
        })

    for disputed in resource.get("disputed_transactions") or []:
        if not isinstance(disputed, dict):
            continue
        capture_ids.update({
            str(disputed.get("seller_transaction_id") or "").strip(),
            str(disputed.get("buyer_transaction_id") or "").strip(),
        })

    event_type = str((event or {}).get("event_type") or "")
    resource_id = str(resource.get("id") or "").strip()
    if event_type.startswith("CHECKOUT.ORDER.") and resource_id:
        paypal_order_ids.add(resource_id)
    elif event_type.startswith("PAYMENT.CAPTURE.") and event_type != "PAYMENT.CAPTURE.REFUNDED" and resource_id:
        capture_ids.add(resource_id)

    return (
        {value for value in references if value},
        {value for value in paypal_order_ids if value},
        {value for value in capture_ids if value},
    )


def find_paypal_payment_for_event(event):
    references, paypal_order_ids, capture_ids = _paypal_payment_candidates(event)
    query = Q()
    if references:
        query |= Q(reference__in=references)
    if paypal_order_ids:
        query |= Q(gateway_reference__in=paypal_order_ids)
    if capture_ids:
        query |= Q(gateway_capture_id__in=capture_ids)
    if not query:
        return None
    return (
        PaymentTransaction.objects
        .select_for_update()
        .filter(gateway=PaymentMethod.PAYPAL)
        .filter(query)
        .order_by("-created_at")
        .first()
    )


def _paypal_event_amount(resource):
    amount = resource.get("amount") or resource.get("seller_payable_breakdown", {}).get("total_refunded_amount") or {}
    try:
        value = Decimal(str(amount.get("value") or "0")).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        value = Decimal("0.00")
    return value, str(amount.get("currency_code") or "").upper()


def _validate_paypal_capture(payment, resource):
    actual_amount, actual_currency = _paypal_event_amount(resource)
    settlement = (payment.gateway_response or {}).get("arolana_settlement") or {}
    try:
        expected_amount = Decimal(
            str(settlement.get("settlement_amount") or payment.amount)
        ).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        expected_amount = Decimal("0.00")
    expected_currency = str(
        settlement.get("settlement_currency") or payment.currency
    ).upper()

    if actual_amount <= 0 or actual_amount != expected_amount:
        raise ValueError(
            f"PayPal capture amount mismatch. Expected {expected_amount}, received {actual_amount}."
        )
    if not actual_currency or actual_currency != expected_currency:
        raise ValueError(
            f"PayPal capture currency mismatch. Expected {expected_currency}, received {actual_currency or 'blank'}."
        )


def _order_for_payment(payment):
    if not payment or not payment.order_id:
        return None
    from orders.models import Order

    order = Order.objects.filter(order_number=payment.order_id).first()
    if not order and str(payment.order_id).isdigit():
        order = Order.objects.filter(pk=int(payment.order_id)).first()
    return order


def _vendor_users_for_order(order):
    if not order:
        return []
    users = {}
    items = order.items.select_related(
        "product__vendor",
        "variant__product__vendor",
        "accessory",
    )
    for item in items:
        user = None
        if item.product_id:
            user = item.product.vendor
        elif item.variant_id and item.variant.product_id:
            user = item.variant.product.vendor
        elif item.accessory_id:
            accessory_product = getattr(item.accessory, "product", None)
            user = getattr(accessory_product, "vendor", None)
        if user and user.pk:
            users[user.pk] = user
    return list(users.values())


def _notify_users(users, *, title, message, link="", metadata=None, priority=2):
    from notifications.models import Notification

    created = []
    seen = set()
    for user in users:
        if not user or not user.pk or user.pk in seen:
            continue
        seen.add(user.pk)
        created.append(Notification.objects.create(
            user=user,
            notification_type="payment",
            title=title,
            message=message,
            link=link,
            metadata=metadata or {},
            priority=priority,
        ))
    return created


def _admin_users():
    User = get_user_model()
    return User.objects.filter(Q(is_staff=True) | Q(is_superuser=True), is_active=True).distinct()


def _payment_event_metadata(payment, order, event, capture_id=""):
    return {
        "payment_reference": payment.reference if payment else "",
        "paypal_order_id": payment.gateway_reference if payment else "",
        "paypal_capture_id": capture_id or (payment.gateway_capture_id if payment else ""),
        "order_id": order.id if order else None,
        "order_number": order.order_number if order else (payment.order_id if payment else ""),
        "paypal_event_id": event.get("id", ""),
        "paypal_event_type": event.get("event_type", ""),
    }


def _handle_paypal_capture_completed(payment, event):
    resource = _paypal_resource(event)

    if str(resource.get("status") or "").strip().upper() != "COMPLETED":
        raise ValueError(
            "PayPal capture webhook did not report COMPLETED status."
        )

    _validate_paypal_capture(payment, resource)
    capture_id = str(resource.get("id") or "").strip()
    paypal_order_id = str(_paypal_related_ids(resource).get("order_id") or "").strip()

    if not capture_id:
        raise ValueError(
            "PayPal capture ID is missing."
        )

    if not paypal_order_id:
        raise ValueError(
            "PayPal order ID is missing from capture webhook."
        )

    local_order_id = str(
        payment.gateway_reference or ""
    ).strip()

    if (
        local_order_id
        and paypal_order_id != local_order_id
    ):
        raise ValueError(
            "PayPal order identity mismatch."
        )

    local_capture_id = str(
        payment.gateway_capture_id or ""
    ).strip()

    if (
        local_capture_id
        and capture_id != local_capture_id
    ):
        raise ValueError(
            "PayPal capture identity mismatch."
        )

    event_references, _order_ids, _capture_ids = (
        _paypal_payment_candidates(event)
    )

    if (
        event_references
        and payment.reference not in event_references
    ):
        raise ValueError(
            "PayPal payment reference mismatch."
        )

    was_success = payment.status == PaymentStatus.SUCCESS
    payment.gateway_capture_id = capture_id
    payment.gateway_reference = paypal_order_id or payment.gateway_reference
    payment.webhook_payload = event
    payment.gateway_response = {
        **(payment.gateway_response or {}),
        "paypal_capture": resource,
        "paypal_last_webhook_event_id": event.get("id", ""),
    }
    payment.save(update_fields=[
        "gateway_capture_id",
        "gateway_reference",
        "webhook_payload",
        "gateway_response",
        "updated_at",
    ])
    if not was_success:
        payment.mark_success(payment.gateway_reference, event)

    order = _order_for_payment(payment)
    metadata = _payment_event_metadata(payment, order, event, capture_id)
    order_number = metadata["order_number"] or payment.reference
    customer_users = [order.user] if order and order.user_id else ([payment.user] if payment.user_id else [])
    _notify_users(
        customer_users,
        title="Payment confirmed",
        message=f"Your PayPal payment for order {order_number} was confirmed successfully.",
        link=f"/orders/{order_number}/" if order else "",
        metadata=metadata,
        priority=3,
    )
    _notify_users(
        _vendor_users_for_order(order),
        title="Customer payment confirmed",
        message=f"PayPal payment for order {order_number} has been confirmed.",
        link=f"/dashboard/vendor/order/{order.id}/" if order else "",
        metadata=metadata,
        priority=3,
    )
    _notify_users(
        _admin_users(),
        title="PayPal payment completed",
        message=f"Order {order_number} was paid through PayPal. Capture: {capture_id}.",
        link=f"/admin/orders/order/{order.id}/change/" if order else "/admin/arolana_payments/paymenttransaction/",
        metadata=metadata,
        priority=3,
    )
    return payment


def _handle_paypal_refund(payment, event):
    resource = _paypal_resource(event)
    refund_id = str(resource.get("id") or event.get("id") or "").strip()
    related = _paypal_related_ids(resource)
    capture_id = str(related.get("capture_id") or payment.gateway_capture_id or "").strip()
    amount, currency = _paypal_event_amount(resource)

    if amount <= 0:
        raise ValueError(
            "PayPal refund event did not include a valid amount."
        )

    local_capture_id = str(
        payment.gateway_capture_id or ""
    ).strip()

    if (
        local_capture_id
        and capture_id != local_capture_id
    ):
        raise ValueError(
            "PayPal refund capture identity mismatch."
        )

    settlement = (
        payment.gateway_response or {}
    ).get("arolana_settlement") or {}

    try:
        settlement_amount = Decimal(
            str(
                settlement.get("settlement_amount")
                or payment.amount
            )
        ).quantize(Decimal("0.01"))
    except (
        InvalidOperation,
        TypeError,
        ValueError,
    ):
        raise ValueError(
            "Invalid PayPal settlement amount."
        )

    settlement_currency = str(
        settlement.get("settlement_currency")
        or payment.currency
    ).strip().upper()

    if not currency or currency != settlement_currency:
        raise ValueError(
            "PayPal refund currency mismatch."
        )

    if amount > settlement_amount:
        raise ValueError(
            "PayPal refund amount exceeds captured settlement amount."
        )

    refund, _created = PaymentRefund.objects.update_or_create(
        gateway_refund_id=refund_id,
        defaults={
            "transaction": payment,
            "gateway": PaymentMethod.PAYPAL,
            "gateway_capture_id": capture_id,
            "order_id": payment.order_id,
            "amount": amount,
            "currency": currency or payment.currency,
            "status": str(resource.get("status") or "completed").lower(),
            "payload": event,
            "refunded_at": timezone.now(),
        },
    )
    total_refunded = sum(
        (
            Decimal(str(value))
            for value in (
                PaymentRefund.objects
                .filter(
                    transaction=payment,
                    gateway=PaymentMethod.PAYPAL,
                )
                .values_list("amount", flat=True)
            )
        ),
        Decimal("0.00"),
    ).quantize(Decimal("0.01"))

    if total_refunded > settlement_amount:
        raise ValueError(
            "Cumulative PayPal refunds exceed the captured settlement amount."
        )

    is_fully_refunded = (
        total_refunded >= settlement_amount
    )

    payment.webhook_payload = event

    if is_fully_refunded:
        payment.status = PaymentStatus.REFUNDED
        payment.save(
            update_fields=[
                "status",
                "webhook_payload",
                "updated_at",
            ]
        )
    else:
        payment.save(
            update_fields=[
                "webhook_payload",
                "updated_at",
            ]
        )

    order = _order_for_payment(payment)

    if order and is_fully_refunded:
        order.payment_status = "refunded"
        order.status = "refunded"
        order.save(
            update_fields=[
                "payment_status",
                "status",
                "updated_at",
            ]
        )

    metadata = _payment_event_metadata(payment, order, event, capture_id)
    metadata["paypal_refund_id"] = refund_id
    metadata["refund_record_id"] = refund.pk
    metadata["refund_amount"] = str(amount)
    metadata["refund_currency"] = currency
    order_number = metadata["order_number"] or payment.reference
    customer_users = [order.user] if order and order.user_id else ([payment.user] if payment.user_id else [])
    _notify_users(
        customer_users,
        title="PayPal refund completed",
        message=f"Your refund of {amount} {currency} for order {order_number} has been recorded.",
        link=f"/orders/{order_number}/" if order else "",
        metadata=metadata,
        priority=3,
    )
    _notify_users(
        _admin_users(),
        title="PayPal payment refunded",
        message=f"PayPal refunded {amount} {currency} for order {order_number}.",
        link=f"/admin/arolana_payments/paymentrefund/{refund.pk}/change/",
        metadata=metadata,
        priority=4,
    )
    return payment


@transaction.atomic
def process_paypal_webhook(log_id):
    log = PayPalWebhookLog.objects.select_for_update().get(pk=log_id)
    if log.status in [PayPalWebhookLog.STATUS_PROCESSED, PayPalWebhookLog.STATUS_IGNORED]:
        return log
    if not log.signature_verified:
        raise ValueError("PayPal webhook signature has not been verified.")

    log.attempts += 1
    event = log.payload or {}
    event_type = str(event.get("event_type") or "")
    payment = find_paypal_payment_for_event(event)
    log.payment = payment

    if event_type not in PAYPAL_WEBHOOK_EVENT_TYPES:
        log.status = PayPalWebhookLog.STATUS_IGNORED
        log.processed_at = timezone.now()
        log.last_error = ""
        log.save(update_fields=["attempts", "payment", "status", "processed_at", "last_error", "updated_at"])
        return log

    if event_type.startswith(("CHECKOUT.ORDER.", "PAYMENT.CAPTURE.")) and not payment:
        raise ValueError("No Arolana PayPal transaction matches this webhook event.")

    resource = _paypal_resource(event)
    if event_type == "CHECKOUT.ORDER.APPROVED":
        if payment.status not in [PaymentStatus.SUCCESS, PaymentStatus.REFUNDED]:
            payment.status = PaymentStatus.PROCESSING
        payment.webhook_payload = event
        payment.save(update_fields=["status", "webhook_payload", "updated_at"])
    elif event_type == "PAYMENT.CAPTURE.COMPLETED":
        _handle_paypal_capture_completed(payment, event)
    elif event_type == "PAYMENT.CAPTURE.DENIED":
        if payment.status not in [PaymentStatus.SUCCESS, PaymentStatus.REFUNDED]:
            payment.mark_failed(event)
        order = _order_for_payment(payment)
        metadata = _payment_event_metadata(payment, order, event)
        order_number = metadata["order_number"] or payment.reference
        customer_users = [order.user] if order and order.user_id else ([payment.user] if payment.user_id else [])
        _notify_users(
            customer_users,
            title="PayPal payment was denied",
            message=f"PayPal could not complete payment for order {order_number}. Please try again or choose another payment method.",
            link=f"/orders/{order_number}/" if order else "",
            metadata=metadata,
            priority=3,
        )
        _notify_users(
            _admin_users(),
            title="PayPal capture denied",
            message=f"PayPal denied payment capture for order {order_number}.",
            link="/admin/arolana_payments/paymenttransaction/",
            metadata=metadata,
            priority=4,
        )
    elif event_type == "PAYMENT.CAPTURE.PENDING":
        if payment.status not in [PaymentStatus.SUCCESS, PaymentStatus.REFUNDED]:
            payment.status = PaymentStatus.PROCESSING
            payment.webhook_payload = event
            payment.save(update_fields=["status", "webhook_payload", "updated_at"])
    elif event_type == "PAYMENT.CAPTURE.REFUNDED":
        _handle_paypal_refund(payment, event)
    elif event_type in ["CUSTOMER.DISPUTE.CREATED", "CUSTOMER.DISPUTE.UPDATED"]:
        if payment and payment.status != PaymentStatus.REFUNDED:
            payment.status = PaymentStatus.REVIEW
            payment.webhook_payload = event
            payment.save(update_fields=["status", "webhook_payload", "updated_at"])
        order = _order_for_payment(payment)
        metadata = _payment_event_metadata(payment, order, event)
        dispute_id = str(resource.get("dispute_id") or resource.get("id") or "")
        metadata["paypal_dispute_id"] = dispute_id
        order_number = metadata["order_number"] or "unknown order"
        _notify_users(
            _admin_users(),
            title="Urgent PayPal dispute update",
            message=f"{event_type.replace('.', ' ').title()} for {order_number}. Dispute: {dispute_id}.",
            link="/admin/arolana_payments/paypalwebhooklog/",
            metadata=metadata,
            priority=4,
        )
        if order and order.user_id:
            _notify_users(
                [order.user],
                title="PayPal dispute update",
                message=f"A PayPal dispute linked to order {order.order_number} has been recorded. Arolana support will review it.",
                link=f"/orders/{order.order_number}/",
                metadata=metadata,
                priority=3,
            )

    log.status = PayPalWebhookLog.STATUS_PROCESSED
    log.processed_at = timezone.now()
    log.last_error = ""
    log.save(update_fields=["attempts", "payment", "status", "processed_at", "last_error", "updated_at"])
    return log


def _paypal_settlement(payment):
    original_currency = str(payment.currency or "NGN").upper()
    original_amount = Decimal(str(payment.amount or "0")).quantize(Decimal("0.01"))
    if original_currency in PAYPAL_SUPPORTED_CURRENCIES:
        return original_amount, original_currency, Decimal("1")

    settlement_currency = str(_paypal_setting("PAYPAL_SETTLEMENT_CURRENCY", "USD") or "USD").upper()
    if settlement_currency not in PAYPAL_SUPPORTED_CURRENCIES:
        settlement_currency = "USD"

    converted = None
    try:
        from currency.models import Currency
        from currency.utils.exchange_rates import CurrencyConverter

        source = Currency.objects.filter(code=original_currency, is_active=True).first()
        target = Currency.objects.filter(code=settlement_currency, is_active=True).first()
        if source and target:
            converted = CurrencyConverter.convert(original_amount, source, target)
    except Exception:
        converted = None

    if converted is None or converted <= 0:
        if original_currency != "NGN" or settlement_currency != "USD":
            raise ValueError(
                f"PayPal does not support {original_currency}. Configure an exchange rate for "
                f"{original_currency} to {settlement_currency}."
            )
        ngn_per_usd = Decimal(str(_paypal_setting("PAYPAL_NGN_PER_USD", "1500") or "1500"))
        if ngn_per_usd <= 0:
            raise ValueError("PAYPAL_NGN_PER_USD must be greater than zero.")
        converted = original_amount / ngn_per_usd

    settlement_amount = Decimal(str(converted)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if settlement_amount <= 0:
        raise ValueError("The converted PayPal amount is too small to process.")
    rate = (settlement_amount / original_amount).quantize(Decimal("0.00000001"))
    return settlement_amount, settlement_currency, rate


def init_paypal_checkout(request, payment):
    base = settings.PAYPAL_BASE_URL.rstrip("/")
    token = paypal_access_token()
    settlement_amount, settlement_currency, conversion_rate = _paypal_settlement(payment)

    return_url = absolute_url(request, reverse("arolana_payments:callback", args=[payment.reference]))
    cancel_url = absolute_url(
    request,
    reverse(
        "arolana_payments:status",
        args=[payment.reference],
    ),
)

    payload = {
        "intent": "CAPTURE",
        "purchase_units": [{
            "reference_id": payment.reference,
            "description": f"Arolana order {payment.order_id or payment.reference}",
            "amount": {
                "currency_code": settlement_currency,
                "value": f"{settlement_amount:.2f}",
            },
        }],
        "application_context": {
            "brand_name": _paypal_setting("PAYPAL_BRAND_NAME", "Arolana Marketplace"),
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
    try:
        data = response.json()
    except ValueError:
        data = {}
    if not response.ok:
        details = data.get("details") or []
        detail = details[0].get("description") if details and isinstance(details[0], dict) else ""
        raise ValueError(detail or data.get("message") or "PayPal could not initialize checkout.")

    payment.gateway_reference = data.get("id", "")
    payment.gateway_response = {
        **data,
        "arolana_settlement": {
            "original_amount": str(payment.amount),
            "original_currency": str(payment.currency).upper(),
            "settlement_amount": f"{settlement_amount:.2f}",
            "settlement_currency": settlement_currency,
            "conversion_rate": str(conversion_rate),
        },
    }
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
    try:
        data = response.json()
    except ValueError:
        data = {}
    if not response.ok and data.get("name") != "ORDER_ALREADY_CAPTURED":
        details = data.get("details") or []
        detail = details[0].get("description") if details and isinstance(details[0], dict) else ""
        raise ValueError(detail or data.get("message") or "PayPal could not verify this payment.")
    return data


def record_paypal_capture_response(payment, data):
    """
    Validate and persist PayPal's synchronous capture response.

    This response never finalizes the Arolana payment. The signed
    PAYMENT.CAPTURE.COMPLETED webhook remains authoritative.
    """
    if payment.gateway != PaymentMethod.PAYPAL:
        raise ValueError("Payment gateway is not PayPal.")

    if not isinstance(data, dict):
        raise ValueError("Invalid PayPal capture response.")

    if str(data.get("status") or "").strip().upper() != "COMPLETED":
        raise ValueError("PayPal capture response is not completed.")

    paypal_order_id = str(data.get("id") or "").strip()
    local_order_id = str(payment.gateway_reference or "").strip()

    if not paypal_order_id:
        raise ValueError("PayPal order ID is missing from capture response.")

    if not local_order_id or paypal_order_id != local_order_id:
        raise ValueError("PayPal capture response order identity mismatch.")

    purchase_units = data.get("purchase_units") or []

    if not isinstance(purchase_units, list) or len(purchase_units) != 1:
        raise ValueError("PayPal capture response must contain exactly one purchase unit.")

    purchase_unit = purchase_units[0]

    if not isinstance(purchase_unit, dict):
        raise ValueError("Invalid PayPal purchase unit.")

    reference_id = str(purchase_unit.get("reference_id") or "").strip()

    if reference_id and reference_id != payment.reference:
        raise ValueError("PayPal capture response reference mismatch.")

    payments = purchase_unit.get("payments") or {}
    captures = payments.get("captures") or []

    if not isinstance(captures, list) or len(captures) != 1:
        raise ValueError("PayPal capture response must contain exactly one capture.")

    capture = captures[0]

    if not isinstance(capture, dict):
        raise ValueError("Invalid PayPal capture object.")

    if str(capture.get("status") or "").strip().upper() != "COMPLETED":
        raise ValueError("PayPal capture object is not completed.")

    _validate_paypal_capture(payment, capture)

    capture_id = str(capture.get("id") or "").strip()

    if not capture_id:
        raise ValueError("PayPal capture ID is missing.")

    local_capture_id = str(payment.gateway_capture_id or "").strip()

    if local_capture_id and capture_id != local_capture_id:
        raise ValueError("PayPal capture response identity mismatch.")

    payment.gateway_capture_id = capture_id
    payment.gateway_response = {
        **(payment.gateway_response or {}),
        "paypal_capture_response": data,
    }

    if payment.status not in [
        PaymentStatus.SUCCESS,
        PaymentStatus.REFUNDED,
    ]:
        payment.status = PaymentStatus.PROCESSING

    payment.save(
        update_fields=[
            "gateway_capture_id",
            "gateway_response",
            "status",
            "updated_at",
        ]
    )

    return capture_id


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
        "cancel_url": absolute_url(
    request,
    reverse(
        "arolana_payments:status",
        args=[payment.reference],
    ),
),
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
    """
    Verify Flutterwave webhook signatures.

    Prefer the current HMACSHA256 Base64 signature scheme.
    Retain the legacy verif-hash fallback for older v3 webhook
    delivery while the integration is being migrated.
    """

    secret_hash = str(
        getattr(settings, "FLUTTERWAVE_SECRET_HASH", "") or ""
    ).strip()

    if not secret_hash:
        return False

    signature = str(
        request.headers.get("flutterwave-signature", "") or ""
    ).strip()

    if signature:
        expected = base64.b64encode(
            hmac.new(
                secret_hash.encode("utf-8"),
                request.body,
                hashlib.sha256,
            ).digest()
        ).decode("ascii")

        return hmac.compare_digest(
            expected,
            signature,
        )

    legacy_signature = str(
        request.headers.get("verif-hash", "") or ""
    ).strip()

    return bool(legacy_signature) and hmac.compare_digest(
        legacy_signature,
        secret_hash,
    )

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

def validate_paystack_payment_response(payment, data):
    """
    Validate a successful Paystack verification response against
    the Arolana PaymentTransaction being fulfilled.
    """

    if not isinstance(data, dict):
        return False, "Invalid Paystack verification response."

    transaction_data = data.get("data") or {}

    if data.get("status") is not True:
        return False, "Paystack verification was not successful."

    if transaction_data.get("status") != "success":
        return False, "Paystack transaction is not successful."

    verified_reference = str(
        transaction_data.get("reference") or ""
    ).strip()

    expected_references = {
        str(payment.reference or "").strip(),
        str(payment.gateway_reference or "").strip(),
    }

    expected_references.discard("")

    if verified_reference not in expected_references:
        return False, "Paystack transaction reference mismatch."

    try:
        verified_amount = int(
            transaction_data.get("amount")
        )
    except (TypeError, ValueError):
        return False, "Invalid Paystack transaction amount."

    expected_amount = int(
        payment.amount_as_decimal * 100
    )

    if verified_amount != expected_amount:
        return False, "Paystack transaction amount mismatch."

    verified_currency = str(
        transaction_data.get("currency") or ""
    ).strip().upper()

    expected_currency = str(
        payment.currency or ""
    ).strip().upper()

    if verified_currency != expected_currency:
        return False, "Paystack transaction currency mismatch."

    return True, ""


def verify_paystack_payment(payment):
    """
    Verify only the Paystack reference stored on the Arolana
    PaymentTransaction and validate reference, amount, and currency.
    """

    reference = str(
        payment.gateway_reference
        or payment.reference
        or ""
    ).strip()

    data = verify_paystack_transaction(reference)

    transaction_data = (
        data.get("data") or {}
        if isinstance(data, dict)
        else {}
    )

    is_successful = (
        isinstance(data, dict)
        and data.get("status") is True
        and transaction_data.get("status") == "success"
    )

    if not is_successful:
        return data

    valid, validation_error = (
        validate_paystack_payment_response(
            payment,
            data,
        )
    )

    if valid:
        return data

    rejected_data = dict(data)

    rejected_data["status"] = False
    rejected_data["validation_error"] = (
        validation_error
    )

    return rejected_data

def fulfill_successful_payment(payment_id):
    """
    Fulfill a successful order payment exactly once.

    Non-order payment purposes are intentionally ignored here.
    Vendor and provider subscriptions have their own fulfillment
    services so payment success and subscription activation remain
    auditable and independently retryable.
    """
    from django.db import transaction
    from django.utils import timezone as django_timezone

    from .models import (
        PaymentStatus,
        PaymentTransaction,
    )

    try:
        with transaction.atomic():
            payment = (
                PaymentTransaction.objects
                .select_for_update()
                .get(pk=payment_id)
            )

            if payment.status != PaymentStatus.SUCCESS:
                return None

            checkout_data = payment.checkout_data or {}

            purpose = str(
                checkout_data.get("purpose") or ""
            ).strip().lower()

            # Empty purpose remains backwards-compatible with
            # existing order checkout transactions.
            if purpose and purpose != "order":
                return None

            if payment.fulfilled_at:
                return None

            payment.fulfillment_attempts += 1
            payment.fulfillment_error = ""

            payment.save(
                update_fields=[
                    "fulfillment_attempts",
                    "fulfillment_error",
                    "updated_at",
                ]
            )

            result = update_order_after_payment(
                payment
            )

            payment.fulfilled_at = (
                django_timezone.now()
            )

            payment.fulfillment_error = ""

            payment.save(
                update_fields=[
                    "fulfilled_at",
                    "fulfillment_error",
                    "updated_at",
                ]
            )

            return result

    except Exception as exc:
        # The original atomic block rolls back, including its attempt
        # increment. Record the failed attempt separately.
        with transaction.atomic():
            failed_payment = (
                PaymentTransaction.objects
                .select_for_update()
                .get(pk=payment_id)
            )

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

def dispatch_successful_payment(payment_id):
    from .models import PaymentTransaction

    payment = (
        PaymentTransaction.objects
        .only(
            "id",
            "checkout_data",
        )
        .get(pk=payment_id)
    )

    purpose = str(
        (payment.checkout_data or {}).get("purpose")
        or "order"
    ).strip().lower()

    if purpose == "vendor_subscription":
        from subscriptions.services import (
            activate_vendor_subscription_payment,
        )

        return activate_vendor_subscription_payment(
            payment_id
        )

    if purpose == "provider_subscription":
        from installers.subscription_services import (
            activate_provider_subscription_payment,
        )

        return activate_provider_subscription_payment(
            payment_id
        )

    return fulfill_successful_payment(
        payment_id
    )

# =============================================================================
# PAYSTACK WEBHOOK SIGNATURE VERIFICATION
# =============================================================================


def verify_paystack_webhook_signature(request_body, signature):
    """
    Verify Paystack's x-paystack-signature using HMAC-SHA512
    over the exact raw request body.
    """
    secret_key = str(
        getattr(settings, "PAYSTACK_SECRET_KEY", "") or ""
    ).strip()

    signature = str(signature or "").strip()

    if not secret_key or not signature:
        return False

    expected = hmac.new(
        secret_key.encode("utf-8"),
        request_body,
        hashlib.sha512,
    ).hexdigest()

    return hmac.compare_digest(
        expected,
        signature,
    )
