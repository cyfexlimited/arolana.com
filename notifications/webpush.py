import json

from django.conf import settings
from django.utils import timezone

from .models import NotificationPreference, WebPushSubscription

try:
    from pywebpush import WebPushException, webpush
except ImportError:  # pragma: no cover - production installs pywebpush.
    WebPushException = Exception
    webpush = None


TYPE_PREFERENCE_MAP = {
    'cart': 'cart_updates',
    'order': 'order_updates',
    'payment': 'order_updates',
    'message': 'message_alerts',
    'review': 'review_alerts',
    'vendor': 'vendor_alerts',
    'product': 'product_updates',
    'promotion': 'promotions',
    'shipping': 'order_updates',
    'security': 'security_alerts',
    'wishlist': 'product_updates',
}


def web_push_is_configured():
    return bool(
        getattr(settings, 'WEB_PUSH_ENABLED', True)
        and getattr(settings, 'WEB_PUSH_VAPID_PUBLIC_KEY', '')
        and getattr(settings, 'WEB_PUSH_VAPID_PRIVATE_KEY', '')
    )


def user_allows_push(notification):
    preferences, _ = NotificationPreference.objects.get_or_create(user=notification.user)

    if not preferences.push_notifications:
        return False

    if preferences.do_not_disturb:
        if not preferences.dnd_until or preferences.dnd_until > timezone.now():
            return False

    if preferences.is_in_quiet_hours():
        return False

    preference_field = TYPE_PREFERENCE_MAP.get(notification.notification_type)
    if preference_field and not getattr(preferences, preference_field, True):
        return False

    return True


def build_push_payload(notification):
    link = notification.link or '/notifications/'
    if not link.startswith(('http://', 'https://', '/')):
        link = '/notifications/'

    return {
        'title': notification.title or 'Arolana notification',
        'body': notification.message or '',
        'url': link,
        'tag': f'arolana-notification-{notification.id}',
        'notification_id': notification.id,
        'type': notification.notification_type,
        'icon': '/static/admin/images/arolana-logo.png',
        'badge': '/static/admin/images/favicon.ico',
    }


def _failure_status(exc):
    response = getattr(exc, 'response', None)
    return getattr(response, 'status_code', None)


def _mark_subscription_failure(subscription, exc):
    subscription.failure_count += 1
    subscription.last_failure_at = timezone.now()
    subscription.last_error = str(exc)[:1000]

    if _failure_status(exc) in (404, 410) or subscription.failure_count >= 5:
        subscription.is_active = False

    subscription.save(
        update_fields=[
            'failure_count',
            'last_failure_at',
            'last_error',
            'is_active',
            'updated_at',
        ]
    )


def send_web_push_notification(notification):
    if not web_push_is_configured() or webpush is None:
        return 0

    if not notification.user_id or not user_allows_push(notification):
        return 0

    payload = json.dumps(build_push_payload(notification))
    claims = {
        'sub': getattr(settings, 'WEB_PUSH_VAPID_SUBJECT', 'mailto:contact@arolana.com'),
    }
    ttl = int(getattr(settings, 'WEB_PUSH_TTL', 86400))
    delivered = 0

    subscriptions = WebPushSubscription.objects.filter(
        user=notification.user,
        is_active=True,
    )

    for subscription in subscriptions:
        try:
            webpush(
                subscription_info=subscription.subscription_info,
                data=payload,
                vapid_private_key=settings.WEB_PUSH_VAPID_PRIVATE_KEY,
                vapid_claims=claims,
                ttl=ttl,
            )
        except WebPushException as exc:
            _mark_subscription_failure(subscription, exc)
        except Exception as exc:
            _mark_subscription_failure(subscription, exc)
        else:
            delivered += 1
            subscription.failure_count = 0
            subscription.last_error = ''
            subscription.last_success_at = timezone.now()
            subscription.save(
                update_fields=[
                    'failure_count',
                    'last_error',
                    'last_success_at',
                    'updated_at',
                ]
            )

    if delivered:
        notification.push_sent = True
        notification.push_sent_at = timezone.now()
        notification.save(update_fields=['push_sent', 'push_sent_at', 'updated_at'])

    return delivered
