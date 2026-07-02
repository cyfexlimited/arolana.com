import json
from datetime import timedelta

from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from mobile_customers.views import _auth_mobile_customer_from_request_data
from staff_mobile.views import _auth_staff, _is_admin_user
from vendors.models import VendorProfile

from .models import VendorQuoteMessage, VendorQuoteRequest
from .quote_services import (
    notify_new_quote,
    quote_access_for_vendor,
    send_admin_customer_message,
    send_admin_vendor_message,
    send_vendor_message,
    serialize_quote,
)


def _payload(request):
    if request.method == "GET":
        data = request.GET.dict()
    else:
        try:
            data = json.loads(request.body.decode("utf-8") or "{}")
        except Exception:
            data = request.POST.dict()
    authorization = request.headers.get("Authorization", "")
    if authorization.lower().startswith("bearer ") and not data.get("api_token"):
        data["api_token"] = authorization.split(" ", 1)[1].strip()
    return data


def _identity(request, data=None):
    data = data or _payload(request)
    user = getattr(request, "user", None)
    if user and getattr(user, "is_authenticated", False):
        if _is_admin_user(user):
            return "admin", user, getattr(user, "vendor_profile", None)
        vendor = getattr(user, "vendor_profile", None)
        if vendor:
            return "vendor", user, vendor
        return "customer", user, None
    try:
        session = _auth_staff(request)
        if session.role == "admin" and _is_admin_user(session.user):
            return "admin", session.user, None
        if session.role == "vendor":
            return "vendor", session.user, getattr(session.user, "vendor_profile", None)
    except Exception:
        pass
    try:
        customer = _auth_mobile_customer_from_request_data(data)
        return "customer", customer.user, None
    except Exception:
        return "", None, None


def _error(message, status=400):
    return JsonResponse({"success": False, "message": message}, status=status)


def _role_queryset(role, user, vendor):
    queryset = VendorQuoteRequest.objects.select_related("vendor", "vendor__user", "customer").prefetch_related("messages__sender")
    if role == "admin":
        return queryset
    if role == "vendor" and vendor:
        return queryset.filter(vendor=vendor)
    if role == "customer" and user:
        return queryset.filter(customer=user)
    return queryset.none()


@require_GET
def quote_list_api(request):
    data = _payload(request)
    role, user, vendor = _identity(request, data)
    if not role:
        return _error("Authentication required.", 401)
    queryset = _role_queryset(role, user, vendor)
    status_filter = (request.GET.get("status") or "").strip()
    if status_filter:
        queryset = queryset.filter(status=status_filter)
    access = quote_access_for_vendor(user) if role == "vendor" else None
    return JsonResponse({
        "success": True,
        "role": role,
        "quotes": [serialize_quote(quote, role, access) for quote in queryset[:100]],
        "quote_access": access or {"can_respond": role == "admin", "upgrade_required": False},
    })


@require_GET
def quote_detail_api(request, quote_id):
    data = _payload(request)
    role, user, vendor = _identity(request, data)
    if not role:
        return _error("Authentication required.", 401)
    quote = get_object_or_404(_role_queryset(role, user, vendor), id=quote_id)
    access = quote_access_for_vendor(user) if role == "vendor" else None
    return JsonResponse({"success": True, "role": role, "quote": serialize_quote(quote, role, access)})


@csrf_exempt
@require_POST
def quote_create_api(request):
    data = _payload(request)
    role, user, _ = _identity(request, data)
    vendor = VendorProfile.objects.filter(
        id=data.get("vendor_id"),
        is_active=True,
    ).first()
    if not vendor:
        return _error("Choose a valid vendor before requesting a quote.")
    name = str(data.get("name") or (user.get_full_name() if user else "") or "").strip()
    email = str(data.get("email") or (getattr(user, "email", "") if user else "") or "").strip()
    phone = str(data.get("phone") or data.get("phone_number") or "").strip()
    message = str(data.get("message") or "").strip()
    if not name or not message or not (email or phone):
        return _error("Name, message, and email or phone are required.")
    quote = VendorQuoteRequest.objects.create(
        customer=user if role == "customer" else None,
        vendor=vendor,
        name=name,
        email=email,
        phone=phone,
        subject=str(data.get("subject") or f"Quote request for {vendor.store_name}").strip(),
        message=message,
        product_name=str(data.get("product_name") or "").strip()[:255],
        product_url=str(data.get("product_url") or "").strip(),
        status="sent_to_vendor",
        sent_to_vendor_at=timezone.now(),
        last_vendor_notified_at=timezone.now(),
        vendor_response_due_at=timezone.now() + timedelta(hours=6),
    )
    from .views import send_vendor_quote_notifications
    quote.email_notification_status = send_vendor_quote_notifications(quote)
    quote.save(update_fields=["email_notification_status", "updated_at"])
    notify_new_quote(quote)
    return JsonResponse({"success": True, "message": "Quote request sent successfully.", "quote": serialize_quote(quote, "customer")}, status=201)


