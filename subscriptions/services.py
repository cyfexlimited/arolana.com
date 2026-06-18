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
def sync_vendor_subscription_profile(user_or_profile, now=None, enforce_visibility=True):
    """Make VendorProfile match the current non-expired subscription source of truth."""
    now = now or timezone.now()
    profile = user_or_profile if isinstance(user_or_profile, VendorProfile) else getattr(user_or_profile, "vendor_profile", None)
    if not profile:
        return None
    user = profile.user

    expired = (
        VendorSubscription.objects
        .filter(vendor=user, is_active=True, end_date__lte=now)
        .update(is_active=False, auto_renew=False, updated_at=now)
    )

    current = (
        VendorSubscription.objects
        .filter(vendor=user, is_active=True, end_date__gt=now)
        .select_related("plan")
        .order_by("-end_date", "-created_at")
        .first()
    )

    if current:
        profile.subscription_active = True
        profile.subscription_started_at = current.start_date
        profile.subscription_expires_at = current.end_date
        profile.subscription_expiry = current.end_date
        profile.save(update_fields=[
            "subscription_active",
            "subscription_started_at",
            "subscription_expires_at",
            "subscription_expiry",
            "updated_at",
        ])
        apply_vendor_subscription_benefits(profile, current.plan)
    else:
        profile.subscription_active = False
        profile.subscription_started_at = None
        profile.subscription_expires_at = None
        profile.subscription_expiry = None
        profile.save(update_fields=[
            "subscription_active",
            "subscription_started_at",
            "subscription_expires_at",
            "subscription_expiry",
            "updated_at",
        ])
        apply_vendor_subscription_benefits(profile, "free")

    profile.refresh_from_db()
    visibility = enforce_vendor_product_visibility(profile) if enforce_visibility else None
    return {
        "profile": profile,
        "current_subscription": current,
        "expired_count": expired,
        "visibility": visibility,
    }


def sync_all_vendor_subscription_profiles(now=None, enforce_visibility=True):
    now = now or timezone.now()
    vendor_ids = set(
        VendorSubscription.objects.values_list("vendor_id", flat=True)
    )
    vendor_ids.update(
        VendorProfile.objects.exclude(subscription_tier="free").values_list("user_id", flat=True)
    )
    vendor_ids.update(
        VendorProfile.objects.filter(subscription_active=True).values_list("user_id", flat=True)
    )
    stats = {"synced": 0, "active": 0, "free": 0, "expired": 0, "visibility_hidden": 0}
    for profile in VendorProfile.objects.select_related("user").filter(user_id__in=vendor_ids):
        result = sync_vendor_subscription_profile(profile, now=now, enforce_visibility=enforce_visibility)
        if not result:
            continue
        stats["synced"] += 1
        stats["expired"] += result.get("expired_count", 0)
        if result.get("current_subscription"):
            stats["active"] += 1
        else:
            stats["free"] += 1
        visibility = result.get("visibility") or {}
        stats["visibility_hidden"] += visibility.get("hidden", 0)
    return stats


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
            result = sync_vendor_subscription_profile(profile, now=now, enforce_visibility=True)
            visibility = (result or {}).get("visibility") or {"hidden": 0}
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
