from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from accounts.models import User

from .models import EmailAudienceMember, NewsletterSubscriber


def upsert_email_audience(email, name='', source='manual', user=None, subscriber=None, accepts_promos=True):
    if not email:
        return None

    member, created = EmailAudienceMember.objects.get_or_create(
        email=email,
        defaults={
            'name': name,
            'source': source,
            'user': user,
            'subscriber': subscriber,
            'accepts_promos': accepts_promos,
            'last_synced_at': timezone.now(),
        },
    )
    if not created:
        sources = {member.source, source}
        if 'registered' in sources and 'newsletter' in sources:
            member.source = 'both'
        elif source != 'manual':
            member.source = source if member.source == 'manual' else member.source
        member.name = member.name or name
        member.user = member.user or user
        member.subscriber = member.subscriber or subscriber
        member.accepts_promos = member.accepts_promos or accepts_promos
        member.is_active = True
        member.last_synced_at = timezone.now()
        member.save()
    return member


def sync_email_audience():
    synced = 0
    for user in User.objects.filter(is_active=True).exclude(email=''):
        try:
            profile = user.profile
        except Exception:
            profile = None
        accepts_promos = bool(getattr(profile, 'promo_emails', True))
        if upsert_email_audience(
            user.email,
            name=user.get_full_name() or user.username,
            source='registered',
            user=user,
            accepts_promos=accepts_promos,
        ):
            synced += 1

    for subscriber in NewsletterSubscriber.objects.filter(is_active=True):
        if upsert_email_audience(
            subscriber.email,
            name=subscriber.name,
            source='newsletter',
            subscriber=subscriber,
            accepts_promos=True,
        ):
            synced += 1
    return synced


def campaign_recipient_emails(campaign):
    sync_email_audience()
    audience = EmailAudienceMember.objects.filter(is_active=True)
    if campaign.recipient_scope == 'subscribers':
        audience = audience.filter(source__in=['newsletter', 'both'])
    elif campaign.recipient_scope == 'registered':
        audience = audience.filter(source__in=['registered', 'both'])
    return sorted(audience.values_list('email', flat=True).distinct())


def send_campaign(campaign):
    recipients = campaign_recipient_emails(campaign)
    sent_count = 0
    for email in recipients:
        send_mail(
            campaign.subject,
            campaign.content,
            settings.DEFAULT_FROM_EMAIL,
            [email],
            html_message=campaign.html_content or None,
            fail_silently=True,
        )
        sent_count += 1

    campaign.sent_count += sent_count
    campaign.status = 'sent'
    campaign.sent_at = timezone.now()
    campaign.last_sent_at = campaign.sent_at
    campaign.save(update_fields=['sent_count', 'status', 'sent_at', 'last_sent_at', 'updated_at'])
    return sent_count
