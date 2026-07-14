"""Reliable multi-channel delivery for account subscription events."""

import json
import logging
import urllib.request

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db.models import Q
from django.template.loader import render_to_string
from django.utils import timezone

from notifications.models import Notification


logger = logging.getLogger(__name__)


def _contact_values(user):
    emails = {value.strip().lower() for value in [getattr(user, "email", "")] if value and value.strip()}
    phones = {
        str(value).strip()
        for value in [getattr(user, "phone", ""), getattr(user, "phone_number", "")]
        if value and str(value).strip()
    }
    vendor = getattr(user, "vendor_profile", None)
    provider = getattr(user, "service_provider_profile", None)
    if vendor:
        for value in [getattr(vendor, "support_email", ""), getattr(vendor, "business_email", "")]:
            if value and str(value).strip():
                emails.add(str(value).strip().lower())
        for value in [getattr(vendor, "support_phone", ""), getattr(vendor, "phone", "")]:
            if value and str(value).strip():
                phones.add(str(value).strip())
    if provider:
        for value in [getattr(provider, "email", ""), getattr(provider, "support_email", "")]:
            if value and str(value).strip():
                emails.add(str(value).strip().lower())
        for value in [getattr(provider, "phone_number", ""), getattr(provider, "support_phone", "")]:
            if value and str(value).strip():
                phones.add(str(value).strip())
    return sorted(emails), sorted(phones)


def _send_email(notification, email):
    context = {
        "user": notification.user,
        "title": notification.title,
        "message": notification.message,
        "subscription_url": f"{getattr(settings, 'SITE_URL', 'https://arolana.com').rstrip('/')}{notification.link}",
        "metadata": notification.metadata or {},
    }
    html = render_to_string("subscriptions/emails/subscription_event.html", context)
    email_message = EmailMultiAlternatives(
        subject=notification.title,
        body=notification.message,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "support@arolana.com"),
        to=[email],
    )
    email_message.attach_alternative(html, "text/html")
    email_message.send(fail_silently=False)


def _push_tokens(user):
    from orders.models import MobilePushToken

    emails, phones = _contact_values(user)
    lookup = Q()
    for email in emails:
        lookup |= Q(email__iexact=email)
    for phone in phones:
        lookup |= Q(phone_number=phone)
    if not emails and not phones:
        return []
    return list(
        MobilePushToken.objects.filter(lookup, is_active=True)
        .exclude(expo_push_token="")
        .values_list("expo_push_token", flat=True)
        .distinct()[:20]
    )


def _send_push(notification, tokens):
    metadata = notification.metadata or {}
    data = {
        "screen": metadata.get("target_screen", "Subscription"),
        "target_screen": metadata.get("target_screen", "Subscription"),
        "subscription_id": metadata.get("subscription_id"),
        "event": metadata.get("event") or metadata.get("subscription_event"),
    }
    payloads = [
        {
            "to": token,
            "sound": "default",
            "title": notification.title,
            "body": notification.message[:180],
            "data": data,
        }
        for token in tokens
    ]
    request = urllib.request.Request(
        "https://exp.host/--/api/v2/push/send",
        data=json.dumps(payloads).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(request, timeout=5).read()


def deliver_subscription_notification(notification):
    """Attempt email and push delivery without changing the business transaction."""
    delivery = dict((notification.metadata or {}).get("delivery") or {})
    now = timezone.now()

    if not notification.email_sent:
        emails, _ = _contact_values(notification.user)
        if emails:
            try:
                _send_email(notification, emails[0])
                notification.email_sent = True
                notification.email_sent_at = now
                delivery["email"] = {"status": "sent", "attempted_at": now.isoformat()}
            except Exception as error:
                logger.exception("Subscription email delivery failed for notification %s", notification.pk)
                delivery["email"] = {
                    "status": "failed",
                    "attempted_at": now.isoformat(),
                    "error": str(error)[:250],
                }
        else:
            delivery["email"] = {"status": "skipped_no_address", "attempted_at": now.isoformat()}

    if not notification.push_sent:
        try:
            tokens = _push_tokens(notification.user)
            if tokens:
                _send_push(notification, tokens)
                notification.push_sent = True
                notification.push_sent_at = now
                delivery["push"] = {
                    "status": "sent",
                    "attempted_at": now.isoformat(),
                    "token_count": len(tokens),
                }
            else:
                delivery["push"] = {"status": "skipped_no_token", "attempted_at": now.isoformat()}
        except Exception as error:
            logger.exception("Subscription push delivery failed for notification %s", notification.pk)
            delivery["push"] = {
                "status": "failed",
                "attempted_at": now.isoformat(),
                "error": str(error)[:250],
            }

    metadata = dict(notification.metadata or {})
    metadata["delivery"] = delivery
    notification.metadata = metadata
    notification.save(
        update_fields=["metadata", "email_sent", "email_sent_at", "push_sent", "push_sent_at", "updated_at"]
    )
    return notification


def dispatch_subscription_notification(user, title, message, metadata=None, priority=3):
    payload = {
        "target_screen": "Subscription",
        "web_url": "/subscriptions/history/",
        **(metadata or {}),
    }
    if "event" in payload and "subscription_event" not in payload:
        payload["subscription_event"] = payload["event"]
    notification = Notification.send(
        user,
        "payment",
        title,
        message,
        link="/subscriptions/history/",
        metadata=payload,
        priority=priority,
    )
    return deliver_subscription_notification(notification)


def retry_failed_subscription_notifications(limit=100):
    notifications = Notification.objects.filter(
        notification_type="payment",
        metadata__target_screen="Subscription",
    ).filter(Q(email_sent=False) | Q(push_sent=False)).order_by("created_at")[:limit]
    retried = 0
    for notification in notifications:
        delivery = (notification.metadata or {}).get("delivery") or {}
        retryable = any(
            (delivery.get(channel) or {}).get("status") == "failed"
            for channel in ("email", "push")
        )
        if retryable:
            deliver_subscription_notification(notification)
            retried += 1
    return retried
