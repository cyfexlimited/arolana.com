import hashlib
import json
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import F
from django.http import (
    HttpResponseBadRequest,
    JsonResponse,
)
from django.shortcuts import (
    get_object_or_404,
    redirect,
    render,
)
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import (
    require_GET,
    require_POST,
)

from orders.models import Cart, Order
from orders.services import normalize_checkout_service_level

from .models import (
    ManualCryptoWallet,
    PayPalWebhookLog,
    PaymentMethod,
    PaymentStatus,
    PaymentTransaction,
)
from .services import (
    capture_paypal_order,
    create_transaction,
    gateway_is_available,
    get_gateway_options,
    init_coinbase_checkout,
    init_flutterwave_checkout,
    init_paypal_checkout,
    init_paystack_checkout,
    process_paypal_webhook,
    record_paypal_capture_response,
    verify_coinbase_signature,
    verify_flutterwave_transaction,
    verify_flutterwave_transaction_by_reference,
    verify_flutterwave_webhook,
    verify_paypal_webhook_signature,
    verify_paystack_transaction,
)


# =============================================================================
# CONSTANTS
# =============================================================================


MOBILE_HOSTED_PAYMENT_METHODS = {
    PaymentMethod.FLUTTERWAVE,
    PaymentMethod.PAYPAL,
    PaymentMethod.PAYSTACK,
    PaymentMethod.COINBASE,
}


# =============================================================================
# JSON HELPERS
# =============================================================================


def _json_body(request):
    try:
        return json.loads(
            request.body.decode("utf-8")
            or "{}"
        )

    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ):
        return {}


def _json_error(
    message,
    status=400,
):
    return JsonResponse(
        {
            "success": False,
            "message": str(message),
            "error": str(message),
        },
        status=status,
    )


# =============================================================================
# VALIDATION HELPERS
# =============================================================================


def _validation_error_messages(
    exc: ValidationError,
):
    if hasattr(
        exc,
        "message_dict",
    ):
        output = []

        for (
            field_name,
            field_errors,
        ) in exc.message_dict.items():
            for error in field_errors:
                output.append(
                    f"{field_name}: {error}"
                )

        return output

    return [
        str(message)
        for message in exc.messages
    ]


def _validate_payment_proof(upload):
    """
    Run the validators configured directly on:

        PaymentTransaction.manual_proof

    This keeps the model field as the source of truth for accepted file
    extensions, signatures, sizes, and content verification.
    """

    field = (
        PaymentTransaction
        ._meta
        .get_field(
            "manual_proof"
        )
    )

    field.run_validators(
        upload
    )

    try:
        upload.seek(0)

    except Exception:
        pass


# =============================================================================
# MOBILE PAYMENT OPTIONS
# =============================================================================


@require_GET
def mobile_payment_options_api(request):
    options = [
        option
        for option in get_gateway_options()
        if (
            option.get("available")
            and option.get("gateway")
            in MOBILE_HOSTED_PAYMENT_METHODS
        )
    ]

    return JsonResponse(
        {
            "success": True,
            "payment_options": options,
        }
    )


# =============================================================================
# PAYPAL HELPERS
# =============================================================================


def _paypal_request_headers(request):
    return {
        "PAYPAL-AUTH-ALGO": request.headers.get(
            "PAYPAL-AUTH-ALGO",
            "",
        ),
        "PAYPAL-CERT-URL": request.headers.get(
            "PAYPAL-CERT-URL",
            "",
        ),
        "PAYPAL-TRANSMISSION-ID": request.headers.get(
            "PAYPAL-TRANSMISSION-ID",
            "",
        ),
        "PAYPAL-TRANSMISSION-SIG": request.headers.get(
            "PAYPAL-TRANSMISSION-SIG",
            "",
        ),
        "PAYPAL-TRANSMISSION-TIME": request.headers.get(
            "PAYPAL-TRANSMISSION-TIME",
            "",
        ),
        "USER-AGENT": request.headers.get(
            "USER-AGENT",
            "",
        ),
    }


# =============================================================================
# GENERAL CLEANING HELPERS
# =============================================================================


def _clean_phone(value):
    return "".join(
        character
        for character in str(
            value
            or ""
        )
        if (
            character.isdigit()
            or character == "+"
        )
    ).strip()


def _clean_text(value):
    return str(
        value
        or ""
    ).strip()


# =============================================================================
# MOBILE CUSTOMER AUTHENTICATION
# =============================================================================


def _mobile_customer_from_payload(
    payload,
):
    try:
        from mobile_customers.models import (
            MobileCustomer,
        )

    except Exception as error:
        raise RuntimeError(
            (
                "Mobile customer accounts are required "
                "before mobile payments can work."
            )
        ) from error

    mobile_payload = (
        payload.get(
            "mobile_customer"
        )
        or {}
    )

    customer_payload = (
        payload.get(
            "customer"
        )
        or {}
    )

    phone_number = _clean_phone(
        payload.get(
            "phone"
        )
        or payload.get(
            "phone_number"
        )
        or mobile_payload.get(
            "phone_number"
        )
        or mobile_payload.get(
            "phoneNumber"
        )
        or customer_payload.get(
            "phone_number"
        )
        or customer_payload.get(
            "phoneNumber"
        )
    )

    api_token = _clean_text(
        payload.get(
            "api_token"
        )
        or payload.get(
            "apiToken"
        )
        or mobile_payload.get(
            "api_token"
        )
        or mobile_payload.get(
            "apiToken"
        )
    )

    if not phone_number:
        raise ValueError(
            "Phone number is required."
        )

    if not api_token:
        raise PermissionError(
            (
                "Login token is required. "
                "Login/register again."
            )
        )

    customer = (
        MobileCustomer.objects
        .select_related(
            "user"
        )
        .filter(
            phone_number=phone_number,
            api_token=api_token,
            is_active=True,
        )
        .first()
    )

    if not customer:
        raise PermissionError(
            (
                "Invalid login token. "
                "Login/register again."
            )
        )

    return customer


# =============================================================================
# MOBILE ORDER OWNERSHIP
# =============================================================================


