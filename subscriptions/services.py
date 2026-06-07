from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from notifications.models import Notification
from products.models import Product
from vendors.models import VendorProfile

from .models import VendorSubscription, apply_vendor_subscription_benefits, get_tier_limits, normalize_subscription_tier, subscription_label


def _vendor_phone(profile):
    user_phone = getattr(profile.user, "phone_number", "") or getattr(profile.user, "phone", "")
    return profile.support_phone or profile.pickup_phone or user_phone or ""


def _send_subscription_email(profile, subject, message):
    email = profile.support_email or profile.user.email
    if not email:
        return False
    try:
        send_mail(subject, message, getattr(settings, "DEFAULT_FROM_EMAIL", None), [email], fail_silently=True)
        return True
    except Exception:
        return False


def _send_subscription_sms(profile, message):
    phone = _vendor_phone(profile)
    if not phone or not getattr(settings, "SMS_CONFIGURED", False):
        return False
    try:
        from twilio.rest import Client

        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        kwargs = {"body": message[:1500], "to": phone}
        if settings.TWILIO_MESSAGING_SERVICE_SID:
            kwargs["messaging_service_sid"] = settings.TWILIO_MESSAGING_SERVICE_SID
        else:
            kwargs["from_"] = settings.TWILIO_FROM_NUMBER
        client.messages.create(**kwargs)
        return True
    except Exception:
        return False


def notify_vendor_subscription(profile, title, message, key, priority=3):
    if Notification.objects.filter(user=profile.user, metadata__subscription_robot_key=key).exists():
        return None
    notification = Notification.send(
        user=profile.user,
        notification_type="payment",
        title=title,
        message=message,
        link="/subscriptions/plans/",
        metadata={
            "subscription_robot_key": key,
            "vendor_profile_id": profile.id,
            "subscription_tier": normalize_subscription_tier(profile.subscription_tier),
            "phone_attempted": bool(_vendor_phone(profile)),
        },
        priority=priority,
    )
    email_sent = _send_subscription_email(profile, title, message)
    sms_sent = _send_subscription_sms(profile, message)
    metadata = dict(notification.metadata or {})
    metadata.update({"email_sent": email_sent, "sms_sent": sms_sent})
    notification.metadata = metadata
    notification.email_sent = email_sent
    if email_sent:
        notification.email_sent_at = timezone.now()
    notification.save(update_fields=["metadata", "email_sent", "email_sent_at", "updated_at"])
    return notification


def enforce_vendor_product_visibility(profile):
    tier = normalize_subscription_tier(profile.subscription_tier)
    expiry = getattr(profile, "subscription_expires_at", None) or profile.subscription_expiry
    if expiry and expiry <= timezone.now():
        tier = "free"
    limit = get_tier_limits(tier)["max_products"]
    approved = Product.objects.filter(vendor=profile.user, approval_status="approved").order_by("created_at", "id")
    if limit == -1:
        approved.update(is_active=True)
        return {"public": approved.count(), "hidden": 0, "tier": tier}
    visible_ids = list(approved.values_list("id", flat=True)[:limit])
    hidden = approved.exclude(id__in=visible_ids)
    Product.objects.filter(id__in=visible_ids).update(is_active=True)
    hidden.update(is_active=False)
    return {"public": len(visible_ids), "hidden": hidden.count(), "tier": tier}


@transaction.atomic
def run_subscription_robot(now=None):
    now = now or timezone.now()
    stats = {"expiring": 0, "expired": 0, "visibility_updated": 0}

    active_subscriptions = (
        VendorSubscription.objects
        .select_related("vendor", "plan", "vendor__vendor_profile")
        .filter(is_active=True)
        .order_by("end_date")
    )

    for subscription in active_subscriptions:
        profile = getattr(subscription.vendor, "vendor_profile", None)
        if not profile:
            continue

        days_left = (subscription.end_date.date() - now.date()).days
        if days_left in {7, 3, 1} and subscription.end_date > now:
            tier = normalize_subscription_tier(subscription.plan.name)
            upgrade_note = "" if tier == "enterprise" else " You can renew now or upgrade to a higher plan for stronger visibility and more selling tools."
            message = (
                f"Your Arolana {subscription_label(tier)} plan will expire in {days_left} day{'s' if days_left != 1 else ''}, on {subscription.end_date:%d %b %Y}. "
                f"Renew before this date to keep your current product visibility, customer chat, and seller tools active."
                f"{upgrade_note}"
            )
            key = f"subscription-expiring-{subscription.id}-{days_left}-{subscription.end_date:%Y%m%d}"
            if notify_vendor_subscription(profile, f"Your Arolana plan expires in {days_left} day{'s' if days_left != 1 else ''}", message, key):
                stats["expiring"] += 1

        if subscription.end_date <= now:
            subscription.is_active = False
            subscription.auto_renew = False
            subscription.save(update_fields=["is_active", "auto_renew", "updated_at"])
            profile.subscription_tier = "free"
            profile.subscription_active = False
            profile.subscription_started_at = None
            profile.subscription_expires_at = None
            profile.subscription_expiry = None
            profile.priority_score = get_tier_limits("free")["priority_score"]
            profile.save(update_fields=["subscription_tier", "subscription_active", "subscription_started_at", "subscription_expires_at", "subscription_expiry", "priority_score", "updated_at"])
            apply_vendor_subscription_benefits(profile, "free")
            profile.refresh_from_db()
            visibility = enforce_vendor_product_visibility(profile)
            message = (
                "Your Arolana subscription has ended, so your account has returned to Free. "
                "Your first approved product remains public. Additional approved products are kept safely in your vendor product list "
                "and will become public again when you renew or choose a paid plan."
            )
            key = f"subscription-expired-{subscription.id}-{now:%Y%m%d}"
            notify_vendor_subscription(profile, "Your Arolana plan has ended", message, key, priority=4)
            stats["expired"] += 1
            stats["visibility_updated"] += visibility["hidden"]

    for profile in VendorProfile.objects.select_related("user").filter(subscription_tier="free"):
        enforce_vendor_product_visibility(profile)

    return stats