@csrf_exempt
@require_POST
def vendor_response_api(request, quote_id):
    data = _payload(request)
    role, user, vendor = _identity(request, data)
    if role != "vendor" or not vendor:
        return _error("Vendor access required.", 403)
    quote = get_object_or_404(VendorQuoteRequest, id=quote_id, vendor=vendor)
    access = quote_access_for_vendor(user)
    if not access["can_respond"]:
        return JsonResponse({"success": False, **access, "message": access["subscription_message"]}, status=403)
    message = str(data.get("message") or data.get("vendor_response") or "").strip()
    if not message:
        return _error("Please enter your response before sending.")
    send_vendor_message(quote, user, message, customer_visible=bool(data.get("is_customer_visible", True)))
    quote.refresh_from_db()
    return JsonResponse({"success": True, "message": "Response sent successfully.", "quote": serialize_quote(quote, "vendor", quote_access_for_vendor(user))})


@csrf_exempt
@require_POST
def admin_vendor_message_api(request, quote_id):
    data = _payload(request)
    role, user, _ = _identity(request, data)
    if role != "admin":
        return _error("Admin access required.", 403)
    quote = get_object_or_404(VendorQuoteRequest, id=quote_id)
    message = str(data.get("message") or "").strip()
    if not message:
        return _error("Enter a message before sending.")
    send_admin_vendor_message(quote, user, message)
    quote.refresh_from_db()
    return JsonResponse({"success": True, "message": "Message sent to vendor.", "quote": serialize_quote(quote, "admin")})


@csrf_exempt
@require_POST
def admin_customer_response_api(request, quote_id):
    data = _payload(request)
    role, user, _ = _identity(request, data)
    if role != "admin":
        return _error("Admin access required.", 403)
    quote = get_object_or_404(VendorQuoteRequest, id=quote_id)
    message = str(data.get("message") or "").strip()
    if not message:
        return _error("Enter a customer response before sending.")
    send_admin_customer_message(quote, user, message)
    quote.refresh_from_db()
    return JsonResponse({"success": True, "message": "Customer update sent.", "quote": serialize_quote(quote, "admin")})


@csrf_exempt
@require_POST
def admin_internal_note_api(request, quote_id):
    data = _payload(request)
    role, user, _ = _identity(request, data)
    if role != "admin":
        return _error("Admin access required.", 403)
    quote = get_object_or_404(VendorQuoteRequest, id=quote_id)
    message = str(data.get("message") or "").strip()
    if not message:
        return _error("Enter an internal note before saving.")
    VendorQuoteMessage.objects.create(
        quote_request=quote,
        sender=user,
        sender_role="admin",
        message=message,
        is_internal=True,
        is_customer_visible=False,
        is_admin_message=True,
    )
    quote.internal_resolution_notes = message
    quote.assigned_admin = user
    quote.save(update_fields=["internal_resolution_notes", "assigned_admin", "updated_at"])
    return JsonResponse({
        "success": True,
        "message": "Internal note saved. It was not sent to the vendor or customer.",
        "quote": serialize_quote(quote, "admin"),
    })


@csrf_exempt
@require_POST
def quote_status_api(request, quote_id):
    data = _payload(request)
    role, user, _ = _identity(request, data)
    if role != "admin":
        return _error("Admin access required.", 403)
    quote = get_object_or_404(VendorQuoteRequest, id=quote_id)
    status_value = str(data.get("status") or "").strip()
    valid = {value for value, _ in VendorQuoteRequest.STATUS_CHOICES}
    if status_value not in valid:
        return _error("Invalid quote status.")
    quote.status = status_value
    if status_value == "closed":
        quote.closed_at = timezone.now()
    if data.get("escalate"):
        quote.escalation_status = "admin_followup"
        quote.is_admin_intervention_required = True
        quote.escalation_level = 2
    quote.save()
    return JsonResponse({"success": True, "message": "Quote status updated.", "quote": serialize_quote(quote, "admin")})