def _mobile_order_for_customer(
    payload,
    customer,
):
    order_id = (
        payload.get(
            "order_id"
        )
        or payload.get(
            "id"
        )
    )

    order_number = (
        payload.get(
            "order_number"
        )
        or payload.get(
            "orderNumber"
        )
    )

    lookup = None

    if order_id:
        lookup = Order.objects.filter(
            id=order_id
        )

    if order_number:
        number_lookup = (
            Order.objects.filter(
                order_number=order_number
            )
        )

        lookup = (
            number_lookup
            if lookup is None
            else (
                lookup
                | number_lookup
            )
        )

    if lookup is None:
        raise ValueError(
            (
                "Order ID or order number "
                "is required."
            )
        )

    ownership = Order.objects.none()

    if getattr(
        customer,
        "user_id",
        None,
    ):
        ownership = (
            Order.objects.filter(
                user=customer.user
            )
        )

    if hasattr(
        Order,
        "customer_phone",
    ):
        ownership = (
            ownership
            | Order.objects.filter(
                customer_phone=(
                    customer.phone_number
                )
            )
        )

    order = (
        lookup
        .filter(
            id__in=ownership.values(
                "id"
            )
        )
        .distinct()
        .first()
    )

    if not order:
        raise PermissionError(
            (
                "Order was not found "
                "for this customer."
            )
        )

    return order


# =============================================================================
# MOBILE PAYMENT HELPERS
# =============================================================================


def _mobile_gateway(gateway):
    gateway = _clean_text(
        gateway
        or PaymentMethod.PAYSTACK
    ).lower()

    if (
        gateway not in PaymentMethod.values
        or gateway
        not in MOBILE_HOSTED_PAYMENT_METHODS
    ):
        raise ValueError(
            (
                "Choose a supported secure "
                "payment gateway."
            )
        )

    return gateway


def _order_amount(order):
    try:
        amount = Decimal(
            str(
                getattr(
                    order,
                    "total",
                    "0",
                )
                or "0"
            ).replace(
                ",",
                "",
            )
        ).quantize(
            Decimal(
                "0.01"
            )
        )

    except (
        InvalidOperation,
        ValueError,
        TypeError,
    ):
        amount = Decimal(
            "0.00"
        )

    if amount <= 0:
        raise ValueError(
            (
                "Order total must be greater "
                "than zero before payment."
            )
        )

    return amount


def _mobile_order_payload(
    request,
    order,
):
    try:
        from orders.views import (
            _mobile_order_payload
            as payload_builder,
        )

        return payload_builder(
            request,
            order,
        )

    except Exception:
        return {
            "id": order.id,
            "order_number": (
                order.order_number
            ),
            "status": order.status,
            "payment_method": (
                order.payment_method
            ),
            "payment_status": (
                order.payment_status
            ),
            "subtotal": str(
                order.subtotal
            ),
            "shipping_cost": str(
                order.shipping_cost
            ),
            "delivery_fee": str(
                order.shipping_cost
            ),
            "tax": str(
                order.tax
            ),
            "total": str(
                order.total
            ),
            "created_at": (
                order.created_at.isoformat()
                if order.created_at
                else ""
            ),
        }


def _hosted_checkout_url(
    request,
    payment,
):
    if (
        payment.gateway
        == PaymentMethod.FLUTTERWAVE
    ):
        return init_flutterwave_checkout(
            request,
            payment,
        )

    if (
        payment.gateway
        == PaymentMethod.PAYPAL
    ):
        return init_paypal_checkout(
            request,
            payment,
        )

    if (
        payment.gateway
        == PaymentMethod.PAYSTACK
    ):
        return init_paystack_checkout(
            request,
            payment,
        )

    if (
        payment.gateway
        == PaymentMethod.COINBASE
    ):
        return init_coinbase_checkout(
            request,
            payment,
        )

    raise ValueError(
        "Unsupported payment gateway."
    )


# =============================================================================
# VERIFY PAYMENT AGAINST GATEWAY
# =============================================================================


def _verify_transaction_now(payment):
    if (
        payment.status
        == PaymentStatus.SUCCESS
    ):
        return (
            True,
            "Payment is already confirmed.",
            (
                payment.webhook_payload
                or payment.gateway_response
            ),
        )

    # -------------------------------------------------------------------------
    # FLUTTERWAVE
    # -------------------------------------------------------------------------

    if (
        payment.gateway
        == PaymentMethod.FLUTTERWAVE
    ):
        data = (
            verify_flutterwave_transaction_by_reference(
                payment.reference
            )
        )

        transaction_data = (
            data.get(
                "data",
                {},
            )
            if isinstance(
                data,
                dict,
            )
            else {}
        )

        transaction_status = (
            transaction_data.get(
                "status"
            )
        )

        transaction_id = (
            transaction_data.get(
                "id"
            )
            or transaction_data.get(
                "tx_ref"
            )
            or payment.reference
        )

        if (
            data.get("status")
            == "success"
            and transaction_status
            == "successful"
        ):
            payment.mark_success(
                str(
                    transaction_id
                ),
                data,
            )

            return (
                True,
                "Flutterwave payment confirmed.",
                data,
            )

        if transaction_status in {
            "failed",
            "cancelled",
        }:
            payment.mark_failed(
                data
            )

            return (
                False,
                (
                    "Flutterwave reported this payment "
                    "as failed or cancelled."
                ),
                data,
            )

        payment.gateway_response = data

        payment.save(
            update_fields=[
                "gateway_response",
                "updated_at",
            ]
        )

        return (
            False,
            (
                "Flutterwave has not confirmed "
                "this payment yet."
            ),
            data,
        )

    # -------------------------------------------------------------------------
    # PAYSTACK
    # -------------------------------------------------------------------------

    if (
        payment.gateway
        == PaymentMethod.PAYSTACK
    ):
        data = verify_paystack_transaction(
            payment.gateway_reference
            or payment.reference
        )

        if (
            data.get(
                "status"
            )
            and data.get(
                "data",
                {},
            ).get(
                "status"
            )
            == "success"
        ):
            payment.mark_success(
                str(
                    data.get(
                        "data",
                        {},
                    ).get(
                        "reference",
                        payment.reference,
                    )
                ),
                data,
            )

            return (
                True,
                "Paystack payment confirmed.",
                data,
            )

        payment.gateway_response = data

        payment.save(
            update_fields=[
                "gateway_response",
                "updated_at",
            ]
        )

        return (
            False,
            (
                "Paystack has not confirmed "
                "this payment yet."
            ),
            data,
        )

    # -------------------------------------------------------------------------
    # PAYPAL
    # -------------------------------------------------------------------------

    if (
        payment.gateway
        == PaymentMethod.PAYPAL
    ):
        data = capture_paypal_order(
            payment
        )

        if (
            data.get(
                "status"
            )
            == "COMPLETED"
        ):
            record_paypal_capture_response(
                payment,
                data,
            )

            return (
                False,
                (
                    "PayPal captured the payment. "
                    "Secure webhook confirmation is pending."
                ),
                data,
            )

        payment.gateway_response = data

        payment.save(
            update_fields=[
                "gateway_response",
                "updated_at",
            ]
        )

        return (
            False,
            (
                "PayPal has not confirmed "
                "this payment yet."
            ),
            data,
        )

    # -------------------------------------------------------------------------
    # COINBASE
    # -------------------------------------------------------------------------

    if (
        payment.gateway
        == PaymentMethod.COINBASE
    ):
        return (
            (
                payment.status
                == PaymentStatus.SUCCESS
            ),
            (
                "Coinbase confirmation is handled "
                "by secure webhook."
            ),
            payment.webhook_payload,
        )

    return (
        False,
        "Unsupported payment gateway.",
        {},
    )


