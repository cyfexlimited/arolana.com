import json
import urllib.request
from datetime import timedelta
from io import BytesIO
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.core import signing
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import HttpResponse, JsonResponse
from django.utils.text import slugify
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from core.content_i18n import translated_field, translated_key
from deliveries.models import DeliveryRequest, DeliveryLocationPing, RiderPayout, RiderProfile, RiderWallet
from deliveries.models import DeliveryVehicle, DeliveryZone
from deliveries.services import create_live_delivery_for_order
from orders.models import MobilePushToken, Order
from kyc.models import KYCDocument, KYCRecord
from products.models import Brand, Category, Product, ProductImage, ProductVariant, ProductVariantImage, ProductWholesaleTier
from notifications.models import Notification
from subscriptions.models import (
    SubscriptionPlan,
    VendorSubscription,
    apply_vendor_subscription_benefits,
    get_tier_limits,
    subscription_label,
    user_subscription_tier,
)
from subscriptions.services import enforce_vendor_product_visibility
from vendors.models import VendorBankAccount, VendorProfile, VendorRFQ, VendorTransaction, VendorWallet, VendorWithdrawal
from vendors.security import send_vendor_password_changed_email
from arolana_payments.models import PaymentMethod, PaymentStatus, PaymentTransaction
from arolana_payments.services import (
    capture_paypal_order,
    gateway_is_available,
    get_gateway_options,
    init_coinbase_checkout,
    init_flutterwave_checkout,
    init_paypal_checkout,
    init_paystack_checkout,
    verify_flutterwave_transaction_by_reference,
    verify_paystack_transaction,
)
from smartchat.models import SmartChatConversation, SmartChatMessage
from installers.models import ProviderProfileChangeRequest, ServiceProviderProfile, ServiceQuoteRequest
from installers.services import (
    approve_profile_change_request,
    approve_provider,
    reject_profile_change_request,
    reject_provider,
    request_provider_changes,
    provider_workspace_notifications,
    suspend_provider,
    submit_provider_profile,
)
from accounts.utils.otp_utils import create_otp, verify_otp
from core.image_protection import (
    duplicate_warning_payload,
    inspect_vendor_image_upload,
    set_protected_image_uploader,
)
from core.media_optimization import get_optimized_image_url

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
except Exception:
    colors = None
    A4 = None
    getSampleStyleSheet = None
    Paragraph = None
    SimpleDocTemplate = None
    Spacer = None
    Table = None
    TableStyle = None

from .models import RiderCredential, StaffMobileToken


def _json_body(request):
    try:
        return json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        return {}


def _clean_text(value):
    return str(value or "").strip()


def _clean_phone(value):
    return "".join(ch for ch in str(value or "") if ch.isdigit() or ch == "+").strip()


def _error(message, status=400):
    return JsonResponse({"success": False, "message": str(message)}, status=status)


SUBSCRIPTION_UPGRADE_MESSAGE = "Your current subscription does not allow this feature. Please upgrade your plan."


def _subscription_limit_error():
    return JsonResponse(
        {
            "success": False,
            "allowed": False,
            "reason": "subscription_required",
            "message": SUBSCRIPTION_UPGRADE_MESSAGE,
        },
        status=403,
    )


def _vendor_upload_policy_error(result):
    return JsonResponse(
        {
            "success": False,
            "allowed": False,
            "reason": result.get("status") or "duplicate_image",
            "message": result.get("message") or "This image cannot be used.",
            "duplicate_warning": result,
        },
        status=409,
    )


def _request_staff_token(request):
    header = request.headers.get("Authorization", "")
    return header.replace("Bearer", "").strip() or request.GET.get("token") or ""


def _money(value, default="0.00"):
    try:
        return Decimal(str(value if value not in [None, ""] else default)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default).quantize(Decimal("0.01"))


def _absolute_media_url(request, file_field, preset=None):
    try:
        if file_field:
            file_url = get_optimized_image_url(file_field, preset) if preset else file_field.url
            if file_url.startswith(("http://", "https://")):
                return file_url
            if request:
                return request.build_absolute_uri(file_url)
            return f"{settings.SITE_URL.rstrip('/')}/{file_url.lstrip('/')}"
    except Exception:
        return ""
    return ""


def _absolute_original_media_url(request, file_field):
    try:
        if not file_field:
            return ""
        file_url = file_field.url
        if file_url.startswith(("http://", "https://")):
            return file_url
        if request:
            return request.build_absolute_uri(file_url)
        return f"{settings.SITE_URL.rstrip('/')}/{file_url.lstrip('/')}"
    except Exception:
        return ""


def _format_vendor_money(profile, amount, from_currency="NGN"):
    target = (getattr(profile, "preferred_currency", "NGN") or "NGN").upper()
    try:
        from currency.models import Currency

        source = Currency.objects.get(code=from_currency.upper(), is_active=True)
        dest = Currency.objects.get(code=target, is_active=True)
        converted = _money(amount) * (dest.exchange_rate / source.exchange_rate)
        return {
            "amount": str(_money(amount)),
            "currency": target,
            "converted_amount": str(converted.quantize(Decimal("0.01"))),
            "display": dest.format_amount(converted),
        }
    except Exception:
        symbol = "₦" if target == "NGN" else f"{target} "
        return {
            "amount": str(_money(amount)),
            "currency": target,
            "converted_amount": str(_money(amount)),
            "display": f"{symbol}{_money(amount):,.2f}",
        }


