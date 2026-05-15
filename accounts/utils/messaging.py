from collections import defaultdict

from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse

from accounts.models import RegistrationMessageTemplate


class SafeFormatDict(defaultdict):
    def __missing__(self, key):
        return '{' + key + '}'


def registration_message_context(user, request=None):
    site_name = 'Arolana'
    if request is not None:
        site_settings = getattr(request, 'site_settings', None)
        if site_settings:
            site_name = getattr(site_settings, 'site_name', site_name)

    base_url = getattr(settings, 'SITE_URL', '').rstrip('/')
    login_url = reverse('accounts:login')
    profile_url = reverse('accounts:profile')

    return SafeFormatDict(str, {
        'first_name': user.first_name or '',
        'last_name': user.last_name or '',
        'full_name': user.get_full_name() or user.username or user.email,
        'username': user.username or user.email,
        'email': user.email,
        'account_type': user.get_user_type_display(),
        'site_name': site_name,
        'login_url': f'{base_url}{login_url}' if base_url else login_url,
        'profile_url': f'{base_url}{profile_url}' if base_url else profile_url,
    })


def sync_newsletter_subscriber(user, subscribe=True, source='registration'):
    if not subscribe or not user.email:
        return None

    try:
        from newsletter.models import NewsletterSubscriber
    except Exception:
        return None

    subscriber, created = NewsletterSubscriber.objects.get_or_create(
        email=user.email,
        defaults={
            'name': user.get_full_name() or user.username,
            'source': source,
            'is_active': True,
        },
    )
    if not created:
        subscriber.name = subscriber.name or user.get_full_name() or user.username
        subscriber.is_active = True
        subscriber.unsubscribed_at = None
        subscriber.save(update_fields=['name', 'is_active', 'unsubscribed_at', 'updated_at'])
    try:
        from newsletter.emailing import upsert_email_audience
        upsert_email_audience(
            user.email,
            name=user.get_full_name() or user.username,
            source='newsletter',
            user=user,
            subscriber=subscriber,
            accepts_promos=True,
        )
    except Exception:
        pass
    return subscriber


def send_registration_messages(user, request=None):
    from notifications.models import Notification

    context = registration_message_context(user, request)
    templates = RegistrationMessageTemplate.objects.filter(
        is_active=True,
        role__in=['all', user.user_type],
    )

    if not templates.exists():
        Notification.objects.create(
            user=user,
            notification_type='success',
            title='Welcome to Arolana',
            message='Your account is ready. Complete your profile to get the best marketplace experience.',
            link='/accounts/profile/',
        )
        return 0

    sent_count = 0
    for template in templates:
        subject = template.render_subject(context)
        body = template.render_body(context)
        if template.channel in ['email', 'both']:
            send_mail(
                subject,
                body,
                settings.DEFAULT_FROM_EMAIL,
                [user.email],
                fail_silently=True,
            )
            sent_count += 1
        if template.channel in ['notification', 'both']:
            Notification.objects.create(
                user=user,
                notification_type='success',
                title=template.notification_title or subject,
                message=body,
                link=template.notification_link or '/accounts/profile/',
            )
    return sent_count