# =============================================================================
# CHECKOUT PAGE
# =============================================================================


def checkout(request):
    """
    Payment selection page.

    Expected query params or POST fields:

    amount
    currency
    order_id
    email
    name
    phone
    """

    wallets = (
        ManualCryptoWallet.objects
        .filter(
            is_active=True
        )
    )

    order_id = request.GET.get(
        "order_id",
        request.POST.get(
            "order_id",
            "",
        ),
    )

    delivery_origin = {}

    package_weight_kg = (
        "0.00"
    )

    if (
        request.user.is_authenticated
        and str(
            order_id
        ).isdigit()
    ):
        cart = (
            Cart.objects
            .filter(
                id=int(
                    order_id
                ),
                user=request.user,
                is_active=True,
            )
            .prefetch_related(
                "items__product__vendor"
            )
            .first()
        )

        if cart:
            try:
                from deliveries.services import (
                    cart_package_weight_kg,
                    cart_pickup_context,
                )

                delivery_origin = (
                    cart_pickup_context(
                        cart
                    )
                )

                package_weight_kg = str(
                    cart_package_weight_kg(
                        cart
                    )
                )

            except Exception:
                delivery_origin = {}

    delivery_options = [
        {
            "value": "standard",
            "label": "Standard Delivery",
            "description": (
                "Reliable delivery calculated "
                "by your location."
            ),
            "icon": "fa-truck",
            "provider_type": (
                "manual_dispatch"
            ),
        },
        {
            "value": "express",
            "label": "Express Delivery",
            "description": (
                "Faster dispatch where available."
            ),
            "icon": "fa-bolt",
            "provider_type": (
                "arolana_driver"
            ),
        },
    ]

    delivery_service_level = (
        normalize_checkout_service_level(
            request.GET.get(
                "delivery_service_level",
                request.POST.get(
                    "delivery_service_level",
                    "standard",
                ),
            )
        )
    )

    context = {
        "wallets": wallets,
        "payment_options": (
            get_gateway_options()
        ),
        "delivery_options": (
            delivery_options
        ),
        "delivery_providers": [],
        "amount": request.GET.get(
            "amount",
            request.POST.get(
                "amount",
                "",
            ),
        ),
        "currency": request.GET.get(
            "currency",
            request.POST.get(
                "currency",
                getattr(
                    settings,
                    "AROLANA_DEFAULT_CURRENCY",
                    "NGN",
                ),
            ),
        ),
        "order_id": order_id,
        "email": request.GET.get(
            "email",
            request.POST.get(
                "email",
                "",
            ),
        ),
        "name": request.GET.get(
            "name",
            request.POST.get(
                "name",
                "",
            ),
        ),
        "phone": request.GET.get(
            "phone",
            request.POST.get(
                "phone",
                "",
            ),
        ),
        "address": request.GET.get(
            "address",
            request.POST.get(
                "address",
                "",
            ),
        ),
        "city": request.GET.get(
            "city",
            request.POST.get(
                "city",
                "",
            ),
        ),
        "state": request.GET.get(
            "state",
            request.POST.get(
                "state",
                "",
            ),
        ),
        "postal_code": request.GET.get(
            "postal_code",
            request.POST.get(
                "postal_code",
                "",
            ),
        ),
        "country": request.GET.get(
            "country",
            request.POST.get(
                "country",
                "",
            ),
        ),
        "delivery_service_level": (
            delivery_service_level
        ),
        "delivery_provider": "",
        "delivery_origin": (
            delivery_origin
        ),
        "package_weight_kg": (
            package_weight_kg
        ),
    }

    return render(
        request,
        "arolana_payments/checkout.html",
        context,
    )


# =============================================================================
# START WEB PAYMENT
# =============================================================================


@require_POST
def start_payment(
    request,
    gateway,
):
    if gateway not in PaymentMethod.values:
        return HttpResponseBadRequest(
            "Unsupported payment gateway."
        )

    try:
        (
            is_available,
            disabled_reason,
        ) = gateway_is_available(
            gateway
        )

        if not is_available:
            messages.error(
                request,
                (
                    disabled_reason
                    or (
                        "This payment gateway "
                        "is not available yet."
                    )
                ),
            )

            return redirect(
                "arolana_payments:checkout"
            )

        payment = create_transaction(
            request,
            gateway,
        )

        if (
            gateway
            == PaymentMethod.FLUTTERWAVE
        ):
            url = init_flutterwave_checkout(
                request,
                payment,
            )

        elif (
            gateway
            == PaymentMethod.PAYPAL
        ):
            url = init_paypal_checkout(
                request,
                payment,
            )

        elif (
            gateway
            == PaymentMethod.PAYSTACK
        ):
            url = init_paystack_checkout(
                request,
                payment,
            )

        elif (
            gateway
            == PaymentMethod.COINBASE
        ):
            url = init_coinbase_checkout(
                request,
                payment,
            )

        elif (
            gateway
            == PaymentMethod.MANUAL_CRYPTO
        ):
            return redirect(
                "arolana_payments:manual_crypto",
                reference=payment.reference,
            )

        else:
            return HttpResponseBadRequest(
                "Unsupported payment gateway."
            )

        if not url:
            payment.mark_failed(
                {
                    "error": (
                        "Gateway did not return "
                        "checkout URL."
                    ),
                }
            )

            messages.error(
                request,
                (
                    "Payment gateway did not return "
                    "a checkout link. Please try another method."
                ),
            )

            return redirect(
                "arolana_payments:checkout"
            )

        return redirect(
            url
        )

    except Exception as exc:
        if "payment" in locals():
            payment.mark_failed(
                {
                    "error": str(
                        exc
                    ),
                }
            )

        messages.error(
            request,
            (
                "Payment initialization failed: "
                f"{exc}"
            ),
        )

        return redirect(
            "arolana_payments:checkout"
        )