def _int_value(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _bool_value(value):
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _auth_staff(request):
    token = _request_staff_token(request)
    if not token:
        raise PermissionError("Staff token is required.")

    session = (
        StaffMobileToken.objects.select_related("user", "rider", "rider__user")
        .filter(token=token, is_active=True)
        .first()
    )
    if not session:
        raise PermissionError("Invalid or expired staff session.")

    session.last_used_at = timezone.now()
    session.save(update_fields=["last_used_at", "updated_at"])
    return session


def _order_value(order, *names, default=""):
    for name in names:
        value = getattr(order, name, None)
        if value not in [None, ""]:
            return value
    return default


def _rider_name(rider):
    if not rider:
        return ""
    user = rider.user
    return user.get_full_name() or user.email or user.username


def safe_phone(value):
    if value in [None, ""]:
        return ""
    try:
        return str(value)
    except Exception:
        return ""


def safe_str(value):
    if value in [None, ""]:
        return ""
    try:
        return str(value)
    except Exception:
        return ""


def _rider_phone(rider):
    return safe_phone(getattr(rider, "phone", "")) if rider else ""


def _rider_payload(rider):
    latest_location_at = rider.last_location_at.isoformat() if rider.last_location_at else ""
    vehicle = getattr(rider, "vehicle", None)
    return {
        "id": rider.id,
        "full_name": safe_str(_rider_name(rider)),
        "phone_number": safe_phone(_rider_phone(rider)),
        "email": safe_str(rider.user.email if rider.user_id else ""),
        "profile_photo_url": _absolute_media_url(None, getattr(rider, "profile_photo", None), "avatar"),
        "dashboard_image_url": _absolute_media_url(None, getattr(rider, "dashboard_image", None), "hero_banner"),
        "about": safe_str(getattr(rider, "about", "")),
        "profile_edit_status": safe_str(getattr(rider, "profile_edit_status", "clear")),
        "profile_edit_pending_data": getattr(rider, "profile_edit_pending_data", {}) or {},
        "profile_edit_requested_at": rider.profile_edit_requested_at.isoformat() if getattr(rider, "profile_edit_requested_at", None) else "",
        "profile_edit_available_at": rider.profile_edit_available_at.isoformat() if getattr(rider, "profile_edit_available_at", None) else "",
        "can_edit_profile": bool(getattr(rider, "can_request_profile_edit", True)),
        "preferred_language": safe_str(getattr(rider, "preferred_language", "english") or "english"),
        "notification_preferences": getattr(rider, "notification_preferences", {}) or {},
        "vehicle_type": safe_str(getattr(vehicle, "vehicle_type", "") if vehicle else ""),
        "vehicle_name": safe_str(getattr(vehicle, "name", "") if vehicle else ""),
        "plate_number": safe_str(getattr(vehicle, "plate_number", "") if vehicle else ""),
        "payout_bank_name": safe_str(getattr(rider, "payout_bank_name", "")),
        "payout_account_name": safe_str(getattr(rider, "payout_account_name", "")),
        "payout_account_number": safe_str(getattr(rider, "payout_account_number", "")),
        "payout_bank_country": safe_str(getattr(rider, "payout_bank_country", "")),
        "payout_preferred_currency": safe_str(getattr(rider, "payout_preferred_currency", "NGN")),
        "kyc_status": safe_str(rider.kyc_status),
        "is_online": bool(rider.is_online),
        "is_available": bool(rider.is_available),
        "is_active": bool(rider.is_active),
        "can_accept_deliveries": bool(rider.can_accept_deliveries),
        "current_latitude": str(rider.current_latitude or ""),
        "current_longitude": str(rider.current_longitude or ""),
        "last_location_at": latest_location_at,
        "completed_deliveries": rider.completed_deliveries,
        "rating_avg": str(rider.rating_avg),
    }


def _live_delivery(order):
    try:
        return order.live_delivery_requests.select_related("rider", "rider__user").order_by("-created_at").first()
    except Exception:
        return None


def _order_payload(order):
    delivery = _live_delivery(order)
    rider = delivery.rider if delivery else None

    delivery_status = safe_str(delivery.status if delivery else "")
    is_ready_for_rider = bool(delivery.is_ready_for_rider) if delivery else False

    if is_ready_for_rider and delivery_status in {"", DeliveryRequest.STATUS_PENDING}:
        delivery_status = "ready_for_pickup"

    items = []
    vendor_item_status = ""

    try:
        for item in order.items.select_related("product")[:20]:
            product = item.product
            item_status = (
                getattr(item, "vendor_status", "")
                or getattr(item, "fulfillment_status", "")
                or getattr(item, "status", "")
            )

            if item_status and not vendor_item_status:
                vendor_item_status = item_status

            items.append({
                "name": safe_str(getattr(item, "item_name", "")),
                "product_id": product.id if product else None,
                "quantity": getattr(item, "quantity", 0),
                "price": str(getattr(item, "price", "0")),
                "subtotal": str(getattr(item, "subtotal", "0")),
            })
    except Exception:
        pass

    customer_name_default = ""
    customer_email_default = ""

    try:
        customer_name_default = order.user.get_full_name() if order.user_id else ""
        customer_email_default = order.user.email if order.user_id else ""
    except Exception:
        customer_name_default = ""
        customer_email_default = ""

    return {
        "id": order.id,
        "order_id": order.id,
        "order_number": safe_str(_order_value(order, "order_number", default=str(order.id))),
        "status": safe_str(_order_value(order, "status", default="pending")),
        "payment_status": safe_str(_order_value(order, "payment_status", default="pending")),
        "payment_method": safe_str(_order_value(order, "payment_method", "payment_type", default="")),
        "total": str(_order_value(order, "total", "grand_total", default="0")),

        "customer_name": safe_str(_order_value(order, "customer_name", default=customer_name_default)),
        "customer_phone": safe_phone(_order_value(order, "customer_phone", default="")),
        "customer_email": safe_str(_order_value(order, "customer_email", default=customer_email_default)),

        "delivery_id": delivery.id if delivery else None,
        "delivery_status": safe_str(delivery_status),
        "vendor_item_status": safe_str(vendor_item_status or ("ready_for_pickup" if is_ready_for_rider else "")),
        "tracking_code": safe_str(delivery.tracking_code if delivery else _order_value(order, "tracking_number", default="")),

        "rider_id": rider.id if rider else None,
        "rider_name": safe_str(_rider_name(rider)),
        "rider_phone": safe_phone(_rider_phone(rider)),

        "pickup_name": safe_str(delivery.pickup_name if delivery else ""),
        "pickup_phone": safe_phone(delivery.pickup_phone if delivery else ""),
        "pickup_address": safe_str(delivery.pickup_address if delivery else ""),

        "delivery_address": safe_str(
            delivery.dropoff_address if delivery else _order_value(
                order,
                "delivery_address",
                "shipping_address",
                default="",
            )
        ),

        "delivery_fee": str(delivery.delivery_fee if delivery else getattr(order, "shipping_cost", "0")),
        "rider_earning": str(delivery.rider_earning if delivery else "0"),
        "is_ready_for_rider": bool(is_ready_for_rider),
        "notification_status": "Customer, vendor and admin notified" if is_ready_for_rider else "",
        "items": items,
        "created_at": order.created_at.isoformat() if getattr(order, "created_at", None) else "",
    }


def _delivery_payload(delivery):
    order_payload = _order_payload(delivery.order)

    vendor_user = None
    vendor_profile = None

    try:
        first_item = (
            delivery.order.items
            .select_related("product__vendor__vendor_profile", "variant__product__vendor__vendor_profile")
            .first()
        )

        if first_item:
            if first_item.product_id:
                vendor_user = first_item.product.vendor
            elif first_item.variant_id and first_item.variant.product_id:
                vendor_user = first_item.variant.product.vendor

        vendor_profile = getattr(vendor_user, "vendor_profile", None) if vendor_user else None
    except Exception:
        vendor_user = None
        vendor_profile = None

    rider = delivery.rider

    try:
        latest_ping = delivery.latest_location
    except Exception:
        latest_ping = None

    status_order = [
        DeliveryRequest.STATUS_ASSIGNED,
        DeliveryRequest.STATUS_ACCEPTED,
        DeliveryRequest.STATUS_ARRIVED_PICKUP,
        DeliveryRequest.STATUS_PICKED_UP,
        DeliveryRequest.STATUS_IN_TRANSIT,
        DeliveryRequest.STATUS_ARRIVED_CUSTOMER,
        DeliveryRequest.STATUS_DELIVERED,
        DeliveryRequest.STATUS_FAILED,
        DeliveryRequest.STATUS_RETURNED,
    ]

    status_rank = {status: index for index, status in enumerate(status_order)}
    current_rank = status_rank.get(delivery.status, -1)

    history_by_status = {}

    try:
        for event in delivery.status_history.select_related("actor").order_by("created_at"):
            history_by_status.setdefault(event.status, event)
    except Exception:
        history_by_status = {}

    timeline = []

    for status in status_order:
        event = history_by_status.get(status)
        is_current = status == delivery.status

        is_done = bool(event) or (
            current_rank >= status_rank.get(status, 999)
            and delivery.status not in {
                DeliveryRequest.STATUS_FAILED,
                DeliveryRequest.STATUS_RETURNED,
            }
        )

        if status in {
            DeliveryRequest.STATUS_FAILED,
            DeliveryRequest.STATUS_RETURNED,
        }:
            is_done = bool(event) or is_current

        timeline.append({
            "status": safe_str(status),
            "label": safe_str(dict(DeliveryRequest.STATUS_CHOICES).get(
                status,
                safe_str(status).replace("_", " ").title(),
            )),
            "completed": bool(is_done),
            "current": bool(is_current),
            "note": safe_str(event.note) if event else "",
            "created_at": event.created_at.isoformat() if event and event.created_at else "",
            "actor": safe_str(
                event.actor.get_full_name() or event.actor.email
            ) if event and event.actor_id else "",
        })

    rider_latitude = latest_ping.latitude if latest_ping else getattr(rider, "current_latitude", None)
    rider_longitude = latest_ping.longitude if latest_ping else getattr(rider, "current_longitude", None)

    vendor_name = ""
    vendor_phone = ""

    if vendor_user:
        vendor_name = (
            getattr(vendor_profile, "store_name", "")
            or vendor_user.get_full_name()
            or getattr(vendor_user, "email", "")
            or getattr(vendor_user, "username", "")
        )
        vendor_phone = (
            getattr(vendor_profile, "support_phone", "")
            or getattr(vendor_user, "phone_number", "")
        )

    order_payload.update({
        "id": delivery.id,
        "delivery_id": delivery.id,
        "order_id": delivery.order_id,

        "status": safe_str(delivery.status),
        "delivery_status": safe_str(delivery.status),
        "tracking_code": safe_str(delivery.tracking_code),
        "is_ready_for_rider": bool(delivery.is_ready_for_rider),

        "vendor_name": safe_str(vendor_name),
        "vendor_phone": safe_phone(vendor_phone),

        "pickup_name": safe_str(delivery.pickup_name or getattr(vendor_profile, "store_name", "")),
        "pickup_phone": safe_phone(delivery.pickup_phone or getattr(vendor_profile, "support_phone", "")),
        "pickup_address": safe_str(delivery.pickup_address),
        "pickup_latitude": str(delivery.pickup_latitude or ""),
        "pickup_longitude": str(delivery.pickup_longitude or ""),

        "delivery_address": safe_str(delivery.dropoff_address),
        "delivery_latitude": str(delivery.dropoff_latitude or ""),
        "delivery_longitude": str(delivery.dropoff_longitude or ""),

        "rider_name": safe_str(_rider_name(rider)),
        "rider_phone": safe_phone(_rider_phone(rider)),
        "rider_current_latitude": str(rider_latitude or ""),
        "rider_current_longitude": str(rider_longitude or ""),

        "timeline": timeline,
        "proof_of_delivery_url": _absolute_media_url(None, delivery.proof_of_delivery, "product_card"),
        "proof_note": safe_str(delivery.proof_note),
        "failed_reason": safe_str(delivery.failed_reason),
        "last_update": delivery.updated_at.isoformat() if delivery.updated_at else "",
    })

    return order_payload


def _staff_session_payload(session):
    user = session.user
    rider = session.rider
    rider_user = rider.user if rider else None
    return {
        "id": session.id,
        "role": session.role,
        "token": session.token,
        "user_id": user.id if user else None,
        "rider_id": rider.id if rider else None,
        "username": getattr(user, "username", "") if user else getattr(rider_user, "username", ""),
        "full_name": (
            (user.get_full_name() if user else "")
            or (_rider_name(rider) if rider else "")
            or getattr(user, "username", "")
        ),
        "email": getattr(user, "email", "") if user else getattr(rider_user, "email", ""),
    }


def _is_admin_user(user):
    return bool(user and (getattr(user, "is_staff", False) or getattr(user, "is_superuser", False)))


def _is_vendor_user(user):
    if not user:
        return False
    if getattr(user, "user_type", "") == "vendor" or getattr(user, "is_vendor", False):
        return True
    groups = getattr(user, "groups", None)
    if groups and groups.filter(name__icontains="vendor").exists():
        return True
    return hasattr(user, "vendor_profile") or hasattr(user, "vendor")


def _vendor_profile_for_user(user):
    if not user:
        return None
    profile = getattr(user, "vendor_profile", None)
    if profile:
        return profile
    return None


def _vendor_wallet(profile):
    if not profile:
        return None
    wallet, _ = VendorWallet.objects.get_or_create(vendor=profile, defaults={"currency": "NGN"})
    return wallet


def _vendor_payload(profile, request=None):
    if not profile:
        return {}
    wallet = _vendor_wallet(profile)
    vendor_type = getattr(profile, "vendor_type", "retailer")
    vendor_type_display = profile.get_vendor_type_display() if hasattr(profile, "get_vendor_type_display") else vendor_type.replace("_", " ").title()
    manufacturer_verified = bool(vendor_type == "manufacturer" and profile.manufacturer_verified)
    return {
        "id": profile.id,
        "store_name": profile.store_name,
        "company_name": profile.company_name,
        "vendor_type": vendor_type,
        "vendor_type_display": vendor_type_display,
        "approval_status": profile.approval_status,
        "kyc_status": profile.kyc_status,
        "is_verified": profile.is_verified,
        "manufacturer_verified": manufacturer_verified,
        "manufacturer_badge_label": profile.manufacturer_badge_label if manufacturer_verified else "",
        "subscription_tier": user_subscription_tier(profile.user),
        "subscription_label": profile.subscription_plan_label,
        "subscription_active": bool(getattr(profile, "subscription_active", False)),
        "subscription_started_at": profile.subscription_started_at.isoformat() if getattr(profile, "subscription_started_at", None) else "",
        "subscription_expires_at": (profile.subscription_expires_at or profile.subscription_expiry).isoformat() if (getattr(profile, "subscription_expires_at", None) or getattr(profile, "subscription_expiry", None)) else "",
        "product_limit": profile.product_limit,
        "image_limit": profile.image_limit,
        "variant_limit": profile.variant_limit,
        "can_upload_video": profile.can_upload_video,
        "can_upload_pdf": profile.can_upload_pdf,
        "can_upload_certificates": profile.can_upload_certificates,
        "can_access_rfq": profile.can_access_rfq,
        "can_receive_direct_enquiries": profile.can_receive_direct_enquiries,
        "can_use_boosting": profile.can_use_boosting,
        "can_show_on_homepage": profile.can_show_on_homepage,
        "can_access_analytics": profile.can_access_analytics,
        "can_access_advanced_analytics": profile.can_access_advanced_analytics,
        "can_access_ads": profile.can_access_ads,
        "priority_score": profile.priority_score,
        "support_level": profile.support_level,
        "badge_level": profile.badge_level or profile.subscription_plan_label,
        "store_logo": _absolute_media_url(request, profile.store_logo, "logo"),
        "logo_url": _absolute_media_url(request, profile.store_logo, "logo"),
        "profile_photo": _absolute_media_url(request, profile.store_logo, "avatar"),
        "store_banner": _absolute_media_url(request, profile.store_banner, "hero_banner"),
        "banner_url": _absolute_media_url(request, profile.store_banner, "hero_banner"),
        "description": profile.description,
        "business_address": profile.business_address,
        "manufacturer_address": profile.manufacturer_address,
        "warehouse_address": profile.warehouse_address,
        "support_email": profile.support_email,
        "support_phone": profile.support_phone,
        "website": profile.website,
        "preferred_language": getattr(profile, "preferred_language", "english") or "english",
        "preferred_currency": getattr(profile, "preferred_currency", "NGN") or "NGN",
        "profile_completion_percent": profile.profile_completion_percent,
        "rating_avg": str(profile.rating_avg),
        "followers_count": profile.followers_count,
        "can_upload_products": profile.can_upload_products,
        "wallet_balance": str(wallet.available_balance if wallet else "0.00"),
        "pending_balance": str(wallet.pending_balance if wallet else "0.00"),
        "withdrawable_balance": str(wallet.withdrawable_balance if wallet else "0.00"),
        "country": profile.country,
        "pickup_address": profile.pickup_address,
        "pickup_phone": profile.pickup_phone,
    }


def _service_provider_payload(provider, request=None):
    return {
        "id": provider.id,
        "user_id": provider.user_id,
        "business_name": provider.business_name,
        "contact_person": provider.contact_person,
        "provider_type": provider.provider_type,
        "provider_type_label": provider.get_provider_type_display(),
        "phone_number": provider.phone_number,
        "whatsapp_number": provider.whatsapp_number,
        "email": provider.email,
        "website": provider.website,
        "country": provider.country,
        "state": provider.state,
        "city": provider.city,
        "address": provider.address,
        "location": provider.location_label,
        "service_coverage": provider.service_coverage,
        "description": provider.description,
        "years_of_experience": provider.years_of_experience,
        "cac_number": provider.cac_number,
        "profile_image": _absolute_media_url(request, provider.profile_image, "avatar"),
        "business_logo": _absolute_media_url(request, provider.business_logo, "logo"),
        "business_banner": _absolute_media_url(request, provider.business_banner, "hero_banner"),
        "verification_status": provider.verification_status,
        "verification_note": provider.verification_note,
        "kyc_status": provider.kyc_status,
        "subscription_plan": provider.subscription_plan,
        "subscription_status": provider.subscription_status,
        "approval_allows_dashboard": provider.approval_allows_dashboard,
        "can_receive_serious_jobs": provider.can_receive_serious_jobs,
        "profile_completion_percent": provider.profile_completion_percent,
        "review_due_at": provider.review_due_at.isoformat() if provider.review_due_at else "",
        "changes_requested_note": provider.changes_requested_note,
        "rejection_reason": provider.rejection_reason,
        "is_verified": provider.is_verified,
        "is_active": provider.is_active,
        "average_rating": str(provider.average_rating),
        "total_reviews": provider.total_reviews,
        "total_completed_jobs": provider.total_completed_jobs,
        "created_at": provider.created_at.isoformat() if provider.created_at else "",
    }


def _service_quote_payload(quote):
    return {
        "id": quote.id,
        "customer_id": quote.customer_id,
        "provider_id": quote.provider_id,
        "provider_name": quote.provider.business_name if quote.provider else "",
        "category": quote.category.name if quote.category else "",
        "product_id": quote.product_id,
        "product_name": quote.product.name if quote.product else "",
        "name": quote.name,
        "phone": quote.phone,
        "whatsapp": quote.whatsapp,
        "email": quote.email,
        "state": quote.state,
        "city": quote.city,
        "address": quote.address,
        "service_needed": quote.service_needed,
        "message": quote.message,
        "status": quote.status,
        "created_at": quote.created_at.isoformat() if quote.created_at else "",
        "updated_at": quote.updated_at.isoformat() if quote.updated_at else "",
    }


def _subscription_status_payload(profile):
    tier = user_subscription_tier(profile.user)
    if tier != profile.subscription_tier:
        apply_vendor_subscription_benefits(profile, tier)
        if tier == "free":
            profile.subscription_active = False
            profile.save(update_fields=["subscription_active", "updated_at"])
        profile.refresh_from_db()
    return _vendor_payload(profile)


def _require_vendor_session(request):
    session = None
    try:
        session = _auth_staff(request)
        if session.role != "vendor":
            raise PermissionError("Vendor access required.")
        user = session.user
    except PermissionError:
        user = getattr(request, "user", None)
        if not user or not getattr(user, "is_authenticated", False):
            raise PermissionError("Vendor access required.")
    profile = _vendor_profile_for_user(user)
    if not profile:
        raise PermissionError("Vendor profile not found.")
    return session, profile


def _provider_profile_for_user(user):
    if not user:
        return None
    return getattr(user, "service_provider_profile", None)


def _require_provider_session(request):
    session = None
    try:
        session = _auth_staff(request)
        if session.role != "provider":
            raise PermissionError("Provider access required.")
        user = session.user
    except PermissionError:
        user = getattr(request, "user", None)
        if not user or not getattr(user, "is_authenticated", False):
            raise PermissionError("Provider access required.")
    profile = _provider_profile_for_user(user)
    if not profile:
        raise PermissionError("Provider profile not found.")
    return session, profile


def _require_admin_session(request):
    session = _auth_staff(request)
    if session.role != "admin" or not _is_admin_user(session.user):
        raise PermissionError("Admin access required.")
    return session


def _require_rider_session(request):
    session = _auth_staff(request)
    if session.role != "rider" or not session.rider_id:
        raise PermissionError("Rider access required.")
    return session


def _send_expo_push_to_user(user, title, body, data=None):
    if not user:
        return
    try:
        phone = getattr(user, "phone_number", "") or getattr(user, "phone", "")
        token_filter = Q()
        if getattr(user, "email", ""):
            token_filter |= Q(email__iexact=user.email)
        if phone:
            token_filter |= Q(phone_number=phone)
        if not token_filter:
            return
        tokens = MobilePushToken.objects.filter(is_active=True).filter(token_filter).exclude(expo_push_token="")
        payloads = [
            {
                "to": token.expo_push_token,
                "sound": "default",
                "title": title,
                "body": body,
                "data": data or {},
            }
            for token in tokens[:20]
        ]
        if not payloads:
            return
        request = urllib.request.Request(
            "https://exp.host/--/api/v2/push/send",
            data=json.dumps(payloads).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(request, timeout=4).read()
    except Exception:
        return


def _notify(user, title, message, notification_type="vendor", metadata=None):
    if not user:
        return None
    try:
        notification = Notification.send(
            user=user,
            notification_type=notification_type,
            title=title,
            message=message,
            metadata=metadata or {},
            priority=3,
        )
        if notification_type in {"delivery", "order"}:
            _send_expo_push_to_user(user, title, message, metadata or {})
        return notification
    except Exception:
        return None


def _admin_notification_users():
    User = get_user_model()
    return User.objects.filter(Q(is_staff=True) | Q(is_superuser=True), is_active=True).distinct()[:30]


def _notify_order_ready(profile, order):
    order_number = _order_value(order, "order_number", default=str(order.id))
    metadata = {"order_id": order.id, "order_number": order_number, "vendor_id": profile.id}
    admin_message = f"Vendor marked order {order_number} ready for pickup."
    customer_message = f"Your order {order_number} is ready for pickup and will be assigned to a rider soon."
    vendor_message = f"Order {order_number} has been marked ready for pickup."

    for admin_user in _admin_notification_users():
        _notify(admin_user, "Order ready for pickup", admin_message, "order", metadata)
    _notify(order.user, "Your order is ready for pickup", customer_message, "order", metadata)
    _notify(profile.user, "Order ready for pickup", vendor_message, "order", metadata)


def _vendor_users_for_order(order):
    try:
        return list(get_user_model().objects.filter(products__order_items__order=order).distinct())
    except Exception:
        try:
            return list(get_user_model().objects.filter(product__order_items__order=order).distinct())
        except Exception:
            users = []
            try:
                for item in order.items.select_related("product__vendor"):
                    vendor = getattr(getattr(item, "product", None), "vendor", None)
                    if vendor and vendor not in users:
                        users.append(vendor)
            except Exception:
                pass
            return users


def _vendor_order_q(vendor_user):
    return Q(items__product__vendor=vendor_user) | Q(items__variant__product__vendor=vendor_user)


def _vendor_orders_for_user(vendor_user):
    return Order.objects.filter(_vendor_order_q(vendor_user)).distinct()


def _notify_delivery_assignment(delivery, admin_user=None):
    order = delivery.order
    order_number = _order_value(order, "order_number", default=str(order.id))
    rider_name = _rider_name(delivery.rider) or "Arolana rider"
    pickup_name = delivery.pickup_name or "the vendor"
    metadata = {
        "target_type": "delivery",
        "screen": "RiderDeliveries",
        "type": "delivery",
        "order_id": order.id,
        "delivery_id": delivery.id,
        "order_number": order_number,
        "tracking_code": delivery.tracking_code,
        "status": delivery.status,
        "delivery_status": delivery.status,
        "rider_id": delivery.rider_id,
        "pickup_name": pickup_name,
        "pickup_address": delivery.pickup_address,
        "delivery_address": delivery.dropoff_address,
    }
    _notify(
        delivery.rider.user if delivery.rider_id else None,
        "New pickup assigned",
        f"You have a new pickup for order {order_number} from {pickup_name}.",
        "delivery",
        metadata,
    )
    _notify(order.user, "Rider assigned", f"{rider_name} has been assigned to your order {order_number}.", "delivery", metadata)
    for vendor_user in _vendor_users_for_order(order):
        _notify(vendor_user, "Rider assigned", f"{rider_name} has been assigned to pick up order {order_number}.", "delivery", metadata)
    _notify(admin_user, "Rider assigned", f"{rider_name} has been assigned to order {order_number}.", "delivery", metadata)


def _notify_delivery_status_change(delivery, status, actor_user=None):
    order = delivery.order
    order_number = _order_value(order, "order_number", default=str(order.id))
    status_label = str(status or "").replace("_", " ").title()
    rider_name = _rider_name(delivery.rider) or "the assigned rider"
    if status == DeliveryRequest.STATUS_PICKED_UP:
        customer_text = f"Your order {order_number} has been picked up from the vendor by {rider_name}."
        vendor_text = f"Order {order_number} handoff recorded: products were given to {rider_name}."
        admin_text = f"Vendor handoff recorded for order {order_number}. Rider: {rider_name}."
        title = "Vendor handoff recorded"
    else:
        customer_text = f"Your order {order_number} is now {status_label}."
        vendor_text = f"Order {order_number} is now {status_label}."
        admin_text = f"Order {order_number} is now {status_label}."
        title = "Delivery update"
    metadata = {
        "order_id": order.id,
        "delivery_id": delivery.id,
        "order_number": order_number,
        "tracking_code": delivery.tracking_code,
        "delivery_status": status,
        "handoff_recorded": status == DeliveryRequest.STATUS_PICKED_UP,
    }
    _notify(order.user, title, customer_text, "delivery", metadata)
    for vendor_user in _vendor_users_for_order(order):
        _notify(vendor_user, title, vendor_text, "delivery", metadata)
        if status == DeliveryRequest.STATUS_PICKED_UP:
            try:
                from dashboard.models import VendorNotification

                VendorNotification.objects.create(
                    vendor=vendor_user,
                    title=title,
                    message=vendor_text,
                    notification_type="delivery_picked_up",
                    action_url="/dashboard/vendor/order-robot/",
                    metadata=metadata,
                )
            except Exception:
                pass
    for admin_user in _admin_notification_users():
        if actor_user and admin_user.id == actor_user.id:
            continue
        _notify(admin_user, title, admin_text, "delivery", metadata)


def _mark_vendor_items_ready(order, vendor_user):
    now = timezone.now()
    try:
        vendor_items = list(
            order.items
            .filter(Q(product__vendor=vendor_user) | Q(variant__product__vendor=vendor_user))
            .select_related("product", "variant__product")
        )
    except Exception:
        vendor_items = []

    for item in vendor_items:
        update_fields = []
        for field, value in (
            ("vendor_status", "ready_for_pickup"),
            ("fulfillment_status", "ready_for_pickup"),
            ("status", "ready_for_pickup"),
            ("is_ready_for_pickup", True),
            ("ready_for_pickup_at", now),
        ):
            if hasattr(item, field):
                try:
                    setattr(item, field, value)
                    update_fields.append(field)
                except Exception:
                    pass
        if update_fields:
            if hasattr(item, "updated_at"):
                update_fields.append("updated_at")
            try:
                item.save(update_fields=list(dict.fromkeys(update_fields)))
            except Exception:
                try:
                    item.save()
                except Exception:
                    pass


def _ensure_order_robot_process(order, actor=None):
    from order_robot.models import OrderRobotProcess, OrderRobotVendorTask
    from order_robot.services import process_paid_order

    try:
        return order.robot_process
    except OrderRobotProcess.DoesNotExist:
        pass

    payment_status = str(getattr(order, "payment_status", "") or "").lower()
    order_status = str(getattr(order, "status", "") or "").lower()
    if payment_status in {"paid", "success", "successful", "completed", "confirmed"} or order_status in {"paid", "processing"}:
        return process_paid_order(order, actor=actor)

    process = OrderRobotProcess.objects.create(order=order)
    due_at = timezone.now() + timedelta(hours=6)
    for vendor_user in _vendor_users_for_order(order):
        OrderRobotVendorTask.objects.get_or_create(
            process=process,
            vendor=vendor_user,
            defaults={"due_at": due_at},
        )
    return process


def _mark_order_ready_for_pickup(session, profile, order, note="Vendor marked order ready for pickup."):
    actor = session.user
    _mark_vendor_items_ready(order, profile.user)

    try:
        from order_robot.models import OrderRobotVendorTask
        from order_robot.services import sync_from_live_delivery, vendor_mark_confirmed

        with transaction.atomic():
            process = _ensure_order_robot_process(order, actor=actor)
            if not process.vendor_tasks.exists():
                due_at = timezone.now() + timedelta(hours=6)
                for vendor_user in _vendor_users_for_order(order):
                    OrderRobotVendorTask.objects.get_or_create(
                        process=process,
                        vendor=vendor_user,
                        defaults={"due_at": due_at},
                    )

            task, _ = OrderRobotVendorTask.objects.get_or_create(
                process=process,
                vendor=profile.user,
                defaults={"due_at": timezone.now() + timedelta(hours=6)},
            )

            delivery = process.live_delivery or _live_delivery(order) or create_live_delivery_for_order(order, defer_assignment=True)
            if process.live_delivery_id != delivery.id:
                process.live_delivery = delivery
                process.save(update_fields=["live_delivery", "updated_at"])

            vendor_mark_confirmed(
                task,
                ready=True,
                actor=actor,
                note=note or f"{profile.store_name} marked this order ready for pickup.",
            )

        delivery = _live_delivery(order) or delivery
        if delivery:
            sync_from_live_delivery(delivery)
    except Exception:
        delivery = _live_delivery(order) or create_live_delivery_for_order(order, defer_assignment=True)
        delivery.is_ready_for_rider = True
        delivery.save(update_fields=["is_ready_for_rider", "updated_at"])
        try:
            delivery.set_status(
                DeliveryRequest.STATUS_PENDING,
                actor=actor,
                note=note or f"{profile.store_name} marked this order ready for pickup.",
            )
        except Exception:
            pass

    _notify_order_ready(profile, order)
    return delivery


def _hosted_subscription_checkout_url(request, payment):
    if payment.gateway == PaymentMethod.FLUTTERWAVE:
        return init_flutterwave_checkout(request, payment)
    if payment.gateway == PaymentMethod.PAYPAL:
        return init_paypal_checkout(request, payment)
    if payment.gateway == PaymentMethod.PAYSTACK:
        return init_paystack_checkout(request, payment)
    if payment.gateway == PaymentMethod.COINBASE:
        return init_coinbase_checkout(request, payment)
    raise ValueError("Unsupported payment gateway.")


def _verify_subscription_payment_now(payment):
    if payment.status == PaymentStatus.SUCCESS:
        return True, "Payment is already confirmed."

    if payment.gateway == PaymentMethod.FLUTTERWAVE:
        data = verify_flutterwave_transaction_by_reference(payment.reference)
        tx = data.get("data", {}) if isinstance(data, dict) else {}
        if data.get("status") == "success" and tx.get("status") == "successful":
            payment.mark_success(str(tx.get("id") or tx.get("tx_ref") or payment.reference), data)
            return True, "Flutterwave payment confirmed."
        if tx.get("status") in ["failed", "cancelled"]:
            payment.mark_failed(data)
            return False, "Flutterwave reported this payment as failed or cancelled."
        payment.gateway_response = data
        payment.save(update_fields=["gateway_response", "updated_at"])
        return False, "Flutterwave has not confirmed this payment yet."

    if payment.gateway == PaymentMethod.PAYSTACK:
        data = verify_paystack_transaction(payment.gateway_reference or payment.reference)
        tx = data.get("data", {}) if isinstance(data, dict) else {}
        if data.get("status") is True and tx.get("status") == "success":
            payment.mark_success(tx.get("reference") or payment.reference, data)
            return True, "Paystack payment confirmed."
        if tx.get("status") in ["failed", "abandoned"]:
            payment.mark_failed(data)
            return False, "Paystack reported this payment as failed or abandoned."
        payment.gateway_response = data
        payment.save(update_fields=["gateway_response", "updated_at"])
        return False, "Paystack has not confirmed this payment yet."

    if payment.gateway == PaymentMethod.PAYPAL:
        data = capture_paypal_order(payment)
        if data.get("status") == "COMPLETED":
            payment.mark_success(data.get("id", ""), data)
            return True, "PayPal payment confirmed."
        payment.gateway_response = data
        payment.save(update_fields=["gateway_response", "updated_at"])
        return False, "PayPal has not confirmed this payment yet."

    if payment.gateway == PaymentMethod.COINBASE:
        return payment.status == PaymentStatus.SUCCESS, "Coinbase confirmation is handled by secure webhook."

    if payment.gateway == PaymentMethod.MANUAL_CRYPTO:
        return False, "Manual crypto payments require admin review before activation."

    return False, "Unsupported payment gateway."


def _smartchat_payload(conversation, viewer_role="vendor"):
    last_message = conversation.messages.order_by("-created_at").first()
    message_rows = []
    for message in conversation.messages.order_by("-created_at")[:20]:
        from_me = (
            message.sender_type == SmartChatMessage.SENDER_ADMIN
            if viewer_role == "admin"
            else message.sender_type == SmartChatMessage.SENDER_USER
        )
        message_rows.append({
            "id": message.id,
            "message": message.message,
            "last_message": message.message,
            "sender_type": message.sender_type,
            "from_me": from_me,
            "created_at": message.created_at.isoformat() if message.created_at else "",
        })
    return {
        "id": conversation.id,
        "conversation_id": conversation.id,
        "title": conversation.title or conversation.customer_display,
        "subject": conversation.title or "Arolana support",
        "last_message": last_message.message if last_message else "",
        "unread_count": conversation.messages.filter(sender_type=SmartChatMessage.SENDER_USER).count() if viewer_role == "admin" else 0,
        "updated_at": conversation.last_message_at.isoformat() if conversation.last_message_at else "",
        "customer_name": conversation.customer_display,
        "status": conversation.status,
        "messages": list(reversed(message_rows)),
    }


def _staff_conversations_for_session(session):
    queryset = SmartChatConversation.objects.prefetch_related("messages").order_by("-last_message_at")
    if session.role == "admin":
        return queryset[:100]
    return queryset.filter(user=session.user)[:100]


def _get_or_create_staff_conversation(user, subject, metadata=None):
    conversation = (
        SmartChatConversation.objects
        .filter(user=user, selected_variants__staff_mobile_chat=True)
        .order_by("-last_message_at")
        .first()
    )
    if conversation:
        if subject and conversation.title != subject:
            conversation.title = subject
            conversation.save(update_fields=["title", "updated_at"])
        return conversation
    return SmartChatConversation.objects.create(
        user=user,
        status=SmartChatConversation.STATUS_ADMIN_REQUESTED,
        customer_name=user.get_full_name() or user.username or user.email,
        customer_email=user.email or "",
        title=subject or "Arolana staff chat",
        selected_variants={"staff_mobile_chat": True, **(metadata or {})},
    )


def _authenticate_staff_user(request, login_value, password):
    User = get_user_model()
    candidates = []
    login_value = _clean_text(login_value)
    if "@" in login_value:
        login_value = login_value.lower()

    direct_user = authenticate(request, username=login_value, password=password)
    if direct_user:
        candidates.append(direct_user)

    lookup = Q(email__iexact=login_value) | Q(username__iexact=login_value)
    clean_phone = _clean_phone(login_value)
    if clean_phone:
        lookup |= Q(phone_number=clean_phone)

    for user in User.objects.filter(lookup):
        if user not in candidates:
            candidates.append(user)

    for user in candidates:
        if not user.is_active:
            continue
        auth_user = authenticate(request, username=user.email, password=password)
        if auth_user:
            return auth_user
        auth_user = authenticate(request, username=user.username, password=password)
        if auth_user:
            return auth_user
        if user.check_password(password):
            return user
    return None


STAFF_LOGIN_CHALLENGE_SALT = "arolana.staff-mobile.login"
STAFF_LOGIN_CHALLENGE_MAX_AGE = 10 * 60
STAFF_PASSWORD_RESET_CHALLENGE_SALT = "arolana.staff-mobile.password-reset"
STAFF_PASSWORD_RESET_CHALLENGE_MAX_AGE = 10 * 60


def _mask_email(email):
    value = _clean_text(email).lower()
    if "@" not in value:
        return "your registered email"
    local, domain = value.split("@", 1)
    visible = local[:2] if len(local) > 2 else local[:1]
    return f"{visible}{'*' * max(2, len(local) - len(visible))}@{domain}"


def _find_user_by_identifier(identifier):
    User = get_user_model()
    value = _clean_text(identifier)
    if not value:
        return None
    lookup = Q(email__iexact=value) | Q(username__iexact=value)
    phone = _clean_phone(value)
    if phone:
        lookup |= Q(phone_number=phone)
    return User.objects.filter(lookup, is_active=True).first()


def _staff_role_profile(user, role):
    if role == "admin":
        return None if _is_admin_user(user) else "This account is not an admin account."
    if role == "vendor":
        return _vendor_profile_for_user(user) or "This account is not a vendor account."
    if role == "provider":
        # Provider is an optional role profile on the same Arolana User.
        # A valid user may authenticate first and set up the profile afterwards.
        return _provider_profile_for_user(user)
    if role == "rider":
        return (
            RiderProfile.objects.select_related("user")
            .filter(user=user, is_active=True)
            .first()
            or "Rider not found or inactive."
        )
    return "Invalid role."


def _staff_login_challenge(user, role, device_name, otp_type, rider=None):
    return signing.dumps(
        {
            "user_id": user.id,
            "role": role,
            "device_name": device_name,
            "otp_type": otp_type,
            "rider_id": rider.id if rider else None,
        },
        salt=STAFF_LOGIN_CHALLENGE_SALT,
        compress=True,
    )


def _load_staff_login_challenge(token):
    return signing.loads(
        token,
        salt=STAFF_LOGIN_CHALLENGE_SALT,
        max_age=STAFF_LOGIN_CHALLENGE_MAX_AGE,
    )


def _authenticated_staff_payload(session, request):
    user = session.user or (session.rider.user if session.rider else None)
    approval_status = "approved"
    kyc_status = "approved"
    subscription_status = "active"
    payload = {
        "success": True,
        "ok": True,
        "otp_required": False,
        "token": session.token,
        "role": session.role,
        "user": {
            "id": user.id if user else None,
            "email": user.email if user else "",
            "name": (user.get_full_name() or user.username or user.email) if user else "",
        },
        "session": _staff_session_payload(session),
    }
    if session.role == "vendor":
        profile = _vendor_profile_for_user(session.user)
        payload["vendor"] = _vendor_payload(profile, request)
        approval_status = profile.approval_status
        kyc_status = profile.kyc_status
        subscription_status = "active" if profile.subscription_active else "inactive"
    elif session.role == "provider":
        profile = _provider_profile_for_user(session.user)
        payload["provider"] = _service_provider_payload(profile, request) if profile else None
        payload["profile_required"] = not bool(profile)
        if profile:
            approval_status = profile.verification_status
            kyc_status = profile.kyc_status
            subscription_status = profile.subscription_status
        else:
            approval_status = "profile_required"
            kyc_status = "not_started"
            subscription_status = "inactive"
    elif session.role == "rider" and session.rider:
        payload["rider"] = _rider_payload(session.rider)
        approval_status = session.rider.kyc_status
        kyc_status = session.rider.kyc_status
        subscription_status = "not_required"
    payload.update({
        "approval_status": approval_status,
        "kyc_status": kyc_status,
        "subscription_status": subscription_status,
    })
    return payload


@csrf_exempt
@require_POST
def staff_login_api(request):
    data = _json_body(request)
    role = _clean_text(data.get("role") or "admin").lower()
    username = _clean_text(data.get("username") or data.get("email") or data.get("phone"))
    if "@" in username:
        username = username.lower()
    password = str(data.get("password") or data.get("pin") or "")
    device_name = _clean_text(data.get("device_name") or data.get("deviceName"))

    if role not in ["admin", "vendor", "provider", "rider"]:
        return _error("Invalid role.")
    if not username or not password:
        return _error("Username/phone and password are required.")

    user = _authenticate_staff_user(request, username, password)
    rider = None
    if not user and role == "rider":
        phone = _clean_phone(username)
        rider = (
            RiderProfile.objects.select_related("user")
            .filter(Q(phone=phone) | Q(user__email__iexact=username) | Q(user__username__iexact=username), is_active=True)
            .first()
        )
        credential = getattr(rider, "mobile_credential", None) if rider else None
        if credential and credential.check_pin(password):
            user = rider.user
    if not user:
        return _error("Invalid login details. Please check your email/phone and password.", status=403)

    profile = _staff_role_profile(user, role)
    if isinstance(profile, str):
        return _error(profile, status=403)
    if role == "rider":
        rider = profile

    if not user.email:
        return _error("This account has no email address for secure verification. Contact Arolana support.", status=403)

    otp_type = "email" if not getattr(user, "email_verified", False) and not _is_admin_user(user) else "login"
    otp = create_otp(user, user.email, otp_type)
    if not otp:
        return _error("We could not send your verification code. Please try again or contact Arolana support.", status=503)

    challenge_token = _staff_login_challenge(user, role, device_name, otp_type, rider)
    return JsonResponse({
        "success": True,
        "ok": True,
        "otp_required": True,
        "verification_type": otp_type,
        "challenge_token": challenge_token,
        "masked_email": _mask_email(user.email),
        "message": "Verification code sent to your email.",
    })


@csrf_exempt
@require_POST
def staff_login_verify_otp_api(request):
    data = _json_body(request)
    challenge_token = _clean_text(data.get("challenge_token"))
    otp_code = _clean_text(data.get("otp_code") or data.get("code"))
    if not challenge_token or not otp_code:
        return _error("Challenge token and verification code are required.")

    try:
        challenge = _load_staff_login_challenge(challenge_token)
    except signing.SignatureExpired:
        return _error("Verification session expired. Please login again.", status=403)
    except signing.BadSignature:
        return _error("Invalid verification session. Please login again.", status=403)

    User = get_user_model()
    user = User.objects.filter(id=challenge.get("user_id"), is_active=True).first()
    role = _clean_text(challenge.get("role")).lower()
    if not user or role not in ["admin", "vendor", "provider", "rider"]:
        return _error("Account is unavailable. Please login again.", status=403)

    profile = _staff_role_profile(user, role)
    if isinstance(profile, str):
        return _error(profile, status=403)

    otp_type = challenge.get("otp_type") or "login"
    success, message = verify_otp(user, otp_code, otp_type)
    if not success:
        return _error(message, status=403)

    if otp_type == "email" and not getattr(user, "email_verified", False):
        user.email_verified = True
        user.save(update_fields=["email_verified", "updated_at"])

    device_name = _clean_text(challenge.get("device_name"))
    if role == "rider":
        session = StaffMobileToken.issue(role=role, user=user, rider=profile, device_name=device_name)
    else:
        session = StaffMobileToken.issue(role=role, user=user, device_name=device_name)
    return JsonResponse(_authenticated_staff_payload(session, request))


@csrf_exempt
@require_POST
def staff_login_resend_otp_api(request):
    challenge_token = _clean_text(_json_body(request).get("challenge_token"))
    if not challenge_token:
        return _error("Verification session is required.")
    try:
        challenge = _load_staff_login_challenge(challenge_token)
    except signing.SignatureExpired:
        return _error("Verification session expired. Please login again.", status=403)
    except signing.BadSignature:
        return _error("Invalid verification session. Please login again.", status=403)

    User = get_user_model()
    user = User.objects.filter(id=challenge.get("user_id"), is_active=True).first()
    if not user:
        return _error("Account is unavailable. Please login again.", status=403)
    otp_type = challenge.get("otp_type") or "login"
    if not create_otp(user, user.email, otp_type):
        return _error("We could not resend your verification code. Please try again.", status=503)
    return JsonResponse({
        "success": True,
        "ok": True,
        "otp_required": True,
        "challenge_token": challenge_token,
        "masked_email": _mask_email(user.email),
        "message": "A new verification code was sent to your email.",
    })


@csrf_exempt
@require_POST
def staff_forgot_password_api(request):
    data = _json_body(request)
    identifier = _clean_text(data.get("identifier") or data.get("email") or data.get("phone"))
    if "@" in identifier:
        identifier = identifier.lower()
    if not identifier:
        return _error("Email, phone, or username is required.")

    user = _find_user_by_identifier(identifier)
    challenge_token = signing.dumps(
        {"user_id": user.id if user else 0, "otp_type": "password_reset"},
        salt=STAFF_PASSWORD_RESET_CHALLENGE_SALT,
        compress=True,
    )
    if user:
        if not user.email:
            return _error("This account has no email address for password recovery. Contact Arolana support.", status=403)
        if not create_otp(user, user.email, "password_reset"):
            return _error("We could not send the password reset code. Please try again or contact support.", status=503)

    return JsonResponse({
        "success": True,
        "ok": True,
        "otp_required": True,
        "challenge_token": challenge_token,
        "masked_email": _mask_email(user.email) if user else "your registered email",
        "message": "If this account exists, a password reset code has been sent to its registered email.",
    })


@csrf_exempt
@require_POST
def staff_reset_password_api(request):
    data = _json_body(request)
    challenge_token = _clean_text(data.get("challenge_token"))
    otp_code = _clean_text(data.get("otp_code") or data.get("code"))
    new_password = str(data.get("new_password") or "")
    if not challenge_token or not otp_code or not new_password:
        return _error("Verification code and new password are required.")
    try:
        challenge = signing.loads(
            challenge_token,
            salt=STAFF_PASSWORD_RESET_CHALLENGE_SALT,
            max_age=STAFF_PASSWORD_RESET_CHALLENGE_MAX_AGE,
        )
    except signing.SignatureExpired:
        return _error("Password reset session expired. Please start again.", status=403)
    except signing.BadSignature:
        return _error("Invalid password reset session. Please start again.", status=403)

    User = get_user_model()
    user = User.objects.filter(id=challenge.get("user_id"), is_active=True).first()
    if not user:
        return _error("Invalid or expired verification code.", status=403)
    success, message = verify_otp(user, otp_code, "password_reset")
    if not success:
        return _error(message, status=403)
    try:
        validate_password(new_password, user=user)
    except ValidationError as error:
        return _error("; ".join(error.messages if hasattr(error, "messages") else [str(error)]))

    user.set_password(new_password)
    user.save(update_fields=["password", "updated_at"])
    StaffMobileToken.objects.filter(user=user, is_active=True).update(is_active=False, updated_at=timezone.now())
    return JsonResponse({
        "success": True,
        "ok": True,
        "message": "Password updated successfully. Sign in with your new password.",
    })


@require_GET
def staff_me_api(request):
    try:
        session = _auth_staff(request)
    except PermissionError as error:
        return _error(error, status=403)
    return JsonResponse(_authenticated_staff_payload(session, request))


@csrf_exempt
@require_POST
def staff_logout_api(request):
    try:
        session = _auth_staff(request)
    except PermissionError as error:
        return _error(error, status=403)
    session.is_active = False
    session.save(update_fields=["is_active", "updated_at"])
    return JsonResponse({"success": True, "ok": True, "message": "Signed out successfully."})


def _unique_store_slug(store_name):
    base = slugify(store_name or "vendor") or "vendor"
    slug = base
    index = 2
    while VendorProfile.objects.filter(store_slug=slug).exists():
        slug = f"{base}-{index}"
        index += 1
    return slug


@csrf_exempt
@require_POST
def provider_register_api(request):
    return _error(
        "Login with your existing Arolana account, then use "
        "/api/provider/register/ to set up or continue your Provider profile.",
        status=410,
    )


@csrf_exempt
@require_POST
def vendor_register_api(request):
    data = _json_body(request)
    User = get_user_model()
    email = _clean_text(data.get("email")).lower()
    password = _clean_text(data.get("password") or data.get("pin"))
    full_name = _clean_text(data.get("full_name") or data.get("name"))
    phone = _clean_phone(data.get("phone_number") or data.get("phone"))
    store_name = _clean_text(data.get("store_name"))
    vendor_type = _clean_text(data.get("vendor_type") or "retailer")

    if not email or not password or not store_name:
        return _error("Email, password/PIN, and store name are required.")
    if vendor_type not in dict(VendorProfile.VENDOR_TYPE_CHOICES):
        return _error("Invalid vendor type.")
    if User.objects.filter(email__iexact=email).exists():
        return _error("An account with this email already exists.", status=409)

    with transaction.atomic():
        username = email.split("@")[0]
        suffix = 2
        original = username
        while User.objects.filter(username=username).exists():
            username = f"{original}{suffix}"
            suffix += 1
        user = User.objects.create_user(username=username, email=email, password=password)
        user.user_type = "vendor"
        if phone:
            try:
                user.phone_number = phone
            except Exception:
                pass
        if full_name:
            parts = full_name.split()
            user.first_name = parts[0]
            user.last_name = " ".join(parts[1:])
        user.save()
        profile = VendorProfile.objects.create(
            user=user,
            store_name=store_name,
            store_slug=_unique_store_slug(store_name),
            description=_clean_text(data.get("description")),
            company_name=_clean_text(data.get("company_name") or store_name),
            vendor_type=vendor_type,
            country=_clean_text(data.get("country") or "Nigeria"),
            business_address=_clean_text(data.get("business_address")),
            manufacturer_address=_clean_text(data.get("manufacturer_address")),
            warehouse_address=_clean_text(data.get("warehouse_address")),
            support_email=email,
            support_phone=phone,
            pickup_phone=phone,
            pickup_address=_clean_text(data.get("warehouse_address") or data.get("business_address")),
            approval_status="pending",
            is_verified=False,
            is_active=True,
        )
        KYCRecord.objects.get_or_create(
            vendor=profile,
            defaults={
                "legal_business_name": profile.company_name or profile.store_name,
                "business_address": profile.business_address or profile.pickup_address or "Pending",
                "city": _clean_text(data.get("city") or "Pending"),
                "state": _clean_text(data.get("state") or "Pending"),
                "country": profile.country or "Nigeria",
                "postal_code": _clean_text(data.get("postal_code") or "000000"),
                "business_phone": phone or "Pending",
                "business_email": email,
                "authorized_person_name": full_name or profile.store_name,
                "authorized_person_title": _clean_text(data.get("authorized_person_title") or "Owner"),
                "authorized_person_email": email,
                "authorized_person_phone": phone or "Pending",
                "kyc_status": "not_started",
            },
        )
        _notify(user, "Vendor registration received", "Your vendor/manufacturer profile has been created. Complete KYC and bank details for approval.")

    session = StaffMobileToken.issue(role="vendor", user=user, device_name=_clean_text(data.get("device_name")))
    return JsonResponse({"success": True, "session": _staff_session_payload(session), "vendor": _vendor_payload(profile, request)})


def _unique_username_from_email(email):
    User = get_user_model()
    base = slugify(str(email).split("@")[0]) or "rider"
    username = base
    suffix = 2
    while User.objects.filter(username=username).exists():
        username = f"{base}{suffix}"
        suffix += 1
    return username


@csrf_exempt
@require_POST
def rider_register_api(request):
    User = get_user_model()
    email = _clean_text(request.POST.get("email")).lower()
    password = _clean_text(request.POST.get("password") or request.POST.get("pin"))
    full_name = _clean_text(request.POST.get("full_name") or request.POST.get("name"))
    phone = _clean_phone(request.POST.get("phone") or request.POST.get("phone_number"))
    emergency_phone = _clean_phone(request.POST.get("emergency_phone"))
    rider_type = _clean_text(request.POST.get("rider_type") or RiderProfile.RIDER_INDEPENDENT)
    vehicle_id = request.POST.get("vehicle_id") or request.POST.get("vehicle")
    about = _clean_text(request.POST.get("about"))

    if not email or not password or not full_name or not phone:
        return _error("Full name, email, phone and password/PIN are required.")
    try:
        validate_email(email)
    except ValidationError:
        return _error("Enter a valid email address.")
    if User.objects.filter(email__iexact=email).exists():
        return _error("An account with this email already exists.", status=409)
    if rider_type not in dict(RiderProfile.RIDER_TYPE_CHOICES):
        return _error("Invalid rider type.")
    vehicle = DeliveryVehicle.objects.filter(id=vehicle_id, is_active=True).first()
    if not vehicle:
        return _error("Choose a valid vehicle.")
    if len(about) < 20:
        return _error("About rider should be at least 20 characters.")

    required_files = {
        "id_document": request.FILES.get("id_document"),
        "driver_license": request.FILES.get("driver_license"),
        "vehicle_document": request.FILES.get("vehicle_document"),
    }
    missing = [label.replace("_", " ").title() for label, file in required_files.items() if not file]
    if missing:
        return _error(f"{', '.join(missing)} required for rider KYC.")

    with transaction.atomic():
        user = User.objects.create_user(username=_unique_username_from_email(email), email=email, password=password)
        user.user_type = "customer"
        parts = full_name.split()
        user.first_name = parts[0]
        user.last_name = " ".join(parts[1:])
        if phone:
            try:
                user.phone_number = phone
            except Exception:
                pass
        user.email_verified = False
        user.save()

        rider = RiderProfile.objects.create(
            user=user,
            rider_type=rider_type,
            vehicle=vehicle,
            phone=phone,
            emergency_phone=emergency_phone,
            about=about,
            kyc_status=RiderProfile.KYC_PENDING,
            is_online=False,
            is_available=False,
            profile_edit_status="pending_admin_review",
            profile_edit_requested_at=timezone.now(),
        )
        rider.id_document = required_files["id_document"]
        rider.driver_license = required_files["driver_license"]
        rider.vehicle_document = required_files["vehicle_document"]
        if request.FILES.get("profile_photo"):
            rider.profile_photo = request.FILES["profile_photo"]
        if request.FILES.get("dashboard_image"):
            rider.dashboard_image = request.FILES["dashboard_image"]
        rider.save()

        credential = RiderCredential.objects.create(rider=rider)
        credential.set_pin(password)
        credential.save(update_fields=["pin_hash", "updated_at"])
        RiderWallet.objects.get_or_create(rider=rider)

        for admin in get_user_model().objects.filter(Q(is_staff=True) | Q(is_superuser=True), is_active=True)[:20]:
            _notify(admin, "New rider registration", f"{full_name} submitted rider KYC and is waiting for email verification/admin approval.", "rider", {"rider_id": rider.id})
        otp = create_otp(user, user.email, "email")

    return JsonResponse({
        "success": True,
        "requires_email_verification": True,
        "message": "Rider registration submitted. Enter the OTP sent to your email before entering the app.",
        "email": email,
        "otp_sent": bool(otp),
        "rider": _rider_payload(rider),
    })


@csrf_exempt
@require_POST
def rider_verify_email_api(request):
    data = _json_body(request)
    email = _clean_text(data.get("email")).lower()
    otp_code = _clean_text(data.get("otp") or data.get("otp_code") or data.get("code"))
    device_name = _clean_text(data.get("device_name") or data.get("deviceName"))
    if not email or not otp_code:
        return _error("Email and OTP code are required.")
    User = get_user_model()
    user = User.objects.filter(email__iexact=email).first()
    if not user:
        return _error("Rider account not found.", status=404)
    success, message = verify_otp(user, otp_code, "email")
    if not success:
        return _error(message)
    user.email_verified = True
    user.save(update_fields=["email_verified", "updated_at"])
    rider = RiderProfile.objects.filter(user=user).first()
    if not rider:
        return _error("Rider profile not found.", status=404)
    _notify(user, "Email verified", "Your rider email has been verified. Admin will review your rider KYC before dispatch access.", "security", {"rider_id": rider.id})
    session = StaffMobileToken.issue(role="rider", rider=rider, device_name=device_name)
    return JsonResponse({
        "success": True,
        "message": "Email verified. Your rider profile is pending admin KYC approval.",
        "session": _staff_session_payload(session),
        "rider": _rider_payload(rider),
    })


@csrf_exempt
@require_POST
def rider_resend_email_otp_api(request):
    data = _json_body(request)
    email = _clean_text(data.get("email")).lower()
    User = get_user_model()
    user = User.objects.filter(email__iexact=email).first()
    if not user:
        return _error("Rider account not found.", status=404)
    if user.email_verified:
        return JsonResponse({"success": True, "message": "Email is already verified."})
    otp = create_otp(user, user.email, "email")
    if not otp:
        return _error("Unable to send OTP email right now.")
    return JsonResponse({"success": True, "message": "A new verification OTP has been sent."})


@require_GET
def rider_registration_options_api(request):
    return JsonResponse({
        "success": True,
        "vehicles": [
            {"id": vehicle.id, "name": vehicle.name, "vehicle_type": vehicle.vehicle_type}
            for vehicle in DeliveryVehicle.objects.filter(is_active=True).order_by("name")
        ],
        "rider_types": [{"key": key, "label": label} for key, label in RiderProfile.RIDER_TYPE_CHOICES],
    })


@require_GET
def vendor_me_api(request):
    try:
        session, profile = _require_vendor_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    return JsonResponse({"success": True, "session": _staff_session_payload(session), "vendor": _vendor_payload(profile, request)})


@csrf_exempt
@require_POST
def vendor_profile_update_api(request):
    data = _json_body(request)
    try:
        session, profile = _require_vendor_session(request)
    except PermissionError as error:
        return _error(error, status=403)

    fields = [
        "store_name", "description", "company_name", "vendor_type", "country", "business_address",
        "manufacturer_address", "warehouse_address", "support_email", "support_phone", "website",
        "preferred_language", "preferred_currency",
        "pickup_contact_name", "pickup_phone", "pickup_address", "factory_name", "factory_video_url",
        "production_capacity", "quality_control_details", "export_countries", "main_product_categories",
    ]
    for field in fields:
        if field in data:
            value = _clean_text(data.get(field))
            if field == "vendor_type" and value not in dict(VendorProfile.VENDOR_TYPE_CHOICES):
                continue
            if field == "preferred_language" and value.lower() not in {
                "english", "pidgin", "yoruba", "igbo", "hausa", "french",
            }:
                continue
            if field == "preferred_currency":
                value = value.upper()
                if value not in {"NGN", "USD", "GBP", "EUR", "CNY", "CAD"}:
                    continue
            setattr(profile, field, value)
    for field in ["pickup_latitude", "pickup_longitude"]:
        if field in data and data.get(field) not in [None, ""]:
            setattr(profile, field, _money(data.get(field), "0.0000000"))
    for field in ["years_in_business", "number_of_employees"]:
        if field in data and str(data.get(field)).isdigit():
            setattr(profile, field, int(data.get(field)))
    profile.save()
    return JsonResponse({"success": True, "vendor": _vendor_payload(profile, request)})


@csrf_exempt
@require_POST
def vendor_profile_photo_api(request):
    try:
        _, profile = _require_vendor_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    uploaded = request.FILES.get("photo") or request.FILES.get("image") or request.FILES.get("logo")
    if not uploaded:
        return _error("Profile photo/logo file is required.")
    profile.store_logo = uploaded
    profile.save(update_fields=["store_logo", "updated_at"])
    return JsonResponse({"success": True, "message": "Profile photo updated.", "vendor": _vendor_payload(profile, request)})


@csrf_exempt
@require_POST
def vendor_profile_banner_api(request):
    try:
        _, profile = _require_vendor_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    uploaded = request.FILES.get("banner") or request.FILES.get("image") or request.FILES.get("store_banner")
    if not uploaded:
        return _error("Store banner file is required.")
    profile.store_banner = uploaded
    profile.save(update_fields=["store_banner", "updated_at"])
    return JsonResponse({"success": True, "message": "Store banner updated.", "vendor": _vendor_payload(profile, request)})


@csrf_exempt
@require_POST
def vendor_change_password_api(request):
    data = _json_body(request)
    try:
        session, profile = _require_vendor_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    current = _clean_text(data.get("current_password") or data.get("current_pin"))
    new_password = _clean_text(data.get("new_password") or data.get("new_pin"))
    confirm = _clean_text(data.get("confirm_password") or data.get("confirm_pin"))
    if not current or not new_password:
        return _error("Current password and new password are required.")
    if new_password != confirm:
        return _error("New password and confirmation do not match.")
    if not profile.user.check_password(current):
        return _error("Current password is incorrect.", status=403)
    try:
        validate_password(new_password, profile.user)
    except ValidationError as error:
        return _error(" ".join(error.messages))
    profile.user.set_password(new_password)
    profile.user.save(update_fields=["password"])
    email_sent = send_vendor_password_changed_email(profile.user)
    email = (profile.user.email or "").strip()
    message = "Password/PIN changed successfully."
    if email_sent:
        message += f" A security confirmation email was sent to {email}."
    elif email:
        message += " Your security notification was saved, but the confirmation email could not be delivered right now."
    _notify(
        profile.user,
        "Vendor security updated",
        "Your Arolana vendor password/PIN was changed successfully. Contact support immediately if you did not make this change.",
        "security",
    )
    return JsonResponse({
        "success": True,
        "message": message,
        "email_sent": email_sent,
        "email": email,
        "session": _staff_session_payload(session),
    })


@csrf_exempt
@require_POST
def vendor_language_setting_api(request):
    data = _json_body(request)
    try:
        _, profile = _require_vendor_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    language = _clean_text(data.get("language") or data.get("preferred_language")).lower()
    if language not in {"english", "pidgin", "yoruba", "igbo", "hausa", "french"}:
        return _error("Unsupported language.")
    profile.preferred_language = language
    profile.save(update_fields=["preferred_language", "updated_at"])
    return JsonResponse({"success": True, "message": "Language preference saved.", "vendor": _vendor_payload(profile, request)})


@csrf_exempt
@require_POST
def vendor_currency_setting_api(request):
    data = _json_body(request)
    try:
        _, profile = _require_vendor_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    currency = _clean_text(data.get("currency") or data.get("preferred_currency")).upper()
    if currency not in {"NGN", "USD", "GBP", "EUR", "CNY", "CAD"}:
        return _error("Unsupported currency.")
    profile.preferred_currency = currency
    profile.save(update_fields=["preferred_currency", "updated_at"])
    return JsonResponse({"success": True, "message": "Currency preference saved.", "vendor": _vendor_payload(profile, request)})


@csrf_exempt
@require_POST
def vendor_kyc_submit_api(request):
    data = request.POST.dict() if request.POST else _json_body(request)
    try:
        session, profile = _require_vendor_session(request)
    except PermissionError as error:
        return _error(error, status=403)

    record, _ = KYCRecord.objects.get_or_create(
        vendor=profile,
        defaults={
            "legal_business_name": profile.company_name or profile.store_name,
            "business_address": profile.business_address or profile.pickup_address or "Pending",
            "city": _clean_text(data.get("city") or "Pending"),
            "state": _clean_text(data.get("state") or "Pending"),
            "country": profile.country or "Nigeria",
            "postal_code": _clean_text(data.get("postal_code") or "000000"),
            "business_phone": profile.support_phone or profile.pickup_phone or "Pending",
            "business_email": profile.support_email or session.user.email,
            "authorized_person_name": session.user.get_full_name() or profile.store_name,
            "authorized_person_title": "Owner",
            "authorized_person_email": session.user.email,
            "authorized_person_phone": profile.support_phone or profile.pickup_phone or "Pending",
        },
    )
    editable = [
        "legal_business_name", "registration_number", "tax_id", "vat_number", "business_address",
        "city", "state", "country", "postal_code", "business_phone", "business_email", "website",
        "business_type", "bank_name", "bank_account_name", "bank_account_number", "bank_routing_number",
        "iban", "swift_code", "factory_address", "warehouse_address", "manufacturer_certificate_number",
        "import_export_license_number", "authorized_person_name", "authorized_person_title",
        "authorized_person_email", "authorized_person_phone",
    ]
    for field in editable:
        if field in data:
            setattr(record, field, _clean_text(data.get(field)))
    record.kyc_status = "pending"
    record.submitted_at = timezone.now()
    record.rejection_reason = ""
    record.save()

    for key, uploaded in request.FILES.items():
        if key.startswith("document_"):
            doc_type = key.replace("document_", "")[:30]
            valid_types = dict(KYCDocument.DOCUMENT_TYPES)
            KYCDocument.objects.create(
                vendor=profile,
                document_type=doc_type if doc_type in valid_types else "other",
                document_file=uploaded,
                description=f"Uploaded from staff mobile: {key}",
            )
    return JsonResponse({"success": True, "kyc_status": record.kyc_status, "message": "KYC submitted for admin review."})


@require_GET
def vendor_kyc_status_api(request):
    try:
        _, profile = _require_vendor_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    record = getattr(profile, "kyc_record", None)
    return JsonResponse({
        "success": True,
        "kyc": {
            "status": record.kyc_status if record else "not_started",
            "rejection_reason": record.rejection_reason if record else "",
            "review_notes": record.review_notes if record else "",
            "documents": [
                {"id": doc.id, "type": doc.document_type, "status": doc.verification_status}
                for doc in profile.kyc_documents.all()[:50]
            ],
        },
    })


def _bank_payload(account):
    return {
        "id": account.id,
        "bank_name": account.bank_name,
        "account_name": account.account_name,
        "account_number": account.account_number,
        "bank_country": account.bank_country,
        "preferred_currency": account.preferred_currency,
        "is_default": account.is_default,
        "is_verified": account.is_verified,
    }


@require_GET
def vendor_bank_account_api(request):
    try:
        _, profile = _require_vendor_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    accounts = profile.bank_accounts.all()
    return JsonResponse({"success": True, "bank_accounts": [_bank_payload(account) for account in accounts]})


@csrf_exempt
@require_POST
def vendor_bank_account_save_api(request):
    data = _json_body(request)
    try:
        _, profile = _require_vendor_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    account_id = data.get("id")
    account = profile.bank_accounts.filter(id=account_id).first() if account_id else None
    if not account:
        account = VendorBankAccount(vendor=profile)
    required = ["bank_name", "account_name", "account_number"]
    for field in required:
        if not _clean_text(data.get(field) or getattr(account, field, "")):
            return _error(f"{field.replace('_', ' ').title()} is required.")
    for field in [
        "bank_name", "account_name", "account_number", "bank_country", "swift_code", "iban",
        "routing_number", "sort_code", "bank_address", "preferred_currency",
    ]:
        if field in data:
            setattr(account, field, _clean_text(data.get(field)))
    account.is_default = bool(data.get("is_default", account.is_default))
    account.is_verified = False
    account.save()
    return JsonResponse({"success": True, "bank_account": _bank_payload(account)})


@require_GET
def vendor_wallet_api(request):
    try:
        _, profile = _require_vendor_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    wallet = _vendor_wallet(profile)
    transactions = profile.transactions.select_related("wallet")[:50]
    withdrawals = profile.withdrawals.select_related("bank_account")[:25]
    return JsonResponse({
        "success": True,
        "wallet": {
            "available_balance": str(wallet.available_balance),
            "pending_balance": str(wallet.pending_balance),
            "withdrawable_balance": str(wallet.withdrawable_balance),
            "total_earnings": str(wallet.total_earnings),
            "total_withdrawn": str(wallet.total_withdrawn),
            "currency": wallet.currency,
        },
        "transactions": [
            {
                "id": tx.id,
                "type": tx.transaction_type,
                "amount": str(tx.amount),
                "balance_after": str(tx.balance_after),
                "reference": tx.reference,
                "description": tx.description,
                "created_at": tx.created_at.isoformat() if tx.created_at else "",
            }
            for tx in transactions
        ],
        "withdrawals": [
            {
                "id": withdrawal.id,
                "amount": str(withdrawal.amount),
                "currency": withdrawal.currency,
                "status": withdrawal.status,
                "bank_account": withdrawal.bank_account.bank_name if withdrawal.bank_account else "",
                "requested_at": withdrawal.requested_at.isoformat() if withdrawal.requested_at else "",
            }
            for withdrawal in withdrawals
        ],
    })


@csrf_exempt
@require_POST
def vendor_withdrawal_request_api(request):
    data = _json_body(request)
    try:
        _, profile = _require_vendor_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    wallet = _vendor_wallet(profile)
    amount = _money(data.get("amount"))
    if amount <= 0:
        return _error("Withdrawal amount must be greater than zero.")
    if amount > wallet.withdrawable_balance:
        return _error("Withdrawal amount is higher than your withdrawable balance.", status=403)
    bank = profile.bank_accounts.filter(id=data.get("bank_account_id")).first() or profile.bank_accounts.filter(is_default=True).first()
    if not bank:
        return _error("Add a bank account before requesting withdrawal.")
    withdrawal = VendorWithdrawal.objects.create(vendor=profile, bank_account=bank, amount=amount, currency=wallet.currency)
    VendorTransaction.objects.create(
        vendor=profile,
        wallet=wallet,
        transaction_type="withdrawal_request",
        amount=-amount,
        balance_after=wallet.withdrawable_balance,
        reference=f"WD-{withdrawal.id}",
        description="Withdrawal request submitted for admin review.",
    )
    return JsonResponse({"success": True, "withdrawal_id": withdrawal.id, "message": "Withdrawal request submitted."})


def _product_payload(product):
    image = _absolute_media_url(None, product.main_image, "product_card") if product.main_image else ""
    detail_image = _absolute_media_url(None, product.main_image, "product_detail") if product.main_image else ""
    original_image = _absolute_original_media_url(None, product.main_image) if product.main_image else ""
    gallery = []
    try:
        gallery = [
            {
                "id": item.id,
                "image": _absolute_media_url(None, item.image, "product_gallery") if item.image else "",
                "url": _absolute_media_url(None, item.image, "product_gallery") if item.image else "",
                "thumbnail_url": _absolute_media_url(None, item.image, "product_gallery") if item.image else "",
                "image_url": _absolute_media_url(None, item.image, "product_gallery") if item.image else "",
                "original_url": _absolute_original_media_url(None, item.image) if item.image else "",
                "is_main": item.is_main,
                "order": item.order,
            }
            for item in product.images.filter(is_active=True).order_by("-is_main", "order", "id")[:20]
        ]
    except Exception:
        gallery = []
    variants = []
    try:
        variants = [
            {
                "id": variant.id,
                "variant_type": variant.variant_type,
                "name": variant.name,
                "value": variant.value,
                "sku": variant.sku,
                "price_adjustment": str(variant.price_adjustment),
                "stock_quantity": variant.stock_quantity,
                "image": _absolute_media_url(None, variant.image, "product_gallery") if variant.image else "",
                "thumbnail_url": _absolute_media_url(None, variant.image, "product_card") if variant.image else "",
                "image_url": _absolute_media_url(None, variant.image, "product_gallery") if variant.image else "",
                "original_url": _absolute_original_media_url(None, variant.image) if variant.image else "",
                "is_active": variant.is_active,
            }
            for variant in product.variants.filter(is_active=True).order_by("variant_type", "name", "value")[:30]
        ]
    except Exception:
        variants = []
    vendor_profile = getattr(getattr(product, "vendor", None), "vendor_profile", None)
    condition_value = getattr(product, "condition", "") or ""
    condition_label = getattr(product, "condition_label", "") or condition_value.replace("_", " ").title()
    return {
        "id": product.id,
        "slug": product.slug,
        "name": product.name,
        "sku": product.sku,
        "manufacturer_sku": product.manufacturer_sku,
        "description": str(product.description or ""),
        "specifications": str(product.specifications or ""),
        "price": str(product.price),
        "wholesale_price": str(product.wholesale_price or ""),
        "bulk_price": str(product.bulk_price or ""),
        "stock_quantity": product.stock_quantity,
        "available_stock": product.available_stock,
        "approval_status": product.approval_status,
        "is_active": product.is_active,
        "is_in_stock": product.is_in_stock,
        "minimum_order_quantity": product.minimum_order_quantity,
        "lead_time_days": product.lead_time_days,
        "country_of_origin": product.country_of_origin,
        "condition": condition_label,
        "condition_label": condition_label,
        "condition_value": condition_value,
        "product_condition": condition_value,
        "vendor_name": getattr(product, "vendor_display_name", "") or (getattr(vendor_profile, "store_name", "") if vendor_profile else ""),
        "vendor_verified": bool(getattr(product, "vendor_verified", False)),
        "vendor_package": getattr(product, "vendor_package_name", "") or (getattr(vendor_profile, "active_plan_name", "") if vendor_profile else ""),
        "vendor_package_name": getattr(product, "vendor_package_name", "") or (getattr(vendor_profile, "active_plan_name", "") if vendor_profile else ""),
        "location": getattr(product, "location_label", "") or "",
        "location_label": getattr(product, "location_label", "") or "",
        "warranty_description": product.warranty_description,
        "image": image,
        "thumbnail_url": image,
        "image_url": detail_image,
        "original_url": original_image,
        "main_image": image,
        "main_image_url": detail_image,
        "images": gallery,
        "product_images": gallery,
        "gallery_count": len(gallery),
        "variants": variants,
        "variant_count": len(variants),
        "created_at": product.created_at.isoformat() if product.created_at else "",
    }


@require_GET
def vendor_catalog_options_api(request):
    try:
        _require_vendor_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    categories = Category.objects.filter(is_active=True).order_by("name")[:500]
    brands = Brand.objects.filter(is_active=True).order_by("name")[:300]
    return JsonResponse({
        "success": True,
        "categories": [{"id": c.id, "name": c.name, "parent_id": c.parent_id} for c in categories],
        "brands": [{"id": b.id, "name": b.name} for b in brands],
        "vendor_types": [{"value": value, "label": label} for value, label in VendorProfile.VENDOR_TYPE_CHOICES],
    })


@require_GET
def vendor_products_api(request):
    try:
        _, profile = _require_vendor_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    products = Product.objects.filter(vendor=profile.user).select_related("category", "brand").order_by("-created_at")
    status = _clean_text(request.GET.get("status"))
    q = _clean_text(request.GET.get("q"))
    if status:
        products = products.filter(approval_status=status)
    if q:
        products = products.filter(Q(name__icontains=q) | Q(sku__icontains=q) | Q(manufacturer_sku__icontains=q))
    return JsonResponse({"success": True, "products": [_product_payload(product) for product in products[:120]]})


@csrf_exempt
@require_POST
def vendor_product_create_api(request):
    data = _json_body(request)
    try:
        _, profile = _require_vendor_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    if not profile.can_upload_products:
        return _error("Complete admin approval and KYC before uploading products.", status=403)
    apply_vendor_subscription_benefits(profile, user_subscription_tier(profile.user))
    profile.refresh_from_db()
    current_product_count = Product.objects.filter(vendor=profile.user).exclude(
        approval_status__in=["rejected", "draft"]
    ).count()
    product_limit_reached = (
        profile.product_limit != -1
        and current_product_count >= profile.product_limit
    )
    category = Category.objects.filter(id=data.get("category_id")).first()
    if not category:
        category = Category.objects.filter(is_active=True).order_by("name", "id").first() or Category.objects.order_by("id").first()
    if not category:
        return _error("Create at least one product category in Django admin before vendor product upload.")
    brand = Brand.objects.filter(id=data.get("brand_id")).first() if data.get("brand_id") else None
    name = _clean_text(data.get("name"))
    if not name:
        return _error("Product name is required.")
    product = Product.objects.create(
        vendor=profile.user,
        category=category,
        brand=brand,
        name=name,
        slug="",
        sku=_clean_text(data.get("sku")),
        manufacturer_sku=_clean_text(data.get("manufacturer_sku")),
        description=_clean_text(data.get("description") or name),
        specifications=_clean_text(data.get("specifications")),
        price=_money(data.get("price"), "0.01"),
        compare_price=_money(data.get("compare_price")) if data.get("compare_price") else None,
        wholesale_price=_money(data.get("wholesale_price")) if data.get("wholesale_price") else None,
        bulk_price=_money(data.get("bulk_price")) if data.get("bulk_price") else None,
        stock_quantity=int(data.get("stock_quantity") or 0),
        minimum_order_quantity=max(1, int(data.get("minimum_order_quantity") or 1)),
        moq_unit=_clean_text(data.get("moq_unit") or "unit"),
        lead_time_days=int(data.get("lead_time_days") or 0) or None,
        country_of_origin=_clean_text(data.get("country_of_origin") or profile.country),
        manufacturer_address=_clean_text(data.get("manufacturer_address") or profile.manufacturer_address),
        certifications=data.get("certifications") if isinstance(data.get("certifications"), list) else [],
        approval_status="draft" if product_limit_reached else "pending",
        is_active=False,
    )
    if product_limit_reached:
        return JsonResponse({
            "success": True,
            "allowed": False,
            "reason": "product_limit_reached",
            "draft_saved": True,
            "message": (
                f"Product saved as draft. Your current plan allows {profile.product_limit} "
                f"product(s), and you have used {current_product_count}/{profile.product_limit}. "
                "Upgrade your subscription to publish this product."
            ),
            "product": _product_payload(product),
        })
    _notify(profile.user, "Product submitted", f"{product.name} is pending admin approval.", "product", {"product_id": product.id})
    return JsonResponse({
        "success": True,
        "allowed": True,
        "reason": None,
        "message": "Product saved and submitted for admin approval.",
        "product": _product_payload(product),
    })


@csrf_exempt
@require_POST
def vendor_product_update_api(request, product_id):
    data = _json_body(request)
    try:
        _, profile = _require_vendor_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    product = Product.objects.filter(id=product_id, vendor=profile.user).first()
    if not product:
        return _error("Product not found.", status=404)
    editable = [
        "name", "manufacturer_sku", "description", "specifications", "moq_unit",
        "country_of_origin", "manufacturer_address", "warranty_description",
    ]
    for field in editable:
        if field in data:
            setattr(product, field, _clean_text(data.get(field)))
    for field in ["price", "compare_price", "wholesale_price", "bulk_price", "sample_price"]:
        if field in data:
            setattr(product, field, _money(data.get(field)) if data.get(field) not in [None, ""] else None)
    for field in ["stock_quantity", "low_stock_threshold", "minimum_order_quantity", "lead_time_days", "warranty_years"]:
        if field in data and str(data.get(field)).isdigit():
            setattr(product, field, int(data.get(field)))
    if "certifications" in data and isinstance(data.get("certifications"), list):
        product.certifications = data.get("certifications")
    elif "certifications" in data:
        product.certifications = [item.strip() for item in str(data.get("certifications") or "").split(",") if item.strip()]
    condition = _clean_text(data.get("condition") or data.get("product_condition"))
    if condition and condition in dict(Product.PRODUCT_CONDITION_CHOICES):
        product.condition = condition
    product.approval_status = "pending"
    product.is_active = False
    product.resubmitted_at = timezone.now()
    product.save()
    return JsonResponse({"success": True, "product": _product_payload(product), "message": "Product updated and submitted for review."})


@csrf_exempt
@require_POST
def vendor_product_submit_review_api(request, product_id):
    try:
        _, profile = _require_vendor_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    product = Product.objects.filter(id=product_id, vendor=profile.user).first()
    if not product:
        return _error("Product not found.", status=404)
    product.approval_status = "pending"
    product.is_active = False
    product.resubmitted_at = timezone.now()
    product.save(update_fields=["approval_status", "is_active", "resubmitted_at", "updated_at"])
    return JsonResponse({"success": True, "product": _product_payload(product)})


@csrf_exempt
@require_POST
def vendor_product_images_api(request, product_id):
    try:
        _, profile = _require_vendor_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    product = Product.objects.filter(id=product_id, vendor=profile.user).first()
    if not product:
        return _error("Product not found.", status=404)
    image_file = request.FILES.get("image")
    if not image_file:
        return _error("Image file is required.")
    upload_policy = inspect_vendor_image_upload(image_file, profile.user)
    if not upload_policy.get("allowed", True):
        return _vendor_upload_policy_error(upload_policy)
    is_main = _bool_value(request.POST.get("is_main"))
    apply_vendor_subscription_benefits(profile, user_subscription_tier(profile.user))
    profile.refresh_from_db()
    gallery_count = product.images.count()
    image_limit = profile.image_limit
    if image_limit != -1 and gallery_count >= image_limit:
        return _subscription_limit_error()
    product_image = ProductImage.objects.create(
        product=product,
        image=image_file,
        alt_text=_clean_text(request.POST.get("alt_text") or product.name),
        is_main=is_main or gallery_count == 0,
        order=_int_value(request.POST.get("order"), gallery_count),
    )
    set_protected_image_uploader(product_image, "image", profile.user)
    duplicate_warning = duplicate_warning_payload(product_image, "image")
    if product_image.is_main or not product.main_image:
        product.main_image = product_image.image
    product.approval_status = "pending"
    product.is_active = False
    product.resubmitted_at = timezone.now()
    product.save(update_fields=["main_image", "approval_status", "is_active", "resubmitted_at", "updated_at"])
    if product.main_image:
        set_protected_image_uploader(product, "main_image", profile.user)
    return JsonResponse({
        "success": True,
        "message": (
            "Image uploaded. Arolana will review this image because it matches another vendor upload."
            if upload_policy.get("pending_review")
            else "Image uploaded successfully."
        ),
        "duplicate_warning": duplicate_warning or upload_policy,
        "image": {
            "id": product_image.id,
            "url": _absolute_media_url(request, product_image.image, "product_gallery"),
        },
        "product": _product_payload(product),
    })


@csrf_exempt
@require_POST
def vendor_product_media_api(request, product_id):
    try:
        _, profile = _require_vendor_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    product = Product.objects.filter(id=product_id, vendor=profile.user).first()
    if not product:
        return _error("Product not found.", status=404)
    upload = request.FILES.get("manual_pdf") or request.FILES.get("file") or request.FILES.get("video")
    media_type = _clean_text(request.POST.get("media_type"))
    if not upload:
        return _error("Media file is required.")
    apply_vendor_subscription_benefits(profile, user_subscription_tier(profile.user))
    profile.refresh_from_db()
    lower_name = upload.name.lower()
    if media_type == "local_video" or lower_name.endswith((".mp4", ".webm", ".mov")):
        if not profile.can_upload_video:
            return _subscription_limit_error()
        if upload.size > 5 * 1024 * 1024:
            return _error("Local product video must not be more than 5MB.")
        product.local_video = upload
        product.video_type = "local"
    elif media_type == "certificate":
        if not profile.can_upload_certificates:
            return _subscription_limit_error()
        certs = product.certifications if isinstance(product.certifications, list) else []
        certs.append({"label": _clean_text(request.POST.get("title") or upload.name), "file_name": upload.name})
        product.certifications = certs
    else:
        if not profile.can_upload_pdf:
            return _subscription_limit_error()
        product.manual_pdf = upload
    product.approval_status = "pending"
    product.is_active = False
    product.resubmitted_at = timezone.now()
    product.save()
    return JsonResponse({"success": True, "product": _product_payload(product), "message": "Media uploaded and product sent for admin review."})


@csrf_exempt
@require_POST
def vendor_product_variants_api(request, product_id):
    data = request.POST if request.POST else _json_body(request)
    try:
        _, profile = _require_vendor_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    product = Product.objects.filter(id=product_id, vendor=profile.user).first()
    if not product:
        return _error("Product not found.", status=404)
    variant_type = _clean_text(data.get("variant_type") or "other")
    if variant_type not in dict(ProductVariant.VARIANT_TYPES):
        variant_type = "other"
    name = _clean_text(data.get("name") or variant_type.title())
    value = _clean_text(data.get("value"))
    if not value:
        return _error("Variant value is required.")
    apply_vendor_subscription_benefits(profile, user_subscription_tier(profile.user))
    profile.refresh_from_db()
    variant_count = product.variants.filter(is_active=True).exclude(name=name, value=value).count()
    if profile.variant_limit != -1 and variant_count >= profile.variant_limit:
        return _subscription_limit_error()
    variant, _created = ProductVariant.objects.update_or_create(
        product=product,
        name=name,
        value=value,
        defaults={
            "variant_type": variant_type,
            "sku": _clean_text(data.get("sku")),
            "price_adjustment": _money(data.get("price_adjustment")),
            "stock_quantity": _int_value(data.get("stock_quantity")),
            "color_code": _clean_text(data.get("color_code")),
            "is_active": True,
        },
    )
    duplicate_warnings = []
    main_image = request.FILES.get("image")
    upload_files = ([main_image] if main_image else []) + list(request.FILES.getlist("images"))
    upload_policies = [
        inspect_vendor_image_upload(image_file, profile.user)
        for image_file in upload_files
    ]
    blocked_policy = next(
        (item for item in upload_policies if not item.get("allowed", True)),
        None,
    )
    if blocked_policy:
        return _vendor_upload_policy_error(blocked_policy)
    if main_image:
        variant.image = main_image
        variant.save(update_fields=["image", "updated_at"])
        set_protected_image_uploader(variant, "image", profile.user)
        warning = duplicate_warning_payload(variant, "image")
        if warning:
            duplicate_warnings.append(warning)
    variant_gallery_limit = 10 if profile.image_limit == -1 else min(10, max(0, profile.image_limit))
    gallery_images = request.FILES.getlist("images")[:variant_gallery_limit]
    for index, image_file in enumerate(gallery_images):
        variant_image = ProductVariantImage.objects.create(
            variant=variant,
            image=image_file,
            alt_text=f"{product.name} {name} {value}",
            order=index,
            is_main=index == 0 and not main_image,
        )
        set_protected_image_uploader(variant_image, "image", profile.user)
        warning = duplicate_warning_payload(variant_image, "image")
        if warning:
            duplicate_warnings.append(warning)
    product.approval_status = "pending"
    product.is_active = False
    product.resubmitted_at = timezone.now()
    product.save(update_fields=["approval_status", "is_active", "resubmitted_at", "updated_at"])
    return JsonResponse({
        "success": True,
        "variant_id": variant.id,
        "product": _product_payload(product),
        "duplicate_warnings": duplicate_warnings,
        "message": (
            "Variant saved. One or more images require Arolana duplicate review."
            if any(item.get("pending_review") for item in upload_policies)
            or any(item.get("needs_review") for item in duplicate_warnings)
            else "Variant saved and product sent for admin review."
        ),
    })


@require_GET
def vendor_dashboard_api(request):
    try:
        _, profile = _require_vendor_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    today = timezone.localdate()
    vendor_orders = _vendor_orders_for_user(profile.user)
    vendor_items = _vendor_orders_for_user(profile.user)
    revenue = vendor_items.aggregate(total=Sum("items__subtotal"))["total"] or Decimal("0.00")
    today_sales = vendor_items.filter(created_at__date=today).aggregate(total=Sum("items__subtotal"))["total"] or Decimal("0.00")
    products = Product.objects.filter(vendor=profile.user)
    vendor_notifications_qs = Notification.objects.filter(user=profile.user, is_archived=False)
    notifications_unread = vendor_notifications_qs.filter(is_read=False).count()
    notifications_total = vendor_notifications_qs.count()
    pickup_report_count = DeliveryRequest.objects.filter(
        Q(order__items__product__vendor=profile.user) | Q(order__items__variant__product__vendor=profile.user),
        status__in=[
            DeliveryRequest.STATUS_PICKED_UP,
            DeliveryRequest.STATUS_IN_TRANSIT,
            DeliveryRequest.STATUS_ARRIVED_CUSTOMER,
            DeliveryRequest.STATUS_DELIVERED,
        ],
    ).distinct().count()
    latest_notifications = Notification.objects.filter(user=profile.user, is_archived=False).order_by("-created_at")[:3]
    latest_messages = SmartChatConversation.objects.filter(user=profile.user).order_by("-updated_at", "-created_at")[:3]
    wallet = _vendor_wallet(profile)
    today_sales_display = _format_vendor_money(profile, today_sales)
    revenue_display = _format_vendor_money(profile, revenue)
    wallet_display = _format_vendor_money(profile, wallet.available_balance if wallet else 0)
    return JsonResponse({
        "success": True,
        "vendor": _vendor_payload(profile, request),
        "stats": {
            "today_sales": str(today_sales),
            "today_sales_display": today_sales_display["display"],
            "total_revenue": str(revenue),
            "total_revenue_display": revenue_display["display"],
            "pending_orders": vendor_orders.filter(status__in=["pending", "processing"]).count(),
            "completed_orders": vendor_orders.filter(status="delivered").count(),
            "active_products": products.filter(is_active=True, approval_status="approved").count(),
            "pending_products": products.filter(approval_status="pending").count(),
            "rejected_products": products.filter(approval_status__in=["rejected", "requires_changes"]).count(),
            "low_stock_products": products.filter(stock_quantity__lte=5, stock_quantity__gt=0).count(),
            "total_customers": vendor_orders.values("user").distinct().count(),
            "followers": profile.followers_count,
            "unread_messages": notifications_unread,
            "unread_notifications": notifications_unread,
            "notification_count": notifications_total,
            "pickup_reports": pickup_report_count,
            "handoff_reports": pickup_report_count,
            "wallet_balance": str(wallet.available_balance),
            "wallet_balance_display": wallet_display["display"],
            "pending_wallet_balance": str(wallet.pending_balance),
            "display_currency": getattr(profile, "preferred_currency", "NGN") or "NGN",
            "product_views": products.aggregate(total=Sum("views_count"))["total"] or 0,
            "has_bank_account": profile.bank_accounts.exists(),
        },
        "latest_notifications": [
            {
                "id": note.id,
                "title": note.title,
                "message": note.message,
                "type": note.notification_type,
                "is_read": note.is_read,
                "created_at": note.created_at.isoformat() if note.created_at else "",
            }
            for note in latest_notifications
        ],
        "latest_messages": [
            {
                "id": item.id,
                "title": item.title or item.customer_display or "Conversation",
                "last_message": (item.messages.order_by("-created_at").first().message if item.messages.exists() else ""),
                "unread_count": item.unread_count_for_vendor if hasattr(item, "unread_count_for_vendor") else 0,
            }
            for item in latest_messages
        ],
        "top_products": [
            {"id": row["items__product"], "name": row["items__product__name"], "sales": row["qty"] or 0, "revenue": str(row["revenue"] or 0)}
            for row in Order.objects.filter(items__product__vendor=profile.user)
            .values("items__product", "items__product__name")
            .annotate(qty=Sum("items__quantity"), revenue=Sum("items__subtotal"))
            .order_by("-qty")[:8]
        ],
    })


@require_GET
def vendor_notifications_api(request):
    try:
        _, profile = _require_vendor_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    notes = Notification.objects.filter(user=profile.user, is_archived=False)[:100]
    return JsonResponse({
        "success": True,
        "notifications": [
            {
                "id": note.id,
                "type": note.notification_type,
                "title": note.title,
                "message": note.message,
                "is_read": note.is_read,
                "created_at": note.created_at.isoformat() if note.created_at else "",
                "metadata": note.metadata,
            }
            for note in notes
        ],
        "unread_count": Notification.objects.filter(user=profile.user, is_read=False, is_archived=False).count(),
    })


@csrf_exempt
@require_POST
def vendor_notification_read_api(request, notification_id):
    try:
        _, profile = _require_vendor_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    note = Notification.objects.filter(id=notification_id, user=profile.user).first()
    if not note:
        return _error("Notification not found.", status=404)
    note.mark_as_read()
    return JsonResponse({"success": True})


@csrf_exempt
@require_POST
def vendor_notifications_read_all_api(request):
    try:
        _, profile = _require_vendor_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    Notification.objects.filter(user=profile.user, is_read=False).update(is_read=True, read_at=timezone.now())
    return JsonResponse({"success": True})


def _notification_user_for_role(request, role):
    if role == "vendor":
        _, profile = _require_vendor_session(request)
        return profile.user
    if role == "admin":
        return _require_admin_session(request).user
    if role == "rider":
        return _require_rider_session(request).rider.user
    raise PermissionError("Invalid notification role.")


@require_GET
def staff_notifications_api(request, role):
    try:
        user = _notification_user_for_role(request, role)
    except PermissionError as error:
        return _error(error, status=403)
    notes = Notification.objects.filter(user=user, is_archived=False)[:100]
    return JsonResponse({
        "success": True,
        "notifications": [
            {
                "id": note.id,
                "type": note.notification_type,
                "title": note.title,
                "message": note.message,
                "is_read": note.is_read,
                "created_at": note.created_at.isoformat() if note.created_at else "",
                "metadata": note.metadata,
            }
            for note in notes
        ],
        "unread_count": Notification.objects.filter(user=user, is_read=False, is_archived=False).count(),
    })


@csrf_exempt
@require_POST
def staff_notification_read_api(request, role, notification_id):
    try:
        user = _notification_user_for_role(request, role)
    except PermissionError as error:
        return _error(error, status=403)
    note = Notification.objects.filter(id=notification_id, user=user).first()
    if not note:
        return _error("Notification not found.", status=404)
    note.mark_as_read()
    return JsonResponse({"success": True})


@csrf_exempt
@require_POST
def staff_notifications_read_all_api(request, role):
    try:
        user = _notification_user_for_role(request, role)
    except PermissionError as error:
        return _error(error, status=403)
    Notification.objects.filter(user=user, is_read=False, is_archived=False).update(is_read=True, read_at=timezone.now())
    return JsonResponse({"success": True})


@csrf_exempt
@require_POST
def staff_notification_delete_api(request, role, notification_id):
    try:
        user = _notification_user_for_role(request, role)
    except PermissionError as error:
        return _error(error, status=403)
    note = Notification.objects.filter(id=notification_id, user=user).first()
    if not note:
        return _error("Notification not found.", status=404)
    note.archive()
    return JsonResponse({"success": True})


@csrf_exempt
@require_POST
def staff_notifications_delete_selected_api(request, role):
    data = _json_body(request)
    try:
        user = _notification_user_for_role(request, role)
    except PermissionError as error:
        return _error(error, status=403)

    raw_ids = data.get("ids") or data.get("notification_ids") or []
    try:
        ids = [int(item) for item in raw_ids][:100]
    except Exception:
        ids = []
    if not ids:
        return _error("Select at least one notification to delete.")

    notes = Notification.objects.filter(id__in=ids, user=user, is_archived=False)
    count = notes.count()
    for note in notes:
        note.archive()
    return JsonResponse({"success": True, "deleted_count": count})


@require_GET
def vendor_messages_api(request):
    try:
        session, profile = _require_vendor_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    notes = Notification.objects.filter(user=profile.user, notification_type="message", is_archived=False)[:50]
    conversations = [_smartchat_payload(item, "vendor") for item in _staff_conversations_for_session(session)]
    return JsonResponse({"success": True, "conversations": conversations, "messages": [
        {"id": note.id, "title": note.title, "message": note.message, "is_read": note.is_read, "created_at": note.created_at.isoformat() if note.created_at else ""}
        for note in notes
    ]})


@csrf_exempt
@require_POST
def vendor_message_send_api(request):
    data = _json_body(request)
    try:
        session, profile = _require_vendor_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    message = _clean_text(data.get("message"))
    if not message:
        return _error("Message is required.")
    subject = _clean_text(data.get("subject")) or "Vendor support"
    conversation = _get_or_create_staff_conversation(
        profile.user,
        subject,
        {"staff_role": "vendor", "vendor_profile_id": profile.id},
    )
    chat_message = SmartChatMessage.objects.create(
        conversation=conversation,
        sender_type=SmartChatMessage.SENDER_USER,
        user=session.user,
        message=message,
        metadata={"recipient_type": data.get("recipient_type") or "admin", "staff_role": "vendor"},
    )
    conversation.mark_admin_requested()
    admins = get_user_model().objects.filter(Q(is_staff=True) | Q(is_superuser=True), is_active=True)[:10]
    for admin_user in admins:
        _notify(admin_user, f"Vendor message from {profile.store_name}", message, "message", {"vendor_id": profile.id, "smartchat_conversation_id": conversation.id, "smartchat_message_id": chat_message.id})
    _notify(profile.user, "Message sent to admin", "Your message has been sent to Arolana admin.", "message", {"smartchat_conversation_id": conversation.id})
    return JsonResponse({"success": True, "message": "Message sent to admin.", "conversation": _smartchat_payload(conversation, "vendor")})


@require_GET
def vendor_rfqs_api(request):
    try:
        _, profile = _require_vendor_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    apply_vendor_subscription_benefits(profile, user_subscription_tier(profile.user))
    profile.refresh_from_db()
    if not profile.can_access_rfq:
        return _subscription_limit_error()
    rfqs = profile.rfqs.select_related("product", "customer")[:100]
    return JsonResponse({"success": True, "rfqs": [
        {
            "id": rfq.id,
            "product": rfq.product.name if rfq.product else "",
            "customer": rfq.customer.get_full_name() or rfq.customer.email if rfq.customer else "",
            "quantity": rfq.quantity,
            "budget": str(rfq.budget or ""),
            "country": rfq.country,
            "delivery_location": rfq.delivery_location,
            "message": rfq.message,
            "status": rfq.status,
            "quote_price": str(rfq.quote_price or ""),
            "quote_lead_time_days": rfq.quote_lead_time_days,
        }
        for rfq in rfqs
    ]})


@csrf_exempt
@require_POST
def vendor_rfq_quote_api(request, rfq_id):
    data = _json_body(request)
    try:
        _, profile = _require_vendor_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    apply_vendor_subscription_benefits(profile, user_subscription_tier(profile.user))
    profile.refresh_from_db()
    if not profile.can_access_rfq:
        return _subscription_limit_error()
    rfq = profile.rfqs.filter(id=rfq_id).first()
    if not rfq:
        return _error("RFQ not found.", status=404)
    rfq.quote_price = _money(data.get("quote_price"))
    rfq.quote_lead_time_days = int(data.get("quote_lead_time_days") or 0) or None
    rfq.vendor_note = _clean_text(data.get("vendor_note"))
    rfq.status = "quoted"
    rfq.quoted_at = timezone.now()
    rfq.save()
    if rfq.customer_id:
        _notify(rfq.customer, "Your quotation is ready", f"{profile.store_name} has sent a quote for your RFQ.", "vendor", {"rfq_id": rfq.id})
    return JsonResponse({"success": True, "message": "Quote sent."})


@require_GET
def vendor_subscription_plans_api(request):
    try:
        _, profile = _require_vendor_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    desired_order = ["free", "basic", "plus", "pro", "special", "enterprise"]
    existing = {}
    for plan in SubscriptionPlan.objects.filter(is_active=True).order_by("order", "price_monthly"):
        existing.setdefault(plan.tier_key, plan)
    plans = [existing[tier] for tier in desired_order if tier in existing]
    current_tier = user_subscription_tier(profile.user)
    def localized_features(plan):
        value = translated_field(plan, "feature_bullets", request=request, default=plan.feature_bullets)
        if isinstance(value, list):
            return value
        try:
            parsed = json.loads(value or "[]")
            return parsed if isinstance(parsed, list) else plan.get_features_list()
        except (TypeError, ValueError):
            return plan.get_features_list()

    return JsonResponse({"success": True, "plans": [
        {
            "id": plan.id,
            "name": plan.tier_key,
            "tier": plan.tier_key,
            "display_name": translated_field(
                plan,
                "display_name",
                request=request,
                default=translated_key(
                    f"subscription.plan.{plan.tier_key}",
                    subscription_label(plan.tier_key),
                    request=request,
                ),
            ),
            "description": translated_field(plan, "description", request=request),
            "features": localized_features(plan),
            "price_monthly": str(plan.price_monthly),
            "price_yearly": str(plan.price_yearly),
            "limits": get_tier_limits(plan.tier_key),
            "is_current": current_tier == plan.tier_key,
        }
        for plan in plans
    ], "benefits_image_url": request.build_absolute_uri("/static/images/arolana-vendor-subscription-benefits.png")})


@require_GET
def vendor_subscription_gateways_api(request):
    try:
        _require_vendor_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    return JsonResponse({"success": True, "gateways": get_gateway_options(include_inactive=True)})


@require_GET
def vendor_subscription_status_api(request):
    try:
        _, profile = _require_vendor_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    return JsonResponse({
        "success": True,
        "vendor": _subscription_status_payload(profile),
    })


def _subscription_message(vendor_name, plan_name, reference):
    return (
        f"Dear {vendor_name},\n\n"
        "Arolana appreciates you!\n\n"
        f"Your {plan_name} subscription has been activated successfully.\n\n"
        "Reference No:\n"
        f"{reference}\n\n"
        "Your invoice/receipt is now available for download.\n\n"
        "Offer ends Apr 30.\n\n"
        "Call:\n"
        "+2349033713922\n\n"
        "WhatsApp:\n"
        "+2349132924620\n\n"
        "Thank you for choosing Arolana.\n\n"
        "Arolana Team"
    )


def _send_subscription_email(profile, plan, payment):
    email = profile.user.email or profile.support_email
    if not email:
        return
    receipt_url = ""
    try:
        receipt_url = f"{getattr(settings, 'SITE_URL', '').rstrip()}/api/staff/vendor/subscription/invoices/{payment.id}/pdf/"
    except Exception:
        receipt_url = ""
    message = _subscription_message(profile.store_name, subscription_label(plan.tier_key), payment.reference)
    if receipt_url:
        message = f"{message}\n\nReceipt link:\n{receipt_url}"
    try:
        send_mail(
            "Arolana Subscription Activated Successfully",
            message,
            getattr(settings, "DEFAULT_FROM_EMAIL", "support@arolana.com"),
            [email],
            fail_silently=True,
        )
    except Exception:
        return


def _activate_vendor_subscription(profile, plan, reference="", payment=None):
    VendorSubscription.objects.filter(vendor=profile.user, is_active=True).update(is_active=False, auto_renew=False)
    started_at = timezone.now()
    expiry = timezone.now() + timezone.timedelta(days=30)
    profile.subscription_tier = plan.tier_key
    profile.subscription_active = True
    profile.subscription_started_at = started_at
    profile.subscription_expires_at = expiry
    profile.priority_score = get_tier_limits(plan.tier_key)["priority_score"]
    profile.subscription_expiry = expiry
    profile.save(update_fields=[
        "subscription_tier",
        "subscription_active",
        "subscription_started_at",
        "subscription_expires_at",
        "priority_score",
        "subscription_expiry",
        "updated_at",
    ])
    apply_vendor_subscription_benefits(profile, plan)
    profile.refresh_from_db()
    VendorSubscription.objects.create(
        vendor=profile.user,
        plan=plan,
        start_date=started_at,
        end_date=expiry,
        is_active=True,
        payment_method="paid" if plan.price_monthly > 0 else "free",
        transaction_id=reference,
    )
    enforce_vendor_product_visibility(profile)
    plan_name = subscription_label(plan.tier_key)
    notification_message = _subscription_message(profile.store_name, plan_name, reference)
    _notify(
        profile.user,
        "Subscription activated",
        notification_message,
        "payment",
        {
            "plan_id": plan.id,
            "tier": plan.tier_key,
            "reference": reference,
            "subscription_started_at": started_at.isoformat(),
            "subscription_expires_at": expiry.isoformat(),
        },
    )
    if payment:
        _send_subscription_email(profile, plan, payment)
    return expiry


def _subscription_receipt(profile, plan, gateway=PaymentMethod.PAYSTACK, status=PaymentStatus.PENDING):
    payment = PaymentTransaction.objects.create(
        user=profile.user,
        order_id=f"vendor_subscription:{profile.id}:{plan.id}",
        gateway=gateway,
        status=status,
        amount=plan.price_monthly,
        currency="NGN",
        customer_email=profile.user.email or profile.support_email,
        customer_name=profile.store_name,
        customer_phone=profile.support_phone or profile.pickup_phone,
        checkout_data={
            "purpose": "vendor_subscription",
            "plan_id": plan.id,
            "tier": plan.tier_key,
            "plan_name": plan.display_name,
            "vendor_profile_id": profile.id,
        },
    )
    return payment


def _activate_free_vendor_plan(profile, plan):
    payment = _subscription_receipt(profile, plan, gateway=PaymentMethod.PAYSTACK, status=PaymentStatus.PENDING)
    payment.mark_success("free-plan", {"message": "Free vendor plan activated."})
    _activate_vendor_subscription(profile, plan, reference=payment.reference, payment=payment)
    return payment


@csrf_exempt
@require_POST
def vendor_subscription_choose_api(request):
    data = _json_body(request)
    try:
        _, profile = _require_vendor_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    plan = SubscriptionPlan.objects.filter(id=data.get("plan_id"), is_active=True).first()
    if not plan:
        return _error("Subscription plan not found.", status=404)
    if plan.price_monthly > 0:
        return _error("Paid plans must be activated through checkout.", status=402)
    payment = _activate_free_vendor_plan(profile, plan)
    return JsonResponse({
        "success": True,
        "vendor": _vendor_payload(profile),
        "invoice_id": payment.id,
        "reference": payment.reference,
        "message": "Free plan selected.",
    })


@csrf_exempt
@require_POST
def vendor_subscription_checkout_api(request):
    data = _json_body(request)
    plan_id = data.get("plan_id")
    if not plan_id and str(request.path).rstrip("/").split("/")[-1].isdigit():
        plan_id = str(request.path).rstrip("/").split("/")[-1]
    try:
        _, profile = _require_vendor_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    plan = SubscriptionPlan.objects.filter(id=plan_id, is_active=True).first()
    if not plan:
        return _error("Subscription plan not found.", status=404)
    if plan.price_monthly <= 0:
        payment = _activate_free_vendor_plan(profile, plan)
        return JsonResponse({
            "success": True,
            "vendor": _vendor_payload(profile),
            "invoice_id": payment.id,
            "reference": payment.reference,
            "message": "Free plan selected.",
        })
    gateway = _clean_text(data.get("payment_gateway") or data.get("gateway") or data.get("payment_method") or PaymentMethod.PAYSTACK).lower()
    if gateway not in PaymentMethod.values:
        return _error("Choose a supported Arolana payment gateway.", status=400)
    is_available, disabled_reason = gateway_is_available(gateway)
    if not is_available:
        return _error(disabled_reason or "This payment gateway is not available yet.", status=400)

    payment = _subscription_receipt(profile, plan, gateway=gateway, status=PaymentStatus.PENDING)
    if data.get("currency"):
        payment.currency = data.get("currency")
        payment.save(update_fields=["currency", "updated_at"])
    if gateway == PaymentMethod.MANUAL_CRYPTO:
        payment.status = PaymentStatus.PENDING
        payment.save(update_fields=["status", "updated_at"])
        return JsonResponse({
            "success": True,
            "manual_payment": True,
            "reference": payment.reference,
            "payment_reference": payment.reference,
            "invoice_id": payment.id,
            "message": "Manual crypto payment created. Admin will activate the plan after confirming payment.",
        })
    try:
        checkout_url = _hosted_subscription_checkout_url(request, payment)
    except Exception as error:
        return _error(f"Unable to start payment checkout: {error}", status=502)
    if not checkout_url:
        payment.mark_failed({"error": "Gateway did not return checkout URL."})
        return _error("Payment gateway did not return a checkout link. Please try another gateway.", status=502)
    return JsonResponse({
        "success": True,
        "reference": payment.reference,
        "payment_reference": payment.reference,
        "invoice_id": payment.id,
        "gateway": payment.gateway,
        "checkout_url": checkout_url,
        "authorization_url": checkout_url,
        "payment_url": checkout_url,
        "url": checkout_url,
        "message": "Payment initialized.",
    })


@csrf_exempt
@require_POST
def vendor_subscription_pay_api(request, plan_id):
    data = _json_body(request)
    data["plan_id"] = plan_id
    request._body = json.dumps(data).encode("utf-8")
    return vendor_subscription_checkout_api(request)


@csrf_exempt
@require_POST
def vendor_subscription_verify_api(request):
    data = _json_body(request)
    reference = _clean_text(data.get("reference") or data.get("payment_reference"))
    invoice_id = data.get("invoice_id")
    try:
        _, profile = _require_vendor_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    if not reference:
        return _error("Payment reference is required.")
    payment_query = PaymentTransaction.objects.filter(user=profile.user)
    if invoice_id:
        payment_query = payment_query.filter(Q(id=invoice_id) | Q(reference=reference) | Q(gateway_reference=reference))
    else:
        payment_query = payment_query.filter(Q(reference=reference) | Q(gateway_reference=reference))
    payment = payment_query.first()
    if not payment:
        return _error("Payment transaction not found.", status=404)
    if payment.status != PaymentStatus.SUCCESS:
        confirmed, message = _verify_subscription_payment_now(payment)
        if not confirmed:
            hard_failure = "failed" in message.lower() or "cancelled" in message.lower() or "abandoned" in message.lower()
            if hard_failure:
                _notify(
                    profile.user,
                    "Subscription payment failed",
                    "Your subscription payment could not be verified. Please try again or contact support.",
                    "payment",
                    {"reference": payment.reference, "invoice_id": payment.id},
                )
                return _error(message, status=402)
            if payment.status in [PaymentStatus.FAILED, PaymentStatus.CANCELLED]:
                payment.status = PaymentStatus.PENDING
                payment.save(update_fields=["status", "updated_at"])
            return JsonResponse({
                "success": True,
                "pending": True,
                "vendor": _vendor_payload(profile),
                "invoice": _subscription_invoice_payload(request, payment),
                "message": f"{message} Please wait a moment and tap Verify Payment again.",
            }, status=202)
    if payment.status != PaymentStatus.SUCCESS:
        return _error("Payment has not been confirmed yet.", status=402)
    checkout_data = payment.checkout_data or {}
    plan = SubscriptionPlan.objects.filter(id=checkout_data.get("plan_id"), is_active=True).first()
    if not plan:
        return _error("Subscription plan for this payment was not found.", status=404)
    _activate_vendor_subscription(profile, plan, reference=payment.reference, payment=payment)
    return JsonResponse({
        "success": True,
        "vendor": _vendor_payload(profile),
        "invoice": _subscription_invoice_payload(request, payment),
        "message": "Subscription payment verified and plan activated.",
    })


def _subscription_invoice_payload(request, payment):
    checkout_data = payment.checkout_data or {}
    token = _request_staff_token(request)
    pdf_path = f"/api/staff/vendor/subscription/invoices/{payment.id}/pdf/"
    if token:
        pdf_path = f"{pdf_path}?token={token}"
    return {
        "id": payment.id,
        "invoice_number": payment.reference,
        "reference": payment.reference,
        "payment_reference": payment.gateway_reference or payment.reference,
        "plan_name": checkout_data.get("plan_name") or checkout_data.get("tier", "Subscription"),
        "tier": checkout_data.get("tier", "subscription"),
        "amount": str(payment.amount),
        "currency": payment.currency,
        "payment_method": payment.gateway,
        "status": payment.status,
        "created_at": payment.created_at.isoformat() if payment.created_at else "",
        "paid_at": payment.paid_at.isoformat() if payment.paid_at else "",
        "receipt_url": request.build_absolute_uri(pdf_path),
        "pdf_url": request.build_absolute_uri(pdf_path),
    }


@require_GET
def vendor_subscription_invoices_api(request):
    try:
        _, profile = _require_vendor_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    payments = PaymentTransaction.objects.filter(
        user=profile.user,
        checkout_data__purpose="vendor_subscription",
    ).order_by("-created_at")[:50]
    return JsonResponse({"success": True, "invoices": [
        _subscription_invoice_payload(request, payment)
        for payment in payments
    ]})


@require_GET
def vendor_subscription_invoice_pdf_api(request, invoice_id):
    profile = None
    try:
        _, profile = _require_vendor_session(request)
    except PermissionError:
        user = getattr(request, "user", None)
        if user and getattr(user, "is_authenticated", False):
            profile = _vendor_profile_for_user(user)
    if not profile:
        return _error("Vendor access required.", status=403)
    payment = PaymentTransaction.objects.filter(
        id=invoice_id,
        user=profile.user,
        checkout_data__purpose="vendor_subscription",
    ).first()
    if not payment:
        return _error("Subscription invoice not found.", status=404)
    if not SimpleDocTemplate:
        return _error("Receipt PDF is not ready yet. Ask Codex to add the PDF endpoint.", status=503)

    checkout_data = payment.checkout_data or {}
    plan_name = checkout_data.get("plan_name") or checkout_data.get("tier", "Subscription")
    active_subscription = VendorSubscription.objects.filter(
        vendor=profile.user,
        transaction_id=payment.reference,
    ).select_related("plan").first()
    started_at = getattr(active_subscription, "start_date", None) or profile.subscription_started_at
    expires_at = getattr(active_subscription, "end_date", None) or profile.subscription_expires_at or profile.subscription_expiry

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    story = [
        Paragraph("<b>Arolana</b>", styles["Title"]),
        Paragraph("Vendor Subscription Invoice / Receipt", styles["Heading2"]),
        Spacer(1, 12),
    ]
    rows = [
        ["Invoice number", payment.reference],
        ["Reference number", payment.gateway_reference or payment.reference],
        ["Vendor name", profile.user.get_full_name() or profile.user.username],
        ["Store name", profile.store_name],
        ["Plan name", plan_name],
        ["Amount paid", f"{payment.currency} {payment.amount}"],
        ["Payment method", payment.get_gateway_display() if hasattr(payment, "get_gateway_display") else payment.gateway],
        ["Payment status", payment.status.title()],
        ["Transaction date", timezone.localtime(payment.paid_at or payment.created_at).strftime("%d %b %Y %H:%M")],
        ["Plan start date", timezone.localtime(started_at).strftime("%d %b %Y") if started_at else "-"],
        ["Plan expiry date", timezone.localtime(expires_at).strftime("%d %b %Y") if expires_at else "-"],
        ["Website", "https://arolana.com"],
        ["Call", "+2349033713922"],
        ["WhatsApp", "+2349132924620"],
        ["Email", "support@arolana.com"],
    ]
    table = Table(rows, colWidths=[150, 330])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F8FAFC")),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#0F172A")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("PADDING", (0, 0), (-1, -1), 8),
    ]))
    story.extend([table, Spacer(1, 18), Paragraph("Thank you for choosing Arolana.", styles["Heading3"])])
    doc.build(story)
    pdf = buffer.getvalue()
    buffer.close()
    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="arolana-subscription-{payment.reference}.pdf"'
    return response


