import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from notifications.models import Notification
from subscriptions.models import subscription_label, user_subscription_limits, user_subscription_tier

from .models import VendorQuoteMessage, VendorQuoteRequest

logger = logging.getLogger(__name__)


def quote_notification_metadata(quote, role):
    screens = {
        "customer": "QuoteDetail",
        "vendor": "VendorQuoteDetail",
        "admin": "StaffQuoteDetail",
    }
    return {
        "type": "quote_request",
        "quote_id": quote.id,
        "quote_request_id": quote.id,
        "target_screen": screens[role],
        "role": role,
    }


def quote_action_url(quote, role):
    if role == "vendor":
        return reverse("dashboard:vendor_quote_requests")
    if role == "admin":
        return reverse("admin:core_vendorquoterequest_change", args=[quote.id])
    if role == "customer" and quote.customer_id:
        return reverse("core:customer_quote_request_detail", args=[quote.id])
    return ""


def quote_access_for_vendor(user):
    limits = user_subscription_limits(user)
    limit = limits.get("quote_responses_per_month", limits.get("max_quote_responses_per_month", 0))
    limit = int(limit)
    month_start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    used = VendorQuoteMessage.objects.filter(
        quote_request__vendor__user=user,
        sender_role="vendor",
        created_at__gte=month_start,
    ).count()
    allowed = limit < 0 or used < limit
    return {
        "can_respond": allowed,
        "allowed": allowed,
        "upgrade_required": not allowed,
        "subscription_message": (
            "" if allowed else
            "Your current plan has reached the quote response limit. Upgrade to continue responding."
        ),
        "responses_used_this_month": used,
        "responses_limit": "unlimited" if limit < 0 else limit,
        "limit": limit,
        "used": used,
        "remaining": -1 if limit < 0 else max(limit - used, 0),
        "chat_enabled": bool(limits.get("quote_chat_enabled", True)),
        "plan": subscription_label(user_subscription_tier(user)),
    }


def safe_quote_email(subject, body, recipients):
    recipients = [value for value in recipients if value]
    if not recipients:
        return False
    try:
        send_mail(
            subject,
            body,
            getattr(settings, "DEFAULT_FROM_EMAIL", None),
            recipients,
            fail_silently=False,
        )
        return True
    except Exception:
        logger.exception("Quote email failed: %s", subject)
        return False


def create_quote_notification(user, quote, role, title, message, priority=3):
    if not user:
        return None
    return Notification.send(
        user=user,
        notification_type="vendor",
        title=title,
        message=message,
        link=quote_action_url(quote, role),
        metadata=quote_notification_metadata(quote, role),
        priority=priority,
    )


def notify_new_quote(quote):
    create_quote_notification(
        quote.vendor.user,
        quote,
        "vendor",
        "New quote request for your store",
        f"{quote.name} requested a quote for {quote.product_name or quote.vendor.store_name}.",
    )
    for admin_user in User.objects.filter(
        Q(is_staff=True) | Q(is_superuser=True), is_active=True
    ).distinct()[:20]:
        create_quote_notification(
            admin_user,
            quote,
            "admin",
            f"New quote request from {quote.name}",
            f"{quote.vendor.store_name}: {quote.subject}",
        )
    if quote.customer_id:
        create_quote_notification(
            quote.customer,
            quote,
            "customer",
            "We received your quote request",
            f"Arolana and {quote.vendor.store_name} received your request.",
            priority=2,
        )


def send_vendor_message(quote, sender, message, customer_visible=True):
    note = VendorQuoteMessage.objects.create(
        quote_request=quote,
        sender=sender,
        recipient=quote.assigned_admin,
        sender_role="vendor",
        message=message,
        is_vendor_message=True,
        is_customer_visible=customer_visible,
    )
    now = timezone.now()
    quote.vendor_response = message
    quote.vendor_responded_at = now
    quote.status = "vendor_replied"
    quote.escalation_status = "none"
    quote.escalation_level = 0
    quote.is_admin_intervention_required = False
    quote.save(update_fields=[
        "vendor_response", "vendor_responded_at", "status", "escalation_status",
        "escalation_level", "is_admin_intervention_required", "updated_at",
    ])
    admins = User.objects.filter(Q(is_staff=True) | Q(is_superuser=True), is_active=True).distinct()[:20]
    for admin_user in admins:
        create_quote_notification(
            admin_user, quote, "admin", "Vendor has responded to quote request",
            f"{quote.vendor.store_name} responded to quote #{quote.id}.",
        )
    admin_email = getattr(settings, "AROLANA_SUPPORT_EMAIL", "") or getattr(settings, "DEFAULT_FROM_EMAIL", "")
    safe_quote_email(
        "Vendor has responded to quote request",
        f"{quote.vendor.store_name} responded to quote #{quote.id}.\n\n{message}\n\n{quote_action_url(quote, 'admin')}",
        [admin_email],
    )
    if customer_visible:
        if quote.customer_id:
            create_quote_notification(
                quote.customer, quote, "customer", "Arolana has responded to your quote request",
                f"{quote.vendor.store_name} sent an update for quote #{quote.id}.",
            )
        if safe_quote_email(
            "Your Arolana quote request update",
            f"{quote.subject}\n\n{quote.vendor.store_name} responded:\n{message}\n\nArolana support can help with the next step.",
            [quote.email],
        ):
            quote.last_customer_notified_at = now
            quote.customer_last_notified_at = now
            quote.save(update_fields=["last_customer_notified_at", "customer_last_notified_at", "updated_at"])
    return note