# =============================================================================
# START PAYMENT API
# =============================================================================


@require_POST
def start_payment_api(
    request,
    gateway,
):
    if gateway not in PaymentMethod.values:
        return _json_error(
            "Unsupported payment gateway.",
            status=400,
        )

    try:
        (
            is_available,
            disabled_reason,
        ) = gateway_is_available(
            gateway
        )

        if not is_available:
            return _json_error(
                (
                    disabled_reason
                    or (
                        "This payment gateway "
                        "is not available yet."
                    )
                ),
                status=400,
            )

        payment = create_transaction(
            request,
            gateway,
        )

        if (
            gateway
            == PaymentMethod.FLUTTERWAVE
        ):
            checkout_url = (
                init_flutterwave_checkout(
                    request,
                    payment,
                )
            )

        elif (
            gateway
            == PaymentMethod.PAYPAL
        ):
            checkout_url = (
                init_paypal_checkout(
                    request,
                    payment,
                )
            )

        elif (
            gateway
            == PaymentMethod.PAYSTACK
        ):
            checkout_url = (
                init_paystack_checkout(
                    request,
                    payment,
                )
            )

        elif (
            gateway
            == PaymentMethod.COINBASE
        ):
            checkout_url = (
                init_coinbase_checkout(
                    request,
                    payment,
                )
            )

        elif (
            gateway
            == PaymentMethod.MANUAL_CRYPTO
        ):
            checkout_url = (
                request.build_absolute_uri(
                    reverse(
                        "arolana_payments:manual_crypto",
                        args=[
                            payment.reference,
                        ],
                    )
                )
            )

        else:
            return _json_error(
                "Unsupported payment gateway.",
                status=400,
            )

        if not checkout_url:
            payment.mark_failed(
                {
                    "error": (
                        "Gateway did not return "
                        "checkout URL."
                    ),
                }
            )

            return _json_error(
                (
                    "Payment gateway did not return "
                    "a checkout link. Please try another method."
                ),
                status=502,
            )

        return JsonResponse(
            {
                "success": True,
                "message": (
                    "Payment initialized."
                ),
                "reference": (
                    payment.reference
                ),
                "gateway": (
                    payment.gateway
                ),
                "checkout_url": (
                    checkout_url
                ),
                "status_url": (
                    request.build_absolute_uri(
                        reverse(
                            "arolana_payments:status",
                            args=[
                                payment.reference,
                            ],
                        )
                    )
                ),
            }
        )

    except Exception as exc:
        if "payment" in locals():
            payment.mark_failed(
                {
                    "error": str(
                        exc
                    ),
                }
            )

        return _json_error(
            (
                "Payment initialization failed: "
                f"{exc}"
            ),
            status=502,
        )


# =============================================================================
# MANUAL CRYPTO PAYMENT
# =============================================================================


def manual_crypto(
    request,
    reference,
):
    payment = get_object_or_404(
        PaymentTransaction,
        reference=reference,
        gateway=(
            PaymentMethod.MANUAL_CRYPTO
        ),
    )

    wallets = (
        ManualCryptoWallet.objects
        .filter(
            is_active=True
        )
    )

    if request.method == "POST":
        # ---------------------------------------------------------------------
        # FINAL PAYMENT STATES CANNOT ACCEPT NEW PROOF
        # ---------------------------------------------------------------------

        if payment.status in {
            PaymentStatus.SUCCESS,
            PaymentStatus.REFUNDED,
        }:
            messages.error(
                request,
                (
                    "This payment is already completed "
                    "and cannot accept another payment proof."
                ),
            )

            return redirect(
                "arolana_payments:status",
                reference=payment.reference,
            )

        wallet_id = request.POST.get(
            "wallet_id"
        )

        wallet = get_object_or_404(
            ManualCryptoWallet,
            id=wallet_id,
            is_active=True,
        )

        uploaded_proof = request.FILES.get(
            "proof"
        )

        # ---------------------------------------------------------------------
        # VALIDATE PAYMENT PROOF BEFORE SAVE
        # ---------------------------------------------------------------------

        if uploaded_proof is not None:
            try:
                _validate_payment_proof(
                    uploaded_proof
                )

            except ValidationError as exc:
                for error in (
                    _validation_error_messages(
                        exc
                    )
                ):
                    messages.error(
                        request,
                        error,
                    )

                return render(
                    request,
                    (
                        "arolana_payments/"
                        "manual_crypto.html"
                    ),
                    {
                        "payment": payment,
                        "wallets": wallets,
                    },
                    status=400,
                )

        sender_wallet = _clean_text(
            request.POST.get(
                "sender_wallet"
            )
        )

        tx_hash = _clean_text(
            request.POST.get(
                "tx_hash"
            )
        )

        note = _clean_text(
            request.POST.get(
                "note"
            )
        )

        if not sender_wallet:
            messages.error(
                request,
                (
                    "Sender wallet address "
                    "is required."
                ),
            )

            return render(
                request,
                (
                    "arolana_payments/"
                    "manual_crypto.html"
                ),
                {
                    "payment": payment,
                    "wallets": wallets,
                },
                status=400,
            )

        if not tx_hash:
            messages.error(
                request,
                (
                    "Transaction hash "
                    "is required."
                ),
            )

            return render(
                request,
                (
                    "arolana_payments/"
                    "manual_crypto.html"
                ),
                {
                    "payment": payment,
                    "wallets": wallets,
                },
                status=400,
            )

        # ---------------------------------------------------------------------
        # SAVE VALIDATED SUBMISSION
        # ---------------------------------------------------------------------

        try:
            with transaction.atomic():
                payment.manual_wallet_network = (
                    wallet.network
                )

                payment.manual_wallet_address = (
                    wallet.address
                )

                payment.manual_sender_wallet = (
                    sender_wallet
                )

                payment.manual_tx_hash = (
                    tx_hash
                )

                payment.manual_note = (
                    note
                )

                payment.status = (
                    PaymentStatus.REVIEW
                )

                update_fields = [
                    "manual_wallet_network",
                    "manual_wallet_address",
                    "manual_sender_wallet",
                    "manual_tx_hash",
                    "manual_note",
                    "status",
                    "updated_at",
                ]

                if uploaded_proof is not None:
                    payment.manual_proof = (
                        uploaded_proof
                    )

                    update_fields.append(
                        "manual_proof"
                    )

                payment.save(
                    update_fields=update_fields
                )

        except Exception:
            messages.error(
                request,
                (
                    "The payment proof could not "
                    "be saved. Please try again."
                ),
            )

            return render(
                request,
                (
                    "arolana_payments/"
                    "manual_crypto.html"
                ),
                {
                    "payment": payment,
                    "wallets": wallets,
                },
                status=500,
            )

        # ---------------------------------------------------------------------
        # ADMIN NOTIFICATION
        # ---------------------------------------------------------------------

        subject = (
            "Arolana manual crypto payment submitted "
            f"- {payment.reference}"
        )

        admin_message = (
            "Manual crypto payment submitted.\n\n"
            f"Reference: {payment.reference}\n"
            f"Order ID: {payment.order_id}\n"
            f"Amount: {payment.amount} "
            f"{payment.currency}\n"
            f"Wallet Network: "
            f"{payment.manual_wallet_network}\n"
            f"Wallet Address: "
            f"{payment.manual_wallet_address}\n"
            f"Sender Wallet: "
            f"{payment.manual_sender_wallet}\n"
            f"Transaction Hash: "
            f"{payment.manual_tx_hash}\n"
            f"Customer: {payment.customer_name} "
            f"<{payment.customer_email}>\n"
        )

        recipients = [
            email
            for email in [
                getattr(
                    settings,
                    "PAYMENT_ADMIN_EMAIL",
                    "",
                ),
                getattr(
                    settings,
                    "DEFAULT_FROM_EMAIL",
                    "",
                ),
            ]
            if email
        ]

        if recipients:
            send_mail(
                subject,
                admin_message,
                getattr(
                    settings,
                    "DEFAULT_FROM_EMAIL",
                    None,
                ),
                recipients,
                fail_silently=True,
            )

        # ---------------------------------------------------------------------
        # CUSTOMER NOTIFICATION
        # ---------------------------------------------------------------------

        if payment.customer_email:
            send_mail(
                (
                    "Payment proof received "
                    f"- {payment.reference}"
                ),
                (
                    "We received your crypto payment proof. "
                    "Your payment is under review and you "
                    "will be notified after confirmation."
                ),
                getattr(
                    settings,
                    "DEFAULT_FROM_EMAIL",
                    None,
                ),
                [
                    payment.customer_email,
                ],
                fail_silently=True,
            )

        messages.success(
            request,
            (
                "Crypto payment proof submitted. "
                "We will review and confirm your payment."
            ),
        )

        return redirect(
            "arolana_payments:status",
            reference=payment.reference,
        )

    return render(
        request,
        "arolana_payments/manual_crypto.html",
        {
            "payment": payment,
            "wallets": wallets,
        },
    )