@csrf_exempt
@require_POST
def vendor_order_ready_api(request, order_id):
    data = _json_body(request)
    try:
        session, profile = _require_vendor_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    order = Order.objects.filter(id=order_id).filter(_vendor_order_q(profile.user)).distinct().first()
    if not order:
        return _error("Order not found for this vendor.", status=404)
    _mark_order_ready_for_pickup(
        session,
        profile,
        order,
        _clean_text(data.get("note")) or "Vendor marked order ready for pickup.",
    )
    return JsonResponse({"success": True, "order": _order_payload(order), "message": "Order marked ready for pickup."})


@require_GET
def admin_orders_api(request):
    try:
        session = _auth_staff(request)
    except PermissionError as error:
        return _error(error, status=403)
    if session.role != "admin":
        return _error("Admin access required.", status=403)

    orders = Order.objects.prefetch_related("items__product", "live_delivery_requests__rider__user").order_by("-created_at")[:120]
    return JsonResponse({"success": True, "orders": [_order_payload(order) for order in orders]})


@require_GET
def vendor_orders_api(request):
    try:
        session = _auth_staff(request)
    except PermissionError as error:
        return _error(error, status=403)
    if session.role not in ["vendor", "admin"]:
        return _error("Vendor access required.", status=403)

    orders = Order.objects.prefetch_related("items__product", "live_delivery_requests__rider__user")
    if session.role == "vendor" and session.user_id:
        orders = orders.filter(_vendor_order_q(session.user)).distinct()
    orders = orders.order_by("-created_at")[:120]
    return JsonResponse({"success": True, "orders": [_order_payload(order) for order in orders]})