def send_admin_vendor_message(quote, sender, message):
    note = VendorQuoteMessage.objects.create(
        quote_request=quote,
        sender=sender,
        recipient=quote.vendor.user,
        sender_role="admin",
        message=message,
        is_admin_message=True,
    )
    now = timezone.now()
    quote.status = "sent_to_vendor"
    quote.assigned_admin = sender
    quote.admin_last_followed_up_at = now
    quote.last_vendor_notified_at = now
    quote.vendor_response_due_at = now + timedelta(hours=6)
    quote.save(update_fields=[
        "status", "assigned_admin", "admin_last_followed_up_at",
        "last_vendor_notified_at", "vendor_response_due_at", "updated_at",
    ])
    create_quote_notification(
        quote.vendor.user, quote, "vendor", "Arolana admin sent you a quote message", message[:220],
    )
    safe_quote_email(
        "Arolana admin sent you a quote message",
        f"Quote #{quote.id}: {quote.subject}\n\n{message}\n\nOpen: {quote_action_url(quote, 'vendor')}",
        [quote.vendor.user.email],
    )
    return note


def send_admin_customer_message(quote, sender, message):
    note = VendorQuoteMessage.objects.create(
        quote_request=quote,
        sender=sender,
        recipient=quote.customer,
        sender_role="admin",
        message=message,
        is_admin_message=True,
        is_customer_visible=True,
    )
    now = timezone.now()
    quote.admin_customer_response = message
    quote.status = "customer_updated"
    quote.last_customer_notified_at = now
    quote.customer_last_notified_at = now
    quote.save(update_fields=[
        "admin_customer_response", "status", "last_customer_notified_at",
        "customer_last_notified_at", "updated_at",
    ])
    if quote.customer_id:
        create_quote_notification(
            quote.customer, quote, "customer", "Arolana has responded to your quote request", message[:220],
        )
    safe_quote_email(
        "Your Arolana quote request update",
        f"{quote.subject}\n\nArolana update:\n{message}\n\nContact Arolana support if you need help.",
        [quote.email],
    )
    return note


def serialize_quote_message(note):
    sender_name = "Arolana"
    if note.sender:
        sender_name = note.sender.get_full_name() or note.sender.username or note.sender.email
    return {
        "id": note.id,
        "sender": sender_name,
        "sender_role": note.sender_role,
        "message": note.message,
        "is_internal": note.is_internal,
        "is_customer_visible": note.is_customer_visible,
        "created_at": note.created_at.isoformat(),
        "read_at": note.read_at.isoformat() if note.read_at else "",
    }


def serialize_quote(quote, role, access=None):
    messages = quote.messages.select_related("sender")
    if role == "customer":
        messages = messages.filter(is_internal=False, is_customer_visible=True)
    elif role == "vendor":
        messages = messages.filter(is_internal=False)
    payload = {
        "id": quote.id,
        "subject": quote.subject,
        "message": quote.message,
        "name": quote.name,
        "email": quote.email if role in {"vendor", "admin"} else "",
        "phone": quote.phone if role in {"vendor", "admin"} else "",
        "vendor_id": quote.vendor_id,
        "vendor_name": quote.vendor.store_name,
        "product_name": quote.product_name,
        "product_url": quote.product_url,
        "status": quote.status,
        "status_label": quote.get_status_display(),
        "escalation_status": quote.escalation_status,
        "vendor_response": quote.vendor_response,
        "admin_customer_response": quote.admin_customer_response if role in {"customer", "admin"} else "",
        "created_at": quote.created_at.isoformat(),
        "updated_at": quote.updated_at.isoformat(),
        "messages": [serialize_quote_message(note) for note in messages],
    }
    if role == "admin":
        payload["admin_notes"] = quote.admin_notes
        payload["internal_resolution_notes"] = quote.internal_resolution_notes
    if access:
        payload.update(access)
    return payload