# =============================================================================
# PAYMENT CALLBACK
# =============================================================================


def callback(
    request,
    reference,
):
    payment = get_object_or_404(
        PaymentTransaction,
        reference=reference,
    )

    # -------------------------------------------------------------------------
    # FLUTTERWAVE
    # -------------------------------------------------------------------------

    if (
        payment.gateway
        == PaymentMethod.FLUTTERWAVE
    ):
        transaction_id = request.GET.get(
            "transaction_id"
        )

        callback_status = request.GET.get(
            "status"
        )

        if (
            transaction_id
            and callback_status
            == "successful"
        ):
            data = verify_flutterwave_transaction(
                transaction_id
            )

            if (
                data.get(
                    "status"
                )
                == "success"
                and data.get(
                    "data",
                    {},
                ).get(
                    "status"
                )
                == "successful"
            ):
                payment.mark_success(
                    str(
                        transaction_id
                    ),
                    data,
                )

            elif (
                data.get(
                    "data",
                    {},
                ).get(
                    "status"
                )
                in {
                    "failed",
                    "cancelled",
                }
            ):
                payment.mark_failed(
                    data
                )

            else:
                payment.gateway_response = data

                payment.status = (
                    PaymentStatus.PROCESSING
                )

                payment.save(
                    update_fields=[
                        "gateway_response",
                        "status",
                        "updated_at",
                    ]
                )

    # -------------------------------------------------------------------------
    # PAYPAL
    # -------------------------------------------------------------------------

    elif (
        payment.gateway
        == PaymentMethod.PAYPAL
    ):
        data = capture_paypal_order(
            payment
        )

        if (
            data.get(
                "status"
            )
            == "COMPLETED"
        ):
            record_paypal_capture_response(
                payment,
                data,
            )

        else:
            payment.gateway_response = data

            payment.status = (
                PaymentStatus.PROCESSING
            )

            payment.save(
                update_fields=[
                    "gateway_response",
                    "status",
                    "updated_at",
                ]
            )

    # -------------------------------------------------------------------------
    # PAYSTACK
    # -------------------------------------------------------------------------

    elif (
        payment.gateway
        == PaymentMethod.PAYSTACK
    ):
        reference_to_verify = (
            request.GET.get(
                "reference"
            )
            or payment.gateway_reference
            or payment.reference
        )

        if reference_to_verify:
            data = verify_paystack_transaction(
                reference_to_verify
            )

            if (
                data.get(
                    "status"
                )
                and data.get(
                    "data",
                    {},
                ).get(
                    "status"
                )
                == "success"
            ):
                payment.mark_success(
                    str(
                        data.get(
                            "data",
                            {},
                        ).get(
                            "reference",
                            reference_to_verify,
                        )
                    ),
                    data,
                )

            elif (
                data.get(
                    "data",
                    {},
                ).get(
                    "status"
                )
                in {
                    "failed",
                    "abandoned",
                }
            ):
                payment.mark_failed(
                    data
                )

            else:
                payment.gateway_response = data

                payment.status = (
                    PaymentStatus.PROCESSING
                )

                payment.save(
                    update_fields=[
                        "gateway_response",
                        "status",
                        "updated_at",
                    ]
                )

    # -------------------------------------------------------------------------
    # COINBASE
    # -------------------------------------------------------------------------

    elif (
        payment.gateway
        == PaymentMethod.COINBASE
    ):
        if payment.status not in {
            PaymentStatus.SUCCESS,
            PaymentStatus.FAILED,
        }:
            payment.status = (
                PaymentStatus.PROCESSING
            )

            payment.save(
                update_fields=[
                    "status",
                    "updated_at",
                ]
            )

    return redirect(
        "arolana_payments:status",
        reference=payment.reference,
    )