@require_GET
def rider_orders_api(request):
    try:
        session = _auth_staff(request)
    except PermissionError as error:
        return _error(error, status=403)
    if session.role != "rider":
        return _error("Rider access required.", status=403)

    base_deliveries = (
        DeliveryRequest.objects.select_related("order", "rider", "rider__user")
        .prefetch_related("order__items__product", "order__items__variant__product", "status_history__actor")
        .filter(rider=session.rider)
    )
    available_deliveries = DeliveryRequest.objects.none()
    can_see_available_requests = bool(
        session.rider
        and session.rider.kyc_status == session.rider.KYC_APPROVED
        and session.rider.is_online
        and not session.rider.is_suspended
    )
    if can_see_available_requests:
        available_deliveries = (
            DeliveryRequest.objects.select_related("order", "rider", "rider__user")
            .prefetch_related("order__items__product", "order__items__variant__product", "status_history__actor")
            .filter(
                rider__isnull=True,
                is_ready_for_rider=True,
                status__in=[DeliveryRequest.STATUS_PENDING, DeliveryRequest.STATUS_ASSIGNED],
            )
            .order_by("-created_at")[:60]
        )
    closed_statuses = [
        DeliveryRequest.STATUS_DELIVERED,
        DeliveryRequest.STATUS_CANCELLED,
        DeliveryRequest.STATUS_FAILED,
        DeliveryRequest.STATUS_RETURNED,
    ]
    active_deliveries = (
        base_deliveries
        .exclude(status__in=[
            DeliveryRequest.STATUS_DELIVERED,
            DeliveryRequest.STATUS_CANCELLED,
            DeliveryRequest.STATUS_FAILED,
            DeliveryRequest.STATUS_RETURNED,
        ])
        .order_by("-created_at")[:120]
    )
    recent_history = base_deliveries.filter(status__in=closed_statuses).order_by("-updated_at", "-created_at")[:40]
    available_payloads = []
    for delivery in available_deliveries:
        payload = _delivery_payload(delivery)
        payload.update({
            "status": DeliveryRequest.STATUS_ASSIGNED,
            "delivery_status": DeliveryRequest.STATUS_ASSIGNED,
            "assignment_mode": "available_request",
            "rider_name": "",
            "rider_phone": "",
        })
        available_payloads.append(payload)
    active_payloads = [_delivery_payload(delivery) for delivery in active_deliveries]
    history_payloads = [_delivery_payload(delivery) for delivery in recent_history]
    current_payloads = available_payloads + active_payloads
    return JsonResponse({
        "success": True,
        "deliveries": current_payloads,
        "orders": current_payloads,
        "available_requests": available_payloads,
        "history": history_payloads,
        "all_deliveries": current_payloads + history_payloads,
        "rider": _rider_payload(session.rider),
    })