# =============================================================================
# CANCEL PAYMENT
# =============================================================================


@require_POST
def cancel(
    request,
    reference,
):
    payment = get_object_or_404(
        PaymentTransaction,
        reference=reference,
    )

    if payment.status in {
        PaymentStatus.SUCCESS,
        PaymentStatus.REFUNDED,
    }:
        messages.error(
            request,
            (
                "A successful or refunded "
                "payment cannot be cancelled."
            ),
        )

        return redirect(
            "arolana_payments:status",
            reference=payment.reference,
        )

    payment.status = (
        PaymentStatus.CANCELLED
    )

    payment.save(
        update_fields=[
            "status",
            "updated_at",
        ]
    )

    messages.warning(
        request,
        "Payment cancelled.",
    )

    return redirect(
        "arolana_payments:status",
        reference=payment.reference,
    )


# =============================================================================
# PAYMENT STATUS
# =============================================================================


def status(
    request,
    reference,
):
    payment = get_object_or_404(
        PaymentTransaction,
        reference=reference,
    )

    order = None
    delivery = None

    if payment.order_id:
        order = (
            Order.objects
            .filter(
                order_number=(
                    payment.order_id
                )
            )
            .prefetch_related(
                "delivery_requests__provider"
            )
            .first()
        )

        if order:
            delivery = (
                order.delivery_requests
                .order_by(
                    "-created_at"
                )
                .first()
            )

    return render(
        request,
        "arolana_payments/status.html",
        {
            "payment": payment,
            "order": order,
            "delivery": delivery,
        },
    )


# =============================================================================
# MOBILE PAYMENT INITIALIZATION
# =============================================================================


@csrf_exempt
@require_POST
def mobile_initialize_payment_api(request):
    payload = _json_body(
        request
    )

    try:
        customer = (
            _mobile_customer_from_payload(
                payload
            )
        )

        order = _mobile_order_for_customer(
            payload,
            customer,
        )

        gateway = _mobile_gateway(
            payload.get(
                "gateway"
            )
            or payload.get(
                "payment_method"
            )
        )

        (
            is_available,
            disabled_reason,
        ) = gateway_is_available(
            gateway
        )

        if not is_available:
            return _json_error(
                (
                    disabled_reason
                    or (
                        "This payment gateway "
                        "is not available yet."
                    )
                ),
                status=400,
            )

        if (
            str(
                getattr(
                    order,
                    "payment_status",
                    "",
                )
            ).lower()
            == "paid"
        ):
            return JsonResponse(
                {
                    "success": True,
                    "message": (
                        "This order is already paid."
                    ),
                    "already_paid": True,
                    "order": (
                        _mobile_order_payload(
                            request,
                            order,
                        )
                    ),
                }
            )

        customer_name = (
            getattr(
                order,
                "customer_name",
                "",
            )
            or getattr(
                customer,
                "full_name",
                "",
            )
            or getattr(
                customer.user,
                "get_full_name",
                lambda: "",
            )()
            or getattr(
                customer.user,
                "username",
                "",
            )
        )

        customer_email = (
            getattr(
                order,
                "customer_email",
                "",
            )
            or getattr(
                customer,
                "email",
                "",
            )
            or getattr(
                customer.user,
                "email",
                "",
            )
        )

        if not customer_email:
            return _json_error(
                (
                    "Customer email is required "
                    "before secure payment."
                ),
                status=400,
            )

        payment = (
            PaymentTransaction.objects
            .create(
                user=(
                    customer.user
                    if getattr(
                        customer,
                        "user_id",
                        None,
                    )
                    else None
                ),
                order_id=(
                    order.order_number
                ),
                gateway=gateway,
                amount=_order_amount(
                    order
                ),
                currency=(
                    payload.get(
                        "currency"
                    )
                    or getattr(
                        settings,
                        "AROLANA_DEFAULT_CURRENCY",
                        "NGN",
                    )
                ).upper(),
                customer_email=(
                    customer_email
                ),
                customer_name=(
                    customer_name
                ),
                customer_phone=(
                    getattr(
                        order,
                        "customer_phone",
                        "",
                    )
                    or customer.phone_number
                ),
                checkout_data={
                    "source": (
                        "mobile_app"
                    ),
                    "order_id": (
                        order.id
                    ),
                    "order_number": (
                        order.order_number
                    ),
                    "delivery_fee": str(
                        getattr(
                            order,
                            "shipping_cost",
                            "0.00",
                        )
                        or "0.00"
                    ),
                    "address": getattr(
                        order,
                        "shipping_address",
                        "",
                    ),
                },
            )
        )

        checkout_url = (
            _hosted_checkout_url(
                request,
                payment,
            )
        )

        if not checkout_url:
            payment.mark_failed(
                {
                    "error": (
                        "Gateway did not return "
                        "checkout URL."
                    ),
                }
            )

            return _json_error(
                (
                    "Payment gateway did not return "
                    "a checkout link. Please try another method."
                ),
                status=502,
            )

        changed_fields = []

        if (
            getattr(
                order,
                "payment_method",
                "",
            )
            != gateway
        ):
            order.payment_method = gateway

            changed_fields.append(
                "payment_method"
            )

        if (
            str(
                getattr(
                    order,
                    "payment_status",
                    "",
                )
            ).lower()
            not in {
                "pending",
                "processing",
            }
        ):
            order.payment_status = (
                "pending"
            )

            changed_fields.append(
                "payment_status"
            )

        if changed_fields:
            order.save(
                update_fields=list(
                    set(
                        changed_fields
                        + [
                            "updated_at",
                        ]
                    )
                )
            )

        return JsonResponse(
            {
                "success": True,
                "message": (
                    "Payment initialized."
                ),
                "reference": (
                    payment.reference
                ),
                "gateway": (
                    payment.gateway
                ),
                "checkout_url": (
                    checkout_url
                ),
                "status_url": (
                    request.build_absolute_uri(
                        reverse(
                            "arolana_payments:status",
                            args=[
                                payment.reference,
                            ],
                        )
                    )
                ),
                "verify_url": (
                    request.build_absolute_uri(
                        reverse(
                            "arolana_payments:mobile_verify"
                        )
                    )
                ),
                "order": (
                    _mobile_order_payload(
                        request,
                        order,
                    )
                ),
            }
        )

    except PermissionError as error:
        return _json_error(
            error,
            status=403,
        )

    except Exception as error:
        return _json_error(
            error,
            status=400,
        )


# =============================================================================
# MOBILE PAYMENT VERIFICATION
# =============================================================================


@csrf_exempt
@require_POST
def mobile_verify_payment_api(request):
    payload = _json_body(
        request
    )

    try:
        customer = (
            _mobile_customer_from_payload(
                payload
            )
        )

        reference = _clean_text(
            payload.get(
                "reference"
            )
            or payload.get(
                "payment_reference"
            )
        )

        if not reference:
            return _json_error(
                (
                    "Payment reference "
                    "is required."
                ),
                status=400,
            )

        payment = (
            PaymentTransaction.objects
            .filter(
                reference=reference
            )
            .first()
        )

        if not payment:
            return _json_error(
                (
                    "Payment reference "
                    "was not found."
                ),
                status=404,
            )

        order = None

        if payment.order_id:
            order = (
                Order.objects
                .filter(
                    order_number=(
                        payment.order_id
                    )
                )
                .first()
            )

        if order:
            allowed = False

            if (
                getattr(
                    customer,
                    "user_id",
                    None,
                )
                and (
                    order.user_id
                    == customer.user_id
                )
            ):
                allowed = True

            if (
                hasattr(
                    order,
                    "customer_phone",
                )
                and (
                    order.customer_phone
                    == customer.phone_number
                )
            ):
                allowed = True

            if not allowed:
                return _json_error(
                    (
                        "This payment does not "
                        "belong to this customer."
                    ),
                    status=403,
                )

        (
            confirmed,
            verification_message,
            _payload,
        ) = _verify_transaction_now(
            payment
        )

        if (
            not order
            and payment.order_id
        ):
            order = (
                Order.objects
                .filter(
                    order_number=(
                        payment.order_id
                    )
                )
                .first()
            )

        return JsonResponse(
            {
                "success": True,
                "confirmed": confirmed,
                "message": (
                    verification_message
                ),
                "reference": (
                    payment.reference
                ),
                "gateway": (
                    payment.gateway
                ),
                "payment_status": (
                    payment.status
                ),
                "order": (
                    _mobile_order_payload(
                        request,
                        order,
                    )
                    if order
                    else None
                ),
            }
        )

    except PermissionError as error:
        return _json_error(
            error,
            status=403,
        )

    except Exception as error:
        return _json_error(
            error,
            status=400,
        )


# =============================================================================
# MANUAL PAYMENT VERIFICATION
# =============================================================================


@require_POST
def verify_payment(
    request,
    reference,
):
    payment = get_object_or_404(
        PaymentTransaction,
        reference=reference,
    )

    if (
        payment.status
        == PaymentStatus.SUCCESS
    ):
        messages.info(
            request,
            (
                "This payment is "
                "already confirmed."
            ),
        )

        return redirect(
            "arolana_payments:status",
            reference=payment.reference,
        )

    if (
        payment.gateway
        == PaymentMethod.FLUTTERWAVE
    ):
        data = (
            verify_flutterwave_transaction_by_reference(
                payment.reference
            )
        )

        transaction_data = (
            data.get(
                "data",
                {},
            )
            if isinstance(
                data,
                dict,
            )
            else {}
        )

        transaction_status = (
            transaction_data.get(
                "status"
            )
        )

        transaction_id = (
            transaction_data.get(
                "id"
            )
            or transaction_data.get(
                "tx_ref"
            )
            or payment.reference
        )

        if (
            data.get(
                "status"
            )
            == "success"
            and transaction_status
            == "successful"
        ):
            payment.mark_success(
                str(
                    transaction_id
                ),
                data,
            )

            messages.success(
                request,
                (
                    "Flutterwave payment confirmed. "
                    "Your order and tracking are ready."
                ),
            )

        elif transaction_status in {
            "failed",
            "cancelled",
        }:
            payment.mark_failed(
                data
            )

            messages.error(
                request,
                (
                    "Flutterwave reported this payment "
                    "as failed or cancelled."
                ),
            )

        else:
            payment.gateway_response = data

            payment.save(
                update_fields=[
                    "gateway_response",
                    "updated_at",
                ]
            )

            messages.info(
                request,
                (
                    "Flutterwave has not confirmed "
                    "this payment yet. Please wait "
                    "a moment and try again."
                ),
            )

        return redirect(
            "arolana_payments:status",
            reference=payment.reference,
        )

    messages.info(
        request,
        (
            "Manual verification is only available "
            "for Flutterwave on this page."
        ),
    )

    return redirect(
        "arolana_payments:status",
        reference=payment.reference,
    )


# =============================================================================
# PAYPAL WEBHOOK
# =============================================================================