@require_GET
def riders_api(request):
    try:
        session = _auth_staff(request)
    except PermissionError as error:
        return _error(error, status=403)
    if session.role != "admin":
        return _error("Admin access required.", status=403)

    riders = RiderProfile.objects.select_related("user", "vehicle", "zone").filter(is_active=True).order_by("user__first_name", "user__email")
    return JsonResponse({"success": True, "riders": [_rider_payload(rider) for rider in riders]})


@csrf_exempt
@require_POST
def admin_assign_rider_api(request):
    data = _json_body(request)
    try:
        session = _auth_staff(request)
    except PermissionError as error:
        return _error(error, status=403)
    if session.role != "admin":
        return _error("Admin access required.", status=403)

    order = Order.objects.filter(id=data.get("order_id")).first()
    rider = RiderProfile.objects.select_related("user").filter(id=data.get("rider_id"), is_active=True).first()
    if not order:
        return _error("Order not found.", status=404)
    if not rider:
        return _error("Rider not found.", status=404)

    delivery = _live_delivery(order) or create_live_delivery_for_order(order, defer_assignment=True)
    delivery.rider = rider
    delivery.is_ready_for_rider = True
    if rider.vehicle_id and not delivery.requested_vehicle_id:
        delivery.requested_vehicle = rider.vehicle
        delivery.save(update_fields=["rider", "requested_vehicle", "is_ready_for_rider", "updated_at"])
    else:
        delivery.save(update_fields=["rider", "is_ready_for_rider", "updated_at"])
    delivery.set_status(DeliveryRequest.STATUS_ASSIGNED, actor=session.user, note=_clean_text(data.get("admin_note")) or "Assigned from Arolana staff mobile.")
    _notify_delivery_assignment(delivery, admin_user=session.user)
    try:
        from order_robot.services import sync_from_live_delivery

        sync_from_live_delivery(delivery)
    except Exception:
        pass
    return JsonResponse({
        "success": True,
        "message": "Rider assigned successfully.",
        "delivery": {
            "id": delivery.id,
            "order_id": order.id,
            "rider_id": rider.id,
            "status": delivery.status,
        },
        "order": _order_payload(order),
    })


@csrf_exempt
@require_POST
def admin_assign_rider_path_api(request, order_id):
    data = _json_body(request)
    mutable_body = dict(data)
    mutable_body.setdefault("order_id", order_id)
    request._body = json.dumps(mutable_body).encode("utf-8")
    return admin_assign_rider_api(request)


@csrf_exempt
@require_POST
def update_delivery_status_api(request):
    data = _json_body(request)
    try:
        session = _auth_staff(request)
    except PermissionError as error:
        return _error(error, status=403)

    delivery = None
    if data.get("delivery_id"):
        delivery = DeliveryRequest.objects.select_related("order", "rider", "rider__user").filter(id=data.get("delivery_id")).first()
    order = delivery.order if delivery else Order.objects.filter(id=data.get("order_id")).first()
    if not order:
        return _error("Order not found.", status=404)

    delivery = delivery or _live_delivery(order) or create_live_delivery_for_order(order, defer_assignment=True)
    status = _clean_text(data.get("status"))

    if session.role == "rider":
        if delivery.rider_id and delivery.rider_id != session.rider_id:
            return _error("This delivery is not assigned to you.", status=403)
        if not delivery.rider_id:
            can_claim = (
                status == "accepted"
                and delivery.is_ready_for_rider
                and delivery.status in [DeliveryRequest.STATUS_PENDING, DeliveryRequest.STATUS_ASSIGNED]
                and session.rider
                and session.rider.kyc_status == session.rider.KYC_APPROVED
                and session.rider.is_online
                and not session.rider.is_suspended
            )
            if not can_claim:
                return _error("This delivery is not assigned to you.", status=403)
            delivery.rider = session.rider
            delivery.status = DeliveryRequest.STATUS_ASSIGNED
            delivery.save(update_fields=["rider", "status", "updated_at"])
            if session.rider.is_available:
                session.rider.is_available = False
                session.rider.save(update_fields=["is_available", "updated_at"])
            _notify(
                session.rider.user,
                "Pickup accepted",
                f"You accepted order {safe_str(getattr(order, 'order_number', '')) or order.id}.",
                "delivery",
                {
                    "order_id": order.id,
                    "delivery_id": delivery.id,
                    "tracking_code": delivery.tracking_code,
                    "screen": "RiderDeliveries",
                },
            )
    if session.role == "vendor" and session.user_id:
        owns_item = order.items.filter(Q(product__vendor=session.user) | Q(variant__product__vendor=session.user)).exists()
        if not owns_item:
            return _error("This order is not assigned to your vendor account.", status=403)

    note = _clean_text(data.get("note"))
    vendor_ready_statuses = {"ready_for_pickup", "vendor_confirmed"}
    if status in {"decline", "declined"}:
        if session.role != "rider":
            return _error("Only the assigned rider can decline a delivery.", status=403)
        if delivery.rider_id != session.rider_id:
            return _error("This delivery is not assigned to you.", status=403)
        rider_name = _rider_name(session.rider) or "Assigned rider"
        delivery.rider = None
        delivery.is_ready_for_rider = True
        delivery.save(update_fields=["rider", "is_ready_for_rider", "updated_at"])
        delivery.set_status(
            DeliveryRequest.STATUS_PENDING,
            actor=session.rider.user,
            note=note or f"{rider_name} declined the delivery request. Order returned to dispatch.",
        )
        metadata = {
            "order_id": order.id,
            "delivery_id": delivery.id,
            "order_number": safe_str(getattr(order, "order_number", "")),
            "tracking_code": delivery.tracking_code,
            "delivery_status": "pending",
        }
        for admin_user in _admin_notification_users():
            _notify(
                admin_user,
                "Rider declined pickup",
                f"{rider_name} declined order {metadata['order_number'] or order.id}. Please assign another rider.",
                "delivery",
                metadata,
            )
        return JsonResponse({
            "success": True,
            "message": "Delivery declined. It has been returned to dispatch.",
            "order": _order_payload(order),
        })
    status_map = {
        "ready_for_pickup": DeliveryRequest.STATUS_PENDING,
        "vendor_confirmed": DeliveryRequest.STATUS_PENDING,
        "assigned": DeliveryRequest.STATUS_ASSIGNED,
        "accepted": DeliveryRequest.STATUS_ACCEPTED,
        "arrived_at_pickup": DeliveryRequest.STATUS_ARRIVED_PICKUP,
        "picked_up": DeliveryRequest.STATUS_PICKED_UP,
        "in_transit": DeliveryRequest.STATUS_IN_TRANSIT,
        "arrived_at_customer": DeliveryRequest.STATUS_ARRIVED_CUSTOMER,
        "delivered": DeliveryRequest.STATUS_DELIVERED,
        "failed": DeliveryRequest.STATUS_FAILED,
        "cancelled": DeliveryRequest.STATUS_CANCELLED,
        "returned": DeliveryRequest.STATUS_RETURNED,
    }
    if status not in status_map:
        return _error("Invalid delivery status.")
    if session.role == "vendor" and status not in vendor_ready_statuses | {"picked_up", "in_transit"}:
        return _error("Vendor can only confirm ready/pickup progress for assigned vendor orders.", status=403)

    if status in vendor_ready_statuses:
        profile = _vendor_profile_for_user(session.user)
        if not profile:
            return _error("Vendor profile not found.", status=403)
        _mark_order_ready_for_pickup(
            session,
            profile,
            order,
            note or "Vendor marked order ready for pickup.",
        )
        return JsonResponse({"success": True, "message": "Order marked ready for pickup.", "order": _order_payload(order)})

    actor = session.user or (session.rider.user if session.rider_id else None)
    delivery_status = status_map[status]
    terminal_statuses = {
        DeliveryRequest.STATUS_DELIVERED,
        DeliveryRequest.STATUS_FAILED,
        DeliveryRequest.STATUS_CANCELLED,
        DeliveryRequest.STATUS_RETURNED,
    }
    if delivery.status in terminal_statuses and delivery.status != delivery_status:
        return JsonResponse({
            "success": True,
            "message": f"Delivery is already {delivery.get_status_display().lower()}.",
            "order": _order_payload(order),
        })
    if delivery_status == DeliveryRequest.STATUS_PICKED_UP and not note:
        rider_name = _rider_name(delivery.rider) or "the assigned rider"
        note = f"Vendor handoff recorded. Product/package was given to {rider_name} for delivery."
    if delivery_status == DeliveryRequest.STATUS_FAILED:
        failed_reason = _clean_text(data.get("failed_reason") or data.get("reason") or note)
        if failed_reason:
            delivery.failed_reason = failed_reason
            delivery.save(update_fields=["failed_reason", "updated_at"])
    delivery.set_status(delivery_status, actor=actor, note=note)
    _notify_delivery_status_change(delivery, delivery_status, actor_user=actor)
    if delivery_status == DeliveryRequest.STATUS_DELIVERED and delivery.rider_id:
        _notify(
            delivery.rider.user,
            "Earnings credited",
            f"{delivery.rider_earning} has been credited for delivery {delivery.tracking_code}.",
            "delivery",
            {
                "order_id": order.id,
                "delivery_id": delivery.id,
                "tracking_code": delivery.tracking_code,
                "amount": str(delivery.rider_earning),
                "screen": "RiderWallet",
            },
        )
    try:
        from order_robot.services import sync_from_live_delivery

        sync_from_live_delivery(delivery)
    except Exception:
        pass
    return JsonResponse({"success": True, "message": "Delivery status updated.", "order": _order_payload(order)})


@csrf_exempt
@require_POST
def rider_delivery_proof_api(request, delivery_id):
    try:
        session = _require_rider_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    delivery = DeliveryRequest.objects.select_related("order", "rider", "rider__user").filter(id=delivery_id).first()
    if not delivery:
        return _error("Delivery not found.", status=404)
    if delivery.rider_id != session.rider_id:
        return _error("This delivery is not assigned to you.", status=403)
    if delivery.status in {DeliveryRequest.STATUS_DELIVERED, DeliveryRequest.STATUS_FAILED, DeliveryRequest.STATUS_CANCELLED, DeliveryRequest.STATUS_RETURNED}:
        return JsonResponse({"success": True, "message": f"Delivery is already {delivery.get_status_display().lower()}.", "order": _order_payload(delivery.order)})

    proof = request.FILES.get("proof_photo") or request.FILES.get("proof_of_delivery") or request.FILES.get("image")
    proof_note = _clean_text(request.POST.get("proof_note") or request.POST.get("note") or "Delivered with proof from rider app.")
    if proof:
        delivery.proof_of_delivery = proof
    delivery.proof_note = proof_note
    delivery.save(update_fields=["proof_of_delivery", "proof_note", "updated_at"])
    delivery.set_status(DeliveryRequest.STATUS_DELIVERED, actor=session.user, note=proof_note)
    _notify_delivery_status_change(delivery, DeliveryRequest.STATUS_DELIVERED, actor_user=session.user)
    _notify(
        delivery.rider.user,
        "Earnings credited",
        f"{delivery.rider_earning} has been credited for delivery {delivery.tracking_code}.",
        "delivery",
        {
            "order_id": delivery.order_id,
            "delivery_id": delivery.id,
            "tracking_code": delivery.tracking_code,
            "amount": str(delivery.rider_earning),
            "screen": "RiderWallet",
        },
    )
    try:
        from order_robot.services import sync_from_live_delivery

        sync_from_live_delivery(delivery)
    except Exception:
        pass
    return JsonResponse({"success": True, "message": "Delivery completed with proof.", "order": _order_payload(delivery.order)})


@csrf_exempt
@require_POST
def update_delivery_status_path_api(request, order_id, status):
    data = _json_body(request)
    mutable_body = dict(data)
    mutable_body.setdefault("order_id", order_id)
    mutable_body.setdefault("status", str(status or "").replace("-", "_"))
    request._body = json.dumps(mutable_body).encode("utf-8")
    return update_delivery_status_api(request)