@csrf_exempt
@require_POST
def paypal_webhook(request):
    try:
        payload = json.loads(
            request.body.decode(
                "utf-8"
            )
            or "{}"
        )

    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
    ):
        return _json_error(
            (
                "Invalid PayPal "
                "webhook JSON."
            ),
            status=400,
        )

    event_id = _clean_text(
        payload.get(
            "id"
        )
    )

    if not event_id:
        event_id = (
            "missing-"
            f"{hashlib.sha256(request.body).hexdigest()}"
        )

    event_type = _clean_text(
        payload.get(
            "event_type"
        )
    )

    resource = (
        payload.get(
            "resource"
        )
        if isinstance(
            payload.get(
                "resource"
            ),
            dict,
        )
        else {}
    )

    headers = (
        _paypal_request_headers(
            request
        )
    )

    log, created = (
        PayPalWebhookLog.objects
        .get_or_create(
            event_id=event_id,
            defaults={
                "event_type": (
                    event_type
                ),
                "resource_type": (
                    _clean_text(
                        resource.get(
                            "resource_type"
                        )
                    )
                ),
                "resource_id": (
                    _clean_text(
                        resource.get(
                            "id"
                        )
                    )
                ),
                "payload": (
                    payload
                ),
                "request_headers": (
                    headers
                ),
            },
        )
    )

    if (
        not created
        and log.status
        in {
            PayPalWebhookLog.STATUS_PROCESSED,
            PayPalWebhookLog.STATUS_IGNORED,
        }
    ):
        return JsonResponse(
            {
                "received": True,
                "duplicate": True,
                "event_id": (
                    event_id
                ),
                "status": (
                    log.status
                ),
            }
        )

    if not created:
        log.event_type = (
            event_type
        )

        log.resource_type = (
            _clean_text(
                resource.get(
                    "resource_type"
                )
            )
        )

        log.resource_id = (
            _clean_text(
                resource.get(
                    "id"
                )
            )
        )

        log.payload = payload

        log.request_headers = (
            headers
        )

        log.status = (
            PayPalWebhookLog.STATUS_RECEIVED
        )

        log.last_error = ""

        log.save(
            update_fields=[
                "event_type",
                "resource_type",
                "resource_id",
                "payload",
                "request_headers",
                "status",
                "last_error",
                "updated_at",
            ]
        )

    try:
        (
            verified,
            verification_response,
        ) = verify_paypal_webhook_signature(
            headers,
            payload,
        )

        if not verified:
            log.status = (
                PayPalWebhookLog.STATUS_FAILED
            )

            log.last_error = (
                "PayPal rejected the webhook signature: "
                f"{verification_response}"
            )

            log.save(
                update_fields=[
                    "status",
                    "last_error",
                    "updated_at",
                ]
            )

            return _json_error(
                (
                    "Invalid PayPal "
                    "webhook signature."
                ),
                status=400,
            )

        log.signature_verified = True

        log.status = (
            PayPalWebhookLog.STATUS_VERIFIED
        )

        log.verified_at = (
            timezone.now()
        )

        log.last_error = ""

        log.save(
            update_fields=[
                "signature_verified",
                "status",
                "verified_at",
                "last_error",
                "updated_at",
            ]
        )

        processed = (
            process_paypal_webhook(
                log.pk
            )
        )

        return JsonResponse(
            {
                "received": True,
                "event_id": (
                    event_id
                ),
                "status": (
                    processed.status
                ),
            }
        )

    except ValueError as error:
        (
            PayPalWebhookLog.objects
            .filter(
                pk=log.pk
            )
            .update(
                status=(
                    PayPalWebhookLog
                    .STATUS_FAILED
                ),
                attempts=(
                    F("attempts")
                    + 1
                ),
                last_error=str(
                    error
                ),
            )
        )

        if log.signature_verified:
            return _json_error(
                (
                    "PayPal webhook processing "
                    "failed temporarily."
                ),
                status=500,
            )

        return _json_error(
            error,
            status=400,
        )

    except Exception as error:
        (
            PayPalWebhookLog.objects
            .filter(
                pk=log.pk
            )
            .update(
                status=(
                    PayPalWebhookLog
                    .STATUS_FAILED
                ),
                attempts=(
                    F("attempts")
                    + 1
                ),
                last_error=str(
                    error
                ),
            )
        )

        return _json_error(
            (
                "PayPal webhook processing "
                "failed temporarily."
            ),
            status=500,
        )


# =============================================================================
# FLUTTERWAVE WEBHOOK
# =============================================================================


@csrf_exempt
@require_POST
def flutterwave_webhook(request):
    if not verify_flutterwave_webhook(
        request
    ):
        return HttpResponseBadRequest(
            (
                "Invalid Flutterwave "
                "webhook."
            )
        )

    try:
        payload = json.loads(
            request.body.decode(
                "utf-8"
            )
            or "{}"
        )

    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
    ):
        return _json_error(
            (
                "Invalid Flutterwave "
                "webhook JSON."
            ),
            status=400,
        )

    data = (
        payload.get(
            "data",
            {},
        )
        if isinstance(
            payload.get(
                "data",
                {},
            ),
            dict,
        )
        else {}
    )

    tx_ref = (
        data.get(
            "tx_ref"
        )
        or payload.get(
            "tx_ref"
        )
    )

    webhook_status = (
        data.get(
            "status"
        )
        or payload.get(
            "status"
        )
    )

    payment = (
        PaymentTransaction.objects
        .filter(
            reference=tx_ref
        )
        .first()
    )

    if payment:
        if (
            webhook_status
            == "successful"
        ):
            payment.mark_success(
                str(
                    data.get(
                        "id",
                        "",
                    )
                ),
                payload,
            )

        elif webhook_status in {
            "failed",
            "cancelled",
        }:
            payment.mark_failed(
                payload
            )

    return JsonResponse(
        {
            "received": True,
        }
    )


# =============================================================================
# COINBASE WEBHOOK
# =============================================================================


@csrf_exempt
@require_POST
def coinbase_webhook(request):
    signature = request.headers.get(
        "X-CC-Webhook-Signature",
        "",
    )

    if not verify_coinbase_signature(
        request.body,
        signature,
    ):
        return HttpResponseBadRequest(
            (
                "Invalid Coinbase "
                "webhook."
            )
        )

    try:
        payload = json.loads(
            request.body.decode(
                "utf-8"
            )
            or "{}"
        )

    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
    ):
        return _json_error(
            (
                "Invalid Coinbase "
                "webhook JSON."
            ),
            status=400,
        )

    event = (
        payload.get(
            "event",
            {},
        )
        if isinstance(
            payload.get(
                "event",
                {},
            ),
            dict,
        )
        else {}
    )

    event_type = event.get(
        "type",
        "",
    )

    data = (
        event.get(
            "data",
            {},
        )
        if isinstance(
            event.get(
                "data",
                {},
            ),
            dict,
        )
        else {}
    )

    metadata = (
        data.get(
            "metadata",
            {},
        )
        if isinstance(
            data.get(
                "metadata",
                {},
            ),
            dict,
        )
        else {}
    )

    reference = metadata.get(
        "reference"
    )

    payment = (
        PaymentTransaction.objects
        .filter(
            reference=reference
        )
        .first()
    )

    if payment:
        if (
            event_type
            == "charge:confirmed"
        ):
            payment.mark_success(
                data.get(
                    "id",
                    "",
                ),
                payload,
            )

        elif (
            event_type
            == "charge:failed"
        ):
            payment.mark_failed(
                payload
            )

        else:
            payment.status = (
                PaymentStatus.PROCESSING
            )

            payment.webhook_payload = (
                payload
            )

            payment.save(
                update_fields=[
                    "status",
                    "webhook_payload",
                    "updated_at",
                ]
            )

    return JsonResponse(
        {
            "received": True,
        }
    )