@require_GET
def admin_dashboard_api(request):
    try:
        _require_admin_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    today = timezone.localdate()
    orders = Order.objects.all()
    live = DeliveryRequest.objects.all()
    return JsonResponse({
        "success": True,
        "dashboard": {
            "today_orders": orders.filter(created_at__date=today).count(),
            "pending_orders": orders.filter(status__in=["pending", "processing"]).count(),
            "ready_for_pickup": live.filter(is_ready_for_rider=True).exclude(status__in=[DeliveryRequest.STATUS_DELIVERED, DeliveryRequest.STATUS_CANCELLED, DeliveryRequest.STATUS_FAILED]).count(),
            "in_transit": live.filter(status=DeliveryRequest.STATUS_IN_TRANSIT).count(),
            "delivered_today": live.filter(status=DeliveryRequest.STATUS_DELIVERED, delivered_at__date=today).count(),
            "total_revenue": str(orders.aggregate(total=Sum("total"))["total"] or Decimal("0.00")),
            "pending_vendor_payouts": str(VendorWithdrawal.objects.filter(status__in=["pending", "under_review", "approved"]).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")),
            "pending_vendor_kyc": KYCRecord.objects.filter(kyc_status__in=["pending", "under_review", "in_review"]).count(),
            "pending_product_approvals": Product.objects.filter(approval_status="pending").count(),
            "pending_service_providers": ServiceProviderProfile.objects.filter(
                verification_status__in=[ServiceProviderProfile.STATUS_SUBMITTED, ServiceProviderProfile.STATUS_PENDING]
            ).count(),
            "provider_change_requests": ProviderProfileChangeRequest.objects.filter(status=ProviderProfileChangeRequest.STATUS_PENDING).count(),
            "new_service_quotes": ServiceQuoteRequest.objects.filter(status="new").count(),
            "online_riders": RiderProfile.objects.filter(is_online=True, is_active=True).count(),
            "withdrawal_requests": VendorWithdrawal.objects.filter(status__in=["pending", "under_review"]).count(),
        },
    })


@require_GET
def admin_service_providers_api(request):
    try:
        _require_admin_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    status_filter = _clean_text(request.GET.get("status") or ServiceProviderProfile.STATUS_PENDING)
    providers = ServiceProviderProfile.objects.select_related("user").order_by("-created_at")
    if status_filter and status_filter != "all":
        providers = providers.filter(verification_status=status_filter)
    return JsonResponse({
        "success": True,
        "providers": [_service_provider_payload(provider, request) for provider in providers[:200]],
    })


@csrf_exempt
@require_POST
def admin_service_provider_action_api(request, provider_id, action):
    try:
        session = _require_admin_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    provider = ServiceProviderProfile.objects.select_related("user").filter(pk=provider_id).first()
    if not provider:
        return _error("Service provider not found.", status=404)
    data = _json_body(request)
    note = _clean_text(data.get("verification_note") or data.get("note") or data.get("reason"))
    if action == "approve":
        approve_provider(provider, session.user, verify=False, note=note)
    elif action == "verify":
        approve_provider(provider, session.user, verify=True, note=note)
    elif action == "reject":
        reject_provider(provider, session.user, note or "Rejected by Arolana admin.")
    elif action in ["request-changes", "request_changes"]:
        request_provider_changes(provider, session.user, note or "Please update your provider profile and resubmit.")
    elif action == "suspend":
        suspend_provider(provider, session.user, note or "Provider account suspended by Arolana admin.")
    elif action == "reactivate":
        approve_provider(provider, session.user, verify=provider.is_verified, note=note)
    elif action == "deactivate":
        provider.is_active = False
        provider.save(update_fields=["is_active", "updated_at"])
    else:
        return _error("Invalid service provider action.")
    _notify(
        provider.user,
        "Service provider verification updated",
        f"Your Arolana service provider profile is now {provider.get_verification_status_display().lower()}.",
        "system",
        {"service_provider_id": provider.id, "verification_status": provider.verification_status},
    )
    return JsonResponse({"success": True, "provider": _service_provider_payload(provider, request), "reviewed_by": session.user.email})


@require_GET
def admin_provider_change_requests_api(request):
    try:
        _require_admin_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    status_filter = _clean_text(request.GET.get("status") or ProviderProfileChangeRequest.STATUS_PENDING)
    changes = ProviderProfileChangeRequest.objects.select_related("provider", "requested_by", "reviewed_by").order_by("-created_at")
    if status_filter and status_filter != "all":
        changes = changes.filter(status=status_filter)
    return JsonResponse({
        "success": True,
        "change_requests": [
            {
                "id": change.id,
                "provider_id": change.provider_id,
                "provider_name": change.provider.business_name,
                "requested_by": change.requested_by.email if change.requested_by else "",
                "old_values": change.old_values,
                "proposed_values": change.proposed_values,
                "sensitive_fields": change.sensitive_fields,
                "status": change.status,
                "admin_note": change.admin_note,
                "created_at": change.created_at.isoformat() if change.created_at else "",
                "reviewed_at": change.reviewed_at.isoformat() if change.reviewed_at else "",
            }
            for change in changes[:200]
        ],
    })


@csrf_exempt
@require_POST
def admin_provider_change_request_action_api(request, change_id, action):
    try:
        session = _require_admin_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    change = ProviderProfileChangeRequest.objects.select_related("provider").filter(pk=change_id).first()
    if not change:
        return _error("Provider change request not found.", status=404)
    note = _clean_text(_json_body(request).get("note") or _json_body(request).get("admin_note"))
    if action == "approve":
        approve_profile_change_request(change, session.user, note)
    elif action == "reject":
        reject_profile_change_request(change, session.user, note or "Rejected by Arolana admin.")
    else:
        return _error("Invalid change request action.")
    return JsonResponse({"success": True, "change_request": {"id": change.id, "status": change.status, "admin_note": change.admin_note}})


@require_GET
def admin_service_quotes_api(request):
    try:
        _require_admin_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    status_filter = _clean_text(request.GET.get("status") or "")
    quotes = ServiceQuoteRequest.objects.select_related("provider", "category", "product", "customer").order_by("-created_at")
    if status_filter and status_filter != "all":
        quotes = quotes.filter(status=status_filter)
    return JsonResponse({
        "success": True,
        "quotes": [_service_quote_payload(quote) for quote in quotes[:250]],
    })


@csrf_exempt
@require_POST
def admin_service_quote_status_api(request, quote_id):
    try:
        session = _require_admin_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    quote = ServiceQuoteRequest.objects.select_related("provider", "customer").filter(pk=quote_id).first()
    if not quote:
        return _error("Service quote request not found.", status=404)
    data = _json_body(request)
    next_status = _clean_text(data.get("status"))
    valid_statuses = {value for value, _label in ServiceQuoteRequest.STATUS_CHOICES}
    if next_status not in valid_statuses:
        return _error("Invalid quote request status.")
    quote.status = next_status
    quote.save(update_fields=["status", "updated_at"])
    if quote.customer:
        _notify(
            quote.customer,
            "Service request updated",
            f"Your request for {quote.service_needed} is now {quote.get_status_display().lower()}.",
            "system",
            {"service_quote_request_id": quote.id, "status": quote.status},
        )
    return JsonResponse({"success": True, "quote": _service_quote_payload(quote), "updated_by": session.user.email})


@csrf_exempt
@require_POST
def admin_assign_service_provider_api(request, quote_id):
    try:
        session = _require_admin_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    quote = ServiceQuoteRequest.objects.filter(pk=quote_id).first()
    if not quote:
        return _error("Service quote request not found.", status=404)
    data = _json_body(request)
    provider = ServiceProviderProfile.objects.filter(pk=data.get("provider_id")).first()
    if not provider:
        return _error("Service provider not found.", status=404)
    try:
        assign_service_request(quote, provider, session.user, _clean_text(data.get("note")))
    except Exception as error:
        return _error(error, status=400)
    return JsonResponse({"success": True, "quote": _service_quote_payload(quote), "assigned_by": session.user.email})


@require_GET
def provider_dashboard_api(request):
    try:
        session, provider = _require_provider_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    quotes = provider.quote_requests.all()
    notifications = provider_workspace_notifications(provider)
    active_jobs = quotes.filter(
        status__in=["assigned", "accepted", "on_the_way", "in_progress"]
    ).select_related("category", "product", "customer").order_by("-created_at")[:3]
    return JsonResponse({
        "success": True,
        "provider": _service_provider_payload(provider, request),
        "access": {
            "dashboard_allowed": provider.approval_allows_dashboard,
            "serious_jobs_allowed": provider.can_receive_serious_jobs,
            "pending_screen_required": not provider.approval_allows_dashboard,
        },
        "cards": {
            "assigned_jobs": quotes.filter(status="assigned").count(),
            "accepted_jobs": quotes.filter(status="accepted").count(),
            "in_progress_jobs": quotes.filter(status="in_progress").count(),
            "completed_jobs": quotes.filter(status__in=["completed", "closed"]).count(),
            "unread_notifications": notifications.filter(is_read=False).count(),
            "profile_completion": provider.profile_completion_percent,
        },
        "recent_jobs": [_service_quote_payload(quote) for quote in active_jobs],
        "recent_notifications": [
            {
                "id": note.id,
                "title": note.title,
                "message": note.message,
                "notification_type": note.notification_type,
                "is_read": note.is_read,
                "created_at": note.created_at.isoformat() if note.created_at else "",
                "metadata": note.metadata,
            }
            for note in notifications[:3]
        ],
        "session": _staff_session_payload(session) if session else {},
    })


@require_GET
def provider_requests_api(request):
    try:
        _session, provider = _require_provider_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    if not provider.approval_allows_dashboard:
        return _error("Provider profile is not approved yet.", status=403)
    status_filter = _clean_text(request.GET.get("status") or "")
    quotes = provider.quote_requests.select_related("category", "product", "customer").order_by("-created_at")
    if status_filter:
        quotes = quotes.filter(status=status_filter)
    return JsonResponse({"success": True, "requests": [_service_quote_payload(quote) for quote in quotes[:100]]})


@csrf_exempt
@require_POST
def provider_request_action_api(request, quote_id, action):
    try:
        _session, provider = _require_provider_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    if not provider.approval_allows_dashboard:
        return _error("Provider profile is not approved yet.", status=403)
    quote = provider.quote_requests.filter(pk=quote_id).first()
    if not quote:
        return _error("Service request not found.", status=404)
    data = _json_body(request)
    if action == "accept":
        if quote.status != "assigned":
            return _error("Only newly assigned jobs can be accepted.")
        quote.status = "accepted"
        quote.accepted_at = timezone.now()
    elif action == "reject":
        if quote.status != "assigned":
            return _error("Only newly assigned jobs can be rejected.")
        quote.status = "rejected_by_provider"
    elif action == "status":
        next_status = _clean_text(data.get("status"))
        allowed_transitions = {
            "accepted": {"accepted", "on_the_way"},
            "on_the_way": {"on_the_way", "in_progress"},
            "in_progress": {"in_progress", "completed"},
        }
        if next_status not in allowed_transitions.get(quote.status, {quote.status}):
            return _error("That job status change is not allowed.")
        quote.status = next_status
        if next_status == "completed":
            quote.completed_at = timezone.now()
    else:
        return _error("Invalid provider request action.")
    quote.provider_note = _clean_text(data.get("provider_note") or quote.provider_note)
    quote.save()
    if quote.customer:
        _notify(quote.customer, "Service request updated", f"Your service request is now {quote.get_status_display().lower()}.", "system", {"service_quote_request_id": quote.id, "status": quote.status})
    return JsonResponse({"success": True, "request": _service_quote_payload(quote)})


@require_GET
def provider_notifications_api(request):
    try:
        _session, provider = _require_provider_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    notes = provider_workspace_notifications(provider)
    return JsonResponse({
        "success": True,
        "unread_count": notes.filter(is_read=False).count(),
        "notifications": [
            {
                "id": note.id,
                "title": note.title,
                "message": note.message,
                "notification_type": note.notification_type,
                "is_read": note.is_read,
                "created_at": note.created_at.isoformat() if note.created_at else "",
                "metadata": note.metadata,
            }
            for note in notes[:100]
        ],
    })


@require_GET
def admin_vendors_api(request):
    try:
        _require_admin_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    vendors = VendorProfile.objects.select_related("user").order_by("-created_at")[:200]
    return JsonResponse({"success": True, "vendors": [
        {
            **_vendor_payload(vendor),
            "shop_name": vendor.store_name,
            "email": vendor.user.email,
            "phone": vendor.support_phone or vendor.pickup_phone,
            "total_products": Product.objects.filter(vendor=vendor.user).count(),
            "total_sales": vendor.total_sales,
            "rating_avg": str(vendor.rating_avg),
            "manufacturer_badge": vendor.manufacturer_badge_label if vendor.manufacturer_verified else "",
        }
        for vendor in vendors
    ]})


@csrf_exempt
@require_POST
def admin_vendor_action_api(request, vendor_id, action):
    try:
        session = _require_admin_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    vendor = VendorProfile.objects.filter(id=vendor_id).first()
    if not vendor:
        return _error("Vendor not found.", status=404)
    if action == "approve":
        vendor.approval_status = "approved"
        vendor.is_active = True
        vendor.is_verified = True
        vendor.approved_by = session.user
        vendor.approved_at = timezone.now()
    elif action == "verify-manufacturer":
        vendor.manufacturer_verified = True
        vendor.is_verified = True
        vendor.approval_status = "approved"
        vendor.approved_by = session.user
        vendor.approved_at = timezone.now()
    elif action == "suspend":
        vendor.approval_status = "suspended"
        vendor.is_active = False
    elif action == "reject":
        vendor.approval_status = "rejected"
        vendor.is_verified = False
    else:
        return _error("Invalid vendor action.")
    vendor.save()
    _notify(vendor.user, "Vendor account updated", f"Your vendor account is now {vendor.approval_status}.", "vendor")
    return JsonResponse({"success": True, "vendor": _vendor_payload(vendor)})


@require_GET
def admin_pending_products_api(request):
    try:
        _require_admin_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    products = Product.objects.select_related("vendor", "brand").filter(approval_status="pending").order_by("-submitted_for_review_at")[:120]
    return JsonResponse({"success": True, "products": [
        {**_product_payload(product), "vendor_name": product.vendor.get_full_name() or product.vendor.email, "brand": product.brand.name if product.brand else ""}
        for product in products
    ]})


@csrf_exempt
@require_POST
def admin_product_action_api(request, product_id, action):
    try:
        session = _require_admin_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    product = Product.objects.filter(id=product_id).first()
    if not product:
        return _error("Product not found.", status=404)
    if action == "approve":
        product.approval_status = "approved"
        product.is_active = True
        product.approved_by = session.user
        product.approved_at = timezone.now()
    elif action == "reject":
        product.approval_status = "rejected"
        product.is_active = False
    else:
        return _error("Invalid product action.")
    product.save()
    _notify(product.vendor, "Product review update", f"{product.name} is now {product.approval_status}.", "product", {"product_id": product.id})
    return JsonResponse({"success": True, "product": _product_payload(product)})


@require_GET
def admin_withdrawals_api(request):
    try:
        _require_admin_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    withdrawals = VendorWithdrawal.objects.select_related("vendor", "bank_account").order_by("-requested_at")[:100]
    return JsonResponse({"success": True, "withdrawals": [
        {
            "id": item.id,
            "vendor_name": item.vendor.store_name,
            "amount": str(item.amount),
            "currency": item.currency,
            "status": item.status,
            "bank_account": item.bank_account.bank_name if item.bank_account else "",
            "created_at": item.requested_at.isoformat() if item.requested_at else "",
        }
        for item in withdrawals
    ]})


@require_GET
def admin_rfqs_api(request):
    try:
        _require_admin_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    rfqs = VendorRFQ.objects.select_related("vendor", "product", "customer").order_by("-created_at")[:100]
    return JsonResponse({"success": True, "rfqs": [
        {
            "id": item.id,
            "vendor_name": item.vendor.store_name,
            "product_name": item.product.name if item.product else "",
            "quantity": item.quantity,
            "budget": str(item.budget or ""),
            "status": item.status,
        }
        for item in rfqs
    ]})


@require_GET
def admin_messages_api(request):
    try:
        session = _require_admin_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    notes = Notification.objects.filter(user=session.user, notification_type="message", is_archived=False).order_by("-created_at")[:100]
    conversations = [_smartchat_payload(item, "admin") for item in _staff_conversations_for_session(session)]
    return JsonResponse({"success": True, "conversations": conversations, "messages": [
        {"id": note.id, "title": note.title, "last_message": note.message, "unread_count": 0 if note.is_read else 1, "updated_at": note.created_at.isoformat() if note.created_at else ""}
        for note in notes
    ]})


@csrf_exempt
@require_POST
def admin_create_rider_api(request):
    data = _json_body(request)
    try:
        _require_admin_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    full_name = _clean_text(data.get("full_name"))
    phone = _clean_phone(data.get("phone_number") or data.get("phone"))
    email = _clean_text(data.get("email")).lower()
    pin = _clean_text(data.get("pin") or data.get("password"))
    if not full_name or not phone or not pin:
        return _error("Full name, phone, and PIN are required.")
    User = get_user_model()
    username_base = (email.split("@")[0] if email else phone.replace("+", "")) or "rider"
    username = username_base
    suffix = 2
    while User.objects.filter(username=username).exists():
        username = f"{username_base}{suffix}"
        suffix += 1
    with transaction.atomic():
        user = User.objects.create_user(username=username, email=email or f"{username}@arolana.local", password=pin)
        user.user_type = "customer"
        names = full_name.split()
        user.first_name = names[0]
        user.last_name = " ".join(names[1:])
        try:
            user.phone_number = phone
        except Exception:
            pass
        user.save()
        vehicle = None
        vehicle_type = _clean_text(data.get("vehicle_type")).lower()
        if vehicle_type:
            vehicle = DeliveryVehicle.objects.filter(Q(vehicle_type=vehicle_type) | Q(name__icontains=vehicle_type)).first()
        zone_name = _clean_text(data.get("zone"))
        zone = DeliveryZone.objects.filter(Q(name__icontains=zone_name) | Q(city__icontains=zone_name)).first() if zone_name else None
        rider = RiderProfile.objects.create(user=user, phone=phone, vehicle=vehicle, zone=zone, kyc_status=RiderProfile.KYC_APPROVED)
        RiderCredential.objects.update_or_create(rider=rider, defaults={"is_active": True})
        rider.mobile_credential.set_pin(pin)
        rider.mobile_credential.save(update_fields=["pin_hash", "updated_at"])
    return JsonResponse({"success": True, "rider": _rider_payload(rider), "message": "Rider created."})


@csrf_exempt
@require_POST
def admin_message_send_api(request):
    data = _json_body(request)
    try:
        session = _require_admin_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    message = _clean_text(data.get("message"))
    if not message:
        return _error("Message is required.")
    conversation_id = data.get("conversation_id")
    conversation = SmartChatConversation.objects.filter(id=conversation_id).first() if conversation_id else None
    if not conversation:
        subject = _clean_text(data.get("subject")) or "Arolana admin message"
        conversation = SmartChatConversation.objects.create(
            user=session.user,
            assigned_admin=session.user,
            status=SmartChatConversation.STATUS_ADMIN_ACTIVE,
            customer_name="Arolana Admin",
            customer_email=session.user.email or "",
            title=subject,
            selected_variants={"staff_mobile_chat": True, "staff_role": "admin", "recipient_type": data.get("recipient_type") or "vendor"},
        )
    else:
        conversation.assign_admin(session.user)
    chat_message = SmartChatMessage.objects.create(
        conversation=conversation,
        sender_type=SmartChatMessage.SENDER_ADMIN,
        user=session.user,
        message=message,
        metadata={"recipient_type": data.get("recipient_type") or "vendor", "staff_role": "admin"},
    )
    if conversation.user_id and conversation.user_id != session.user_id:
        _notify(conversation.user, "Arolana admin replied", message, "message", {"smartchat_conversation_id": conversation.id, "smartchat_message_id": chat_message.id})
    return JsonResponse({"success": True, "message": "Admin message sent.", "from": session.user.email, "conversation": _smartchat_payload(conversation, "admin")})


@require_GET
def rider_me_api(request):
    try:
        session = _require_rider_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    return JsonResponse({"success": True, "rider": _rider_payload(session.rider)})


@require_GET
def rider_settings_info_api(request):
    try:
        session = _require_rider_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    rider = session.rider
    policies = {
        "Terms and Conditions": (
            "Arolana riders must follow all dispatch instructions, verify pickup handoff, protect customer packages, "
            "and update every delivery status truthfully. Riders are expected to obey applicable Nigerian road traffic "
            "rules, including safe riding/driving, valid licensing where required, helmet and safety compliance, and "
            "lawful conduct around pickup and dropoff locations. Arolana may suspend dispatch access for unsafe conduct, "
            "fraud, package tampering, repeated failed handoffs without valid reason, or abuse of customers, vendors, or staff."
        ),
        "Privacy Policy": (
            "Arolana processes rider profile, location, payout, device, and delivery data only for dispatch, safety, "
            "customer support, fraud prevention, payout administration, and legal compliance. Rider data should be handled "
            "in line with the Nigeria Data Protection Act 2023 and Arolana internal access controls. Location is used for "
            "active dispatch/tracking and operational audit. Riders must not disclose customer phone numbers, addresses, "
            "order details, or delivery notes outside the delivery purpose."
        ),
        "Delivery Policy": (
            "Before pickup, confirm the order number/tracking code and vendor handoff. At pickup, mark Arrived at Vendor, "
            "then Picked Up only after the package is physically released to you. During transit, protect the item from "
            "loss, damage, water, heat, and unauthorized access. At customer arrival, call the customer where needed, "
            "confirm identity reasonably, capture proof where required, and mark Delivered only after handoff. If delivery "
            "fails, record a clear reason such as customer unavailable, wrong address, unsafe location, payment issue, or "
            "vendor/customer dispute."
        ),
        "Payout Policy": (
            "Rider earnings are credited after a completed and valid delivery. Failed, cancelled, or disputed deliveries "
            "may not qualify for completed earnings until admin review. Payouts are reviewed through Arolana admin using "
            "the rider bank details saved in this app. Bank account names should match the rider or approved payout owner. "
            "Arolana may hold, reverse, or investigate earnings tied to fraud, duplicate completion, missing proof, or customer/vendor dispute."
        ),
        "Account deletion policy": (
            "A rider may request account deletion or deactivation from the app. Arolana may retain order, payout, tax, fraud-prevention, "
            "safety, and dispute records where required for legal, accounting, or compliance reasons. Active deliveries and pending payouts "
            "must be resolved before full operational closure. Deactivation stops new dispatch access while admin reviews the request."
        ),
    }
    completion_base = 6
    completion_score = sum([
        bool(rider.profile_photo),
        bool(getattr(rider, "dashboard_image", None)),
        bool(rider.phone),
        bool(getattr(rider, "about", "")),
        bool(rider.payout_bank_name and rider.payout_account_name and rider.payout_account_number),
        rider.kyc_status == RiderProfile.KYC_APPROVED,
    ])
    return JsonResponse({"success": True, "settings": {
        "support": {
            "phone": "+2349033713922",
            "whatsapp": "+2349132924620",
            "email": "support@arolana.com",
            "hours": "Arolana operations support is available for dispatch, payout, safety, and account issues.",
        },
        "policies": policies,
        "performance": {
            "rating": str(rider.rating_avg),
            "completed_deliveries": rider.completed_deliveries,
            "failed_deliveries": rider.failed_deliveries,
            "completion_rate": "Synced from completed and failed delivery records.",
            "profile_completion_percent": int((completion_score / completion_base) * 100),
            "tips": [
                "Update every trip stage at the actual location and time.",
                "Use proof photos for completed deliveries where possible.",
                "Record honest failed-delivery reasons for admin and customer support.",
                "Keep payout bank details accurate before requesting payment.",
            ],
        },
        "profile_edit": {
            "status": rider.profile_edit_status,
            "can_edit": rider.can_request_profile_edit,
            "requested_at": rider.profile_edit_requested_at.isoformat() if rider.profile_edit_requested_at else "",
            "available_at": rider.profile_edit_available_at.isoformat() if rider.profile_edit_available_at else "",
            "pending_data": rider.profile_edit_pending_data or {},
            "rule": "For rider safety, payout, and dispatch integrity, account profile edits go to admin review and can be submitted once every 14 days.",
        },
        "vehicles": [
            {"id": vehicle.id, "name": vehicle.name, "vehicle_type": vehicle.vehicle_type}
            for vehicle in DeliveryVehicle.objects.filter(is_active=True).order_by("name")
        ],
    }})


@csrf_exempt
@require_POST
def rider_profile_update_api(request):
    data = _json_body(request)
    try:
        session = _require_rider_session(request)
    except PermissionError as error:
        return _error(error, status=403)

    rider = session.rider
    if not rider.can_request_profile_edit:
        next_date = rider.profile_edit_available_at.strftime("%b %d, %Y") if rider.profile_edit_available_at else "later"
        return _error(f"You can edit your rider profile again from {next_date}. Rider profile edits are limited to once every 14 days.")

    first_name = _clean_text(data.get("first_name") or data.get("full_name", "").split(" ")[0])
    last_name = _clean_text(data.get("last_name") or " ".join(str(data.get("full_name") or "").split(" ")[1:]))
    phone = _clean_phone(data.get("phone") or data.get("phone_number"))
    emergency_phone = _clean_phone(data.get("emergency_phone"))
    about = _clean_text(data.get("about"))
    rider_type = _clean_text(data.get("rider_type") or rider.rider_type)
    vehicle_id = data.get("vehicle_id") or data.get("vehicle")

    if not phone:
        return _error("Phone number is required.")
    if len(about) < 20:
        return _error("About rider should be at least 20 characters so admin can review your profile properly.")
    if rider_type not in dict(RiderProfile.RIDER_TYPE_CHOICES):
        rider_type = rider.rider_type
    vehicle = None
    if vehicle_id:
        vehicle = DeliveryVehicle.objects.filter(id=vehicle_id, is_active=True).first()
        if not vehicle:
            return _error("Selected vehicle is not available.")

    pending = {
        "first_name": first_name,
        "last_name": last_name,
        "phone": phone,
        "emergency_phone": emergency_phone,
        "about": about,
        "rider_type": rider_type,
        "vehicle_id": vehicle.id if vehicle else rider.vehicle_id,
        "vehicle_name": vehicle.name if vehicle else safe_str(getattr(rider.vehicle, "name", "")),
        "submitted_from": "staff_mobile",
    }
    now = timezone.now()
    rider.profile_edit_pending_data = pending
    rider.profile_edit_status = "pending_admin_review"
    rider.profile_edit_requested_at = now
    rider.profile_edit_available_at = now + timedelta(days=14)
    rider.kyc_status = RiderProfile.KYC_PENDING
    rider.is_online = False
    rider.is_available = False
    rider.save(update_fields=[
        "profile_edit_pending_data",
        "profile_edit_status",
        "profile_edit_requested_at",
        "profile_edit_available_at",
        "kyc_status",
        "is_online",
        "is_available",
        "updated_at",
    ])

    for admin in get_user_model().objects.filter(Q(is_staff=True) | Q(is_superuser=True), is_active=True)[:20]:
        _notify(
            admin,
            "Rider profile edit needs review",
            f"{_rider_name(rider)} submitted rider account changes for admin verification.",
            "rider",
            {"rider_id": rider.id, "profile_edit_status": rider.profile_edit_status},
        )
    _notify(
        session.user,
        "Profile edit submitted",
        "Your rider account changes were sent to Arolana admin. You can submit another profile edit after 14 days.",
        "rider",
        {"rider_id": rider.id, "profile_edit_available_at": rider.profile_edit_available_at.isoformat()},
    )
    return JsonResponse({
        "success": True,
        "message": "Profile changes submitted for admin verification.",
        "rider": _rider_payload(rider),
    })


@csrf_exempt
@require_POST
def rider_profile_photo_api(request):
    try:
        session = _require_rider_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    uploaded = request.FILES.get("profile_photo") or request.FILES.get("photo") or request.FILES.get("image")
    if not uploaded:
        return _error("Profile photo file is required.")
    session.rider.profile_photo = uploaded
    session.rider.save(update_fields=["profile_photo", "updated_at"])
    return JsonResponse({"success": True, "message": "Profile photo updated.", "rider": _rider_payload(session.rider)})


@csrf_exempt
@require_POST
def rider_profile_banner_api(request):
    try:
        session = _require_rider_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    uploaded = request.FILES.get("dashboard_image") or request.FILES.get("banner") or request.FILES.get("image")
    if not uploaded:
        return _error("Dashboard banner image is required.")
    session.rider.dashboard_image = uploaded
    session.rider.save(update_fields=["dashboard_image", "updated_at"])
    return JsonResponse({"success": True, "message": "Dashboard image updated.", "rider": _rider_payload(session.rider)})


@csrf_exempt
@require_POST
def rider_change_password_api(request):
    data = _json_body(request)
    try:
        session = _require_rider_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    current = _clean_text(data.get("current_password") or data.get("current_pin"))
    new_password = _clean_text(data.get("new_password") or data.get("new_pin"))
    confirm = _clean_text(data.get("confirm_password") or data.get("confirm_pin"))
    if not current or not new_password:
        return _error("Current password and new password are required.")
    if new_password != confirm:
        return _error("New password and confirmation do not match.")
    if not session.user.check_password(current):
        return _error("Current password is incorrect.", status=403)
    session.user.set_password(new_password)
    session.user.save(update_fields=["password"])
    try:
        if hasattr(session.rider, "mobile_credential") and new_password.isdigit():
            session.rider.mobile_credential.set_pin(new_password)
            session.rider.mobile_credential.save(update_fields=["pin_hash", "updated_at"])
    except Exception:
        pass
    _notify(session.user, "Security updated", "Your rider password/PIN was changed successfully.", "security")
    return JsonResponse({"success": True, "message": "Password/PIN changed successfully.", "session": _staff_session_payload(session)})


@csrf_exempt
@require_POST
def rider_preferences_api(request):
    data = _json_body(request)
    try:
        session = _require_rider_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    language = _clean_text(data.get("preferred_language") or data.get("language") or session.rider.preferred_language).lower()
    if language not in {"english", "french", "arabic", "chinese", "spanish"}:
        return _error("Unsupported language.")
    preferences = data.get("notification_preferences")
    if not isinstance(preferences, dict):
        preferences = {
            "push": bool(data.get("push", True)),
            "sound": bool(data.get("sound", True)),
            "vibration": bool(data.get("vibration", True)),
            "delivery_alerts": bool(data.get("delivery_alerts", True)),
            "earnings_alerts": bool(data.get("earnings_alerts", True)),
            "message_alerts": bool(data.get("message_alerts", True)),
        }
    session.rider.preferred_language = language
    session.rider.notification_preferences = preferences
    session.rider.save(update_fields=["preferred_language", "notification_preferences", "updated_at"])
    return JsonResponse({"success": True, "message": "Preferences saved.", "rider": _rider_payload(session.rider)})


@csrf_exempt
@require_POST
def rider_report_problem_api(request):
    data = _json_body(request)
    try:
        session = _require_rider_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    subject = _clean_text(data.get("subject")) or "Rider reported a problem"
    message = _clean_text(data.get("message"))
    category = _clean_text(data.get("category")) or "rider_support"
    if not message:
        return _error("Describe the problem before sending.")
    metadata = {
        "rider_id": session.rider_id,
        "rider_name": _rider_name(session.rider),
        "category": category,
        "source": "staff_mobile_rider_settings",
    }
    for admin_user in _admin_notification_users():
        _notify(admin_user, subject, message, "support", metadata)
    _notify(session.user, "Support report sent", "Arolana support has received your rider report.", "support", metadata)
    return JsonResponse({"success": True, "message": "Your report has been sent to Arolana support."})


@csrf_exempt
@require_POST
def rider_bank_account_save_api(request):
    data = _json_body(request)
    try:
        session = _require_rider_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    required = ["bank_name", "account_name", "account_number"]
    for field in required:
        if not _clean_text(data.get(field)):
            return _error(f"{field.replace('_', ' ').title()} is required.")
    currency = _clean_text(data.get("preferred_currency") or data.get("currency") or "NGN").upper()
    if currency not in {"NGN", "USD", "GBP", "EUR", "CNY", "CAD"}:
        return _error("Unsupported payout currency.")
    rider = session.rider
    rider.payout_bank_name = _clean_text(data.get("bank_name"))
    rider.payout_account_name = _clean_text(data.get("account_name"))
    rider.payout_account_number = _clean_text(data.get("account_number"))
    rider.payout_bank_country = _clean_text(data.get("bank_country") or "Nigeria")
    rider.payout_preferred_currency = currency
    rider.save(update_fields=[
        "payout_bank_name",
        "payout_account_name",
        "payout_account_number",
        "payout_bank_country",
        "payout_preferred_currency",
        "updated_at",
    ])
    _notify(session.user, "Payout bank updated", "Your rider payout bank details were saved successfully.", "payment")
    return JsonResponse({"success": True, "message": "Payout bank details saved.", "rider": _rider_payload(rider)})


@require_GET
def rider_bank_account_api(request):
    try:
        session = _require_rider_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    rider = session.rider
    return JsonResponse({"success": True, "bank_account": {
        "bank_name": safe_str(rider.payout_bank_name),
        "account_name": safe_str(rider.payout_account_name),
        "account_number": safe_str(rider.payout_account_number),
        "bank_country": safe_str(rider.payout_bank_country),
        "preferred_currency": safe_str(rider.payout_preferred_currency),
    }})


@csrf_exempt
@require_POST
def rider_delete_request_api(request):
    try:
        session = _require_rider_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    session.rider.is_suspended = True
    session.rider.is_online = False
    session.rider.is_available = False
    session.rider.admin_notes = (session.rider.admin_notes + "\n" if session.rider.admin_notes else "") + "Rider requested account deletion/deactivation from mobile app."
    session.rider.save(update_fields=["is_suspended", "is_online", "is_available", "admin_notes", "updated_at"])
    for admin in get_user_model().objects.filter(is_staff=True, is_active=True)[:20]:
        _notify(admin, "Rider account deletion request", f"{_rider_name(session.rider)} requested account deletion/deactivation.", "rider")
    _notify(session.user, "Account deletion request received", "Your rider account deletion request has been sent to Arolana support.", "security")
    return JsonResponse({"success": True, "message": "Account deletion request received."})


@require_GET
def rider_dashboard_api(request):
    try:
        session = _require_rider_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    deliveries = DeliveryRequest.objects.filter(rider=session.rider)
    today = timezone.localdate()
    active_statuses = [
        DeliveryRequest.STATUS_ASSIGNED,
        DeliveryRequest.STATUS_ACCEPTED,
        DeliveryRequest.STATUS_ARRIVED_PICKUP,
        DeliveryRequest.STATUS_PICKED_UP,
        DeliveryRequest.STATUS_IN_TRANSIT,
        DeliveryRequest.STATUS_ARRIVED_CUSTOMER,
    ]
    active_deliveries = deliveries.filter(status__in=active_statuses).order_by("-updated_at", "-created_at")[:10]
    available_requests = DeliveryRequest.objects.none()
    can_see_available_requests = bool(
        session.rider.kyc_status == session.rider.KYC_APPROVED
        and session.rider.is_online
        and not session.rider.is_suspended
    )
    if can_see_available_requests:
        available_requests = DeliveryRequest.objects.filter(
            rider__isnull=True,
            is_ready_for_rider=True,
            status__in=[DeliveryRequest.STATUS_PENDING, DeliveryRequest.STATUS_ASSIGNED],
        ).select_related("order", "rider", "rider__user").prefetch_related(
            "order__items__product",
            "order__items__variant__product",
            "status_history__actor",
        ).order_by("-created_at")[:10]
    available_payloads = []
    for delivery in available_requests:
        payload = _delivery_payload(delivery)
        payload.update({
            "status": DeliveryRequest.STATUS_ASSIGNED,
            "delivery_status": DeliveryRequest.STATUS_ASSIGNED,
            "assignment_mode": "available_request",
            "rider_name": "",
            "rider_phone": "",
        })
        available_payloads.append(payload)
    assigned_to_rider_count = deliveries.filter(status=DeliveryRequest.STATUS_ASSIGNED).count()
    available_count = len(available_payloads)
    new_pickup_count = assigned_to_rider_count + available_count
    unread_notifications = Notification.objects.filter(user=session.rider.user, is_read=False, is_archived=False).count()
    completed = deliveries.filter(status=DeliveryRequest.STATUS_DELIVERED, delivered_at__isnull=False)
    today_earnings = completed.filter(delivered_at__date=today).aggregate(total=Sum("rider_earning"))["total"] or Decimal("0.00")
    return JsonResponse({"success": True, "dashboard": {
        "today_deliveries": deliveries.filter(created_at__date=today).count(),
        "assigned_deliveries": deliveries.filter(status__in=active_statuses).count() + available_count,
        "delivery_inbox_count": new_pickup_count,
        "new_order_count": new_pickup_count,
        "new_pickups": new_pickup_count,
        "unread_notifications": unread_notifications,
        "in_transit": deliveries.filter(status=DeliveryRequest.STATUS_IN_TRANSIT).count(),
        "completed_today": deliveries.filter(status=DeliveryRequest.STATUS_DELIVERED, delivered_at__date=today).count(),
        "today_earnings": str(today_earnings),
        "rating": str(session.rider.rating_avg),
        "rider_current_latitude": str(session.rider.current_latitude or ""),
        "rider_current_longitude": str(session.rider.current_longitude or ""),
        "available_requests": available_payloads,
        "active_deliveries": available_payloads + [_delivery_payload(delivery) for delivery in active_deliveries],
    }})


@require_GET
def rider_earnings_api(request):
    try:
        session = _require_rider_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    deliveries = DeliveryRequest.objects.filter(rider=session.rider)
    completed = deliveries.filter(status=DeliveryRequest.STATUS_DELIVERED, delivered_at__isnull=False)
    completed_total = completed.aggregate(total=Sum("rider_earning"))["total"] or Decimal("0.00")
    paid_total = RiderPayout.objects.filter(rider=session.rider, status=RiderPayout.STATUS_PAID).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    approved_total = RiderPayout.objects.filter(rider=session.rider, status=RiderPayout.STATUS_APPROVED).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    pending_payout_total = RiderPayout.objects.filter(rider=session.rider, status=RiderPayout.STATUS_PENDING).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    pending_earnings = max(completed_total - paid_total - approved_total - pending_payout_total, Decimal("0.00"))
    balance = pending_earnings + approved_total + pending_payout_total
    wallet, _created = RiderWallet.objects.get_or_create(rider=session.rider)
    wallet.balance = balance
    wallet.pending_balance = pending_earnings + pending_payout_total
    wallet.total_earned = completed_total
    wallet.total_paid_out = paid_total
    wallet.save(update_fields=["balance", "pending_balance", "total_earned", "total_paid_out", "updated_at"])
    return JsonResponse({"success": True, "earnings": {
        "today_earnings": str(completed.filter(delivered_at__date=timezone.localdate()).aggregate(total=Sum("rider_earning"))["total"] or Decimal("0.00")),
        "pending_earnings": str(pending_earnings + pending_payout_total),
        "available_balance": str(approved_total),
        "paid_earnings": str(paid_total),
        "balance": str(balance),
        "total_earnings": str(completed_total),
        "transactions": [
            {
                "id": delivery.id,
                "order_id": delivery.order_id,
                "tracking_code": delivery.tracking_code,
                "type": "delivery_earning",
                "amount": str(delivery.rider_earning),
                "status": "completed",
                "created_at": delivery.delivered_at.isoformat() if delivery.delivered_at else "",
            }
            for delivery in completed.order_by("-delivered_at", "-updated_at")[:30]
        ],
        "payouts": [
            {
                "id": payout.id,
                "amount": str(payout.amount),
                "status": payout.status,
                "bank_name": payout.bank_name,
                "account_name": payout.account_name,
                "account_number": payout.account_number,
                "created_at": payout.created_at.isoformat() if payout.created_at else "",
                "paid_at": payout.paid_at.isoformat() if payout.paid_at else "",
            }
            for payout in RiderPayout.objects.filter(rider=session.rider).order_by("-created_at")[:30]
        ],
    }})


@csrf_exempt
@require_POST
def rider_status_action_api(request, action):
    try:
        session = _require_rider_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    rider = session.rider
    if action == "online":
        rider.is_online = True
    elif action == "offline":
        rider.is_online = False
        rider.is_available = False
    elif action == "available":
        rider.is_online = True
        rider.is_available = True
    elif action == "busy":
        rider.is_available = False
    else:
        return _error("Invalid rider status action.")
    rider.save(update_fields=["is_online", "is_available", "updated_at"])
    return JsonResponse({"success": True, "rider": _rider_payload(rider)})


@csrf_exempt
@require_POST
def rider_location_update_api(request):
    data = _json_body(request)
    try:
        session = _require_rider_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    rider = session.rider
    latitude = _money(data.get("latitude"), "0.0000000")
    longitude = _money(data.get("longitude"), "0.0000000")
    rider.current_latitude = latitude
    rider.current_longitude = longitude
    rider.last_location_at = timezone.now()
    rider.save(update_fields=["current_latitude", "current_longitude", "last_location_at", "updated_at"])
    delivery = None
    if data.get("delivery_id"):
        delivery = DeliveryRequest.objects.filter(id=data.get("delivery_id"), rider=rider).first()
    if not delivery:
        delivery = (
            DeliveryRequest.objects
            .filter(
                rider=rider,
                status__in=[
                    DeliveryRequest.STATUS_ASSIGNED,
                    DeliveryRequest.STATUS_ACCEPTED,
                    DeliveryRequest.STATUS_ARRIVED_PICKUP,
                    DeliveryRequest.STATUS_PICKED_UP,
                    DeliveryRequest.STATUS_IN_TRANSIT,
                    DeliveryRequest.STATUS_ARRIVED_CUSTOMER,
                ],
            )
            .order_by("-updated_at", "-created_at")
            .first()
        )
    if delivery:
        def optional_decimal(value):
            if value in [None, ""]:
                return None
            try:
                return Decimal(str(value))
            except (InvalidOperation, TypeError, ValueError):
                return None

        DeliveryLocationPing.objects.create(
            delivery=delivery,
            rider=rider,
            latitude=latitude,
            longitude=longitude,
            heading=optional_decimal(data.get("heading")),
            speed_kmph=optional_decimal(data.get("speed") or data.get("speed_kmph")),
            accuracy_meters=optional_decimal(data.get("accuracy") or data.get("accuracy_meters")),
        )
    return JsonResponse({"success": True, "rider": _rider_payload(rider)})


@csrf_exempt
@require_POST
def rider_push_token_api(request):
    data = _json_body(request)
    try:
        session = _require_rider_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    token = _clean_text(data.get("expo_push_token"))
    if not token:
        return _error("Expo push token is required.")
    rider = session.rider
    user = rider.user
    phone = _rider_phone(rider) or getattr(user, "phone_number", "")
    MobilePushToken.objects.update_or_create(
        expo_push_token=token,
        defaults={
            "phone_number": phone,
            "email": user.email or "",
            "device_name": _clean_text(data.get("device_name")) or "Arolana Staff App",
            "platform": _clean_text(data.get("platform")) or "",
            "is_active": True,
            "last_registered_at": timezone.now(),
        },
    )
    return JsonResponse({"success": True, "message": "Rider push token saved."})


@require_GET
def rider_messages_api(request):
    try:
        session = _require_rider_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    user = session.rider.user
    notes = Notification.objects.filter(user=user, notification_type="message", is_archived=False)[:100]
    conversations = [_smartchat_payload(item, "rider") for item in _staff_conversations_for_session(session)]
    return JsonResponse({"success": True, "conversations": conversations, "messages": [
        {"id": note.id, "title": note.title, "last_message": note.message, "unread_count": 0 if note.is_read else 1, "updated_at": note.created_at.isoformat() if note.created_at else ""}
        for note in notes
    ]})


@csrf_exempt
@require_POST
def rider_message_send_api(request):
    data = _json_body(request)
    try:
        session = _require_rider_session(request)
    except PermissionError as error:
        return _error(error, status=403)
    message = _clean_text(data.get("message"))
    if not message:
        return _error("Message is required.")
    subject = _clean_text(data.get("subject")) or "Rider support"
    conversation = _get_or_create_staff_conversation(
        session.rider.user,
        subject,
        {"staff_role": "rider", "rider_id": session.rider_id},
    )
    chat_message = SmartChatMessage.objects.create(
        conversation=conversation,
        sender_type=SmartChatMessage.SENDER_USER,
        user=session.rider.user,
        message=message,
        metadata={"recipient_type": data.get("recipient_type") or "admin", "staff_role": "rider"},
    )
    conversation.mark_admin_requested()
    admins = get_user_model().objects.filter(Q(is_staff=True) | Q(is_superuser=True), is_active=True)[:10]
    for admin_user in admins:
        _notify(admin_user, f"Rider message from {_rider_name(session.rider)}", message, "message", {"rider_id": session.rider_id, "smartchat_conversation_id": conversation.id, "smartchat_message_id": chat_message.id})
    return JsonResponse({"success": True, "message": "Message sent to admin.", "conversation": _smartchat_payload(conversation, "rider")})